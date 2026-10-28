"""Contract tests use local stubs; never train a model or upload to AWS."""
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


def wav(seconds=30, silent=False, rate=48000):
    out = io.BytesIO()
    with wave.open(out, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        sample = b"\0\0" if silent else struct.pack("<h", 6000)
        audio.writeframes(sample * int(seconds * rate))
    return out.getvalue()


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bridge = server.Bridge(Path(self.temp.name))
        self.bridge.api_key = "test-only-never-sent"
        self.s3 = Mock()
        self.bridge.s3 = Mock(return_value=self.s3)
        self.bridge.upstream = Mock(return_value={"job_id": "job_123", "status": "queued"})
        self.audio = wav()

    def tearDown(self):
        self.temp.cleanup()

    def test_complete_pcm_and_not_silence(self):
        self.assertEqual(server.validate_wav(self.audio)["duration_seconds"], 30)
        for data in (wav(29.999), wav(30, silent=True), self.audio[:-100], b"not a WAV"):
            with self.subTest(size=len(data)), self.assertRaises(server.BridgeError):
                server.validate_wav(data)

    def test_upload_and_exact_documented_training_payload(self):
        job = self.bridge.train(self.audio, "test_001", "My Voice", {"game": "echo"})
        self.assertEqual(job["job_id"], "job_123")
        self.s3.put_object.assert_called_once_with(
            Bucket="hookmlbucket",
            Key="voice_swap/inputs/raw_vocals_for_training/test_001/stardust-30-seconds.wav",
            Body=self.audio, ContentType="audio/wav")
        self.bridge.upstream.assert_called_once_with("POST", "/api/training", {
            "training_set_id": "test_001", "model_name": "My Voice", "epochs": 400,
            "f0_method": "harvest"})
        self.assertEqual(job["capture_metadata"]["game"], "echo")

    def test_repeated_submission_recovers_same_job_without_upload(self):
        self.bridge.train(self.audio, "same_id", "My Voice")
        repeated = self.bridge.train(self.audio, "same_id", "My Voice")
        self.assertEqual(repeated["job_id"], "job_123")
        self.assertEqual(self.s3.put_object.call_count, 1)
        self.assertEqual(self.bridge.upstream.call_count, 1)
        recovered = server.Bridge(Path(self.temp.name))
        self.assertEqual(recovered.state["jobs"]["job_123"]["model_name"], "My Voice")
        self.assertEqual(recovered.state_path.stat().st_mode & 0o777, 0o600)

    def test_uncertain_network_submission_is_not_repeated(self):
        self.bridge.upstream.side_effect = server.BridgeError(503, "Network timeout", "upstream_unavailable")
        with self.assertRaises(server.BridgeError):
            self.bridge.train(self.audio, "uncertain", "My Voice")
        with self.assertRaises(server.BridgeError) as caught:
            self.bridge.train(self.audio, "uncertain", "My Voice")
        self.assertEqual(caught.exception.code, "submission_unknown")
        self.assertEqual(self.bridge.upstream.call_count, 1)

    def test_invalid_inputs_never_upload(self):
        for args in ((wav(29), "good", "Voice"), (self.audio, "../bad", "Voice"),
                     (self.audio, "good", "<script>")):
            with self.assertRaises(server.BridgeError):
                self.bridge.train(*args)
        self.s3.put_object.assert_not_called()

    def test_poll_stores_real_model_and_terminal_status(self):
        self.bridge.train(self.audio, "test_002", "Voice")
        self.bridge.upstream.return_value = {"status": "succeeded", "result": {"model_id": "model_123"},
                                            "summary": {"stage": "complete", "percent_complete": 100}}
        job = self.bridge.get_job("job_123")
        self.assertEqual(job["result"]["model_id"], "model_123")
        self.assertEqual(job["progress"], {"stage": "complete", "percent_complete": 100})
        self.bridge.upstream.reset_mock()
        self.assertEqual(self.bridge.get_job("job_123")["status"], "succeeded")
        self.bridge.upstream.assert_not_called()

    def test_api_key_uses_verified_secret_and_stays_out_of_status_and_history(self):
        self.bridge.api_key = ""
        session = Mock()
        secret = "test-secret-not-for-browser"
        session.client.return_value.get_secret_value.return_value = {"SecretString": secret}
        self.bridge.aws_session = Mock(return_value=session)
        self.assertEqual(self.bridge.resolve_api_key(), secret)
        session.client.return_value.get_secret_value.assert_called_once_with(SecretId="voice-swap-dev/api-key")
        self.bridge.health = Mock(return_value=True)
        status = self.bridge.status()
        self.assertTrue(status["ready"])
        self.assertNotIn(secret, json.dumps(status))
        self.assertNotIn(secret, json.dumps(self.bridge.state))

    def test_transform_uses_single_file_and_real_ready_model(self):
        with self.assertRaises(server.BridgeError):
            self.bridge.transform(self.audio, "unknown", "voice.wav", "audio/wav")
        self.bridge.state["jobs"]["trained"] = {"kind": "training", "status": "succeeded",
                                                  "result": {"model_id": "model_123"}}
        self.bridge.transform(self.audio, "model_123", "my%20voice.wav", "audio/wav")
        method, path, body, content_type = self.bridge.upstream.call_args.args
        self.assertEqual((method, path), ("POST", "/api/transformations"))
        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="model_id"\r\n\r\nmodel_123\r\n', body)
        self.assertIn(b'name="file"; filename="my voice.wav"', body)
        self.assertNotIn(b'name="isrc"', body)
        self.assertIn(self.audio, body)

    def test_results_cannot_fetch_arbitrary_bucket_or_path(self):
        self.bridge.state["jobs"]["done"] = {"job_id": "done", "kind": "transformation",
            "model_id": "model_123", "status": "succeeded", "result": {}}
        for location in ("s3://other/private.wav", "voice_swap/outputs/another/voice.wav",
                         "voice_swap/outputs/model_123/../private.wav", "https://attacker.test/file"):
            self.bridge.state["jobs"]["done"]["result"] = {"output_s3_uri": location}
            with self.assertRaises(server.BridgeError):
                self.bridge.result("done")
        self.s3.get_object.assert_not_called()
        self.bridge.state["jobs"]["done"]["result"] = {
            "output_s3_uri": "s3://hookmlbucket/voice_swap/outputs/model_123/voice.wav"}
        self.bridge.result("done")
        self.s3.get_object.assert_called_once_with(Bucket="hookmlbucket",
            Key="voice_swap/outputs/model_123/voice.wav")


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bridge = server.Bridge(Path(self.temp.name))
        self.bridge.train = Mock(return_value={"job_id": "local_stub", "status": "queued"})
        self.http = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.http.bridge = self.bridge
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.http.server_address[1]}"

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        self.temp.cleanup()

    def test_private_files_are_not_served(self):
        for path in ("/.env.local", "/.runtime/jobs.json", "/songs/data.json", "/source/app.html", "/../server.py"):
            with self.subTest(path=path), self.assertRaises(HTTPError) as caught:
                urlopen(self.base + path)
            self.assertEqual(caught.exception.code, 404)

    def test_cross_origin_and_missing_client_requests_are_rejected(self):
        for headers in ({"Content-Type": "audio/wav"},
                        {"Content-Type": "audio/wav", "X-Stardust-Client": "1", "Origin": "https://elsewhere.test"}):
            request = Request(self.base + "/api/training", data=b"blocked before audio is read", headers=headers)
            with self.assertRaises(HTTPError) as caught:
                urlopen(request)
            self.assertEqual(caught.exception.code, 403)
        self.bridge.train.assert_not_called()

    def test_same_origin_raw_wav_contract(self):
        request = Request(self.base + "/api/training", data=wav(), headers={
            "Content-Type": "audio/wav", "X-Stardust-Client": "1",
            "X-Model-Name": "Test Voice", "X-Training-Set-Id": "capture_1",
            "Origin": self.base})
        with urlopen(request) as response:
            self.assertEqual(response.status, 202)
            self.assertEqual(json.load(response)["job_id"], "local_stub")
        self.assertEqual(self.bridge.train.call_args.args[1:3], ("capture_1", "Test Voice"))


if __name__ == "__main__":
    unittest.main()
