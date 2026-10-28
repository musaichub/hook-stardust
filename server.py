#!/usr/bin/env python3
"""Local-only Stardust capture and documented HOOK Voice Swap API bridge.

Credentials stay in this process. Nothing is uploaded until a POST initiated by
the app. The private service must be reachable through the user's HOOK network.
"""
from __future__ import annotations

import argparse
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import re
import socket
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen
import uuid
import wave

ROOT = Path(__file__).resolve().parent
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9 _-]{1,128}$")
BUCKET = "hookmlbucket"
REGION = "us-east-2"
INPUT_PREFIX = "voice_swap/inputs/raw_vocals_for_training/"
OUTPUT_PREFIX = "voice_swap/outputs/"
MAX_TRAINING_BYTES = 12_000_000
MAX_TRANSFORM_BYTES = 50_000_000
TERMINAL = {"succeeded", "failed", "cancelled", "canceled"}
ENV_KEYS = {
    "VOICE_SWAP_API_KEY", "VOICE_SWAP_SERVICE_API_KEY", "VOICE_SWAP_API_KEY_SECRET",
    "VOICE_SWAP_BASE_URL", "VOICE_SWAP_UPSTREAM_HOST", "AWS_PROFILE", "AWS_REGION",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
}


class BridgeError(Exception):
    def __init__(self, status: int, message: str, code: str = "request_failed"):
        super().__init__(message)
        self.status, self.code = status, code


def load_local_env(path: Path):
    """Read explicit local settings without executing shell code."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key in ENV_KEYS and key not in os.environ and value:
            if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if value:
                os.environ[key] = value


def safe_id(value: str, label: str) -> str:
    if not ID_RE.fullmatch(value):
        raise BridgeError(400, f"Invalid {label}.", "invalid_id")
    return value


def validate_wav(data: bytes) -> dict:
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            channels, width, rate, frames = (
                audio.getnchannels(), audio.getsampwidth(),
                audio.getframerate(), audio.getnframes(),
            )
            if audio.getcomptype() != "NONE" or channels != 1 or width != 2:
                raise BridgeError(400, "Use mono 16-bit PCM WAV audio.", "invalid_audio")
            if rate not in (44100, 48000):
                raise BridgeError(400, "Use a 44.1 or 48 kHz recording.", "invalid_audio")
            pcm = audio.readframes(frames)
            if len(pcm) != frames * width:
                raise BridgeError(400, "The recording is incomplete.", "invalid_audio")
            duration = frames / rate
            if duration < 30 or duration > 31:
                raise BridgeError(400, "Record a complete 30-second take before submitting.", "invalid_duration")
            # Reject digital silence independently of frontend capture checks.
            if not any(pcm):
                raise BridgeError(400, "The recording contains no microphone audio.", "silent_audio")
            return {"duration_seconds": duration, "sample_rate": rate,
                    "channels": channels, "bits_per_sample": width * 8}
    except (wave.Error, EOFError, ValueError) as error:
        raise BridgeError(400, "The recording is not a valid PCM WAV file.", "invalid_audio") from error


class Bridge:
    def __init__(self, runtime: Path | None = None):
        self.runtime = runtime or ROOT / ".runtime"
        self.runtime.mkdir(exist_ok=True, parents=True, mode=0o700)
        self.state_path = self.runtime / "jobs.json"
        self.lock = threading.RLock()
        self.state = {"jobs": {}, "submissions": {}}
        if self.state_path.exists():
            try:
                saved = json.loads(self.state_path.read_text())
                if isinstance(saved.get("jobs"), dict) and isinstance(saved.get("submissions"), dict):
                    self.state = saved
            except (ValueError, OSError):
                raise RuntimeError("Local job history cannot be read; preserve .runtime/jobs.json before recovery.")
        self.base = os.environ.get("VOICE_SWAP_BASE_URL", "http://voice-swap-dev.develop.internal").rstrip("/")
        endpoint = urlsplit(self.base)
        if endpoint.scheme not in ("http", "https") or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
            raise RuntimeError("VOICE_SWAP_BASE_URL must be a plain HTTP(S) service URL.")
        self.api_key = os.environ.get("VOICE_SWAP_API_KEY") or os.environ.get("VOICE_SWAP_SERVICE_API_KEY", "")
        self.api_key_secret = os.environ.get("VOICE_SWAP_API_KEY_SECRET", "voice-swap-dev/api-key")
        self.upstream_host = os.environ.get("VOICE_SWAP_UPSTREAM_HOST", "voice-swap-dev.develop.internal")
        if not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]{1,5})?", self.upstream_host):
            raise RuntimeError("VOICE_SWAP_UPSTREAM_HOST must be a hostname.")
        self.authentication_verified = False
        self._aws_session = None
        self._s3 = None

    def save(self):
        temporary = self.state_path.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(self.state, stream, indent=2)
        os.replace(temporary, self.state_path)

    def aws_session(self):
        if self._aws_session is None:
            try:
                import boto3
            except ImportError as error:
                raise BridgeError(503, "AWS support is not installed. Start with ./run.sh.", "aws_dependency_missing") from error
            # A local bridge must not wait for EC2 instance metadata credentials.
            os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
            session = boto3.Session(region_name=REGION)
            credentials = session.get_credentials()
            if credentials is None:
                raise BridgeError(503, "Sign in to your HOOK AWS profile or provide local AWS credentials.", "aws_credentials_missing")
            credentials.get_frozen_credentials()
            self._aws_session = session
        return self._aws_session

    def s3(self):
        if self._s3 is None:
            from botocore.config import Config
            self._s3 = self.aws_session().client("s3", config=Config(connect_timeout=5, read_timeout=30,
                                                                    retries={"max_attempts": 1}))
        return self._s3

    def resolve_api_key(self):
        if self.api_key:
            return self.api_key
        try:
            from botocore.config import Config
            secrets = self.aws_session().client("secretsmanager", config=Config(connect_timeout=3,
                read_timeout=5, retries={"max_attempts": 0}))
            value = secrets.get_secret_value(SecretId=self.api_key_secret).get("SecretString")
            if not isinstance(value, str) or not value.strip():
                raise ValueError("The configured secret is empty")
            self.api_key = value.strip()
            return self.api_key
        except Exception as error:
            raise BridgeError(503, "HOOK AWS access must allow reading the Voice Swap API-key secret.", "api_key_unavailable") from error

    def health(self):
        try:
            for path, expected in (("/health", "ok"), ("/ready", "ready")):
                request = Request(self.base + path, headers={"Accept": "application/json", "Host": self.upstream_host})
                with urlopen(request, timeout=3) as response:
                    if json.loads(response.read(4096)).get("status") != expected:
                        return False
            return True
        except (OSError, ValueError, AttributeError):
            return False

    def status(self):
        blockers = []
        aws_ready = False
        try:
            self.s3()
            aws_ready = True
        except Exception as error:
            blockers.append(str(error) if isinstance(error, BridgeError) else "HOOK AWS credentials are unavailable or expired.")
        if not self.api_key:
            if aws_ready:
                try:
                    self.resolve_api_key()
                except BridgeError as error:
                    blockers.append(str(error))
            else:
                blockers.append("The Voice Swap API key will be read from HOOK AWS after sign-in.")
        reachable = self.health()
        if not reachable:
            blockers.append("Voice Swap is not reachable or ready. Connect to the HOOK private network and check the service.")
        with self.lock:
            jobs = [self.public_job(job) for job in self.state["jobs"].values()]
        return {"configured": bool(self.api_key and aws_ready),
                "ready": bool(self.api_key and aws_ready and reachable),
                "blockers": blockers, "service": "HOOK Voice Swap",
                "service_reachable": reachable, "aws_configured": aws_ready,
                "authentication_verified": self.authentication_verified,
                "jobs": sorted(jobs, key=lambda item: item.get("created_at", 0), reverse=True)[:20]}

    def upstream(self, method: str, path: str, data=None, content_type="application/json"):
        self.resolve_api_key()
        encoded = json.dumps(data).encode() if isinstance(data, dict) else data
        request = Request(self.base + path, data=encoded, method=method,
                          headers={"X-Api-Key": self.api_key, "Accept": "application/json",
                                   "Content-Type": content_type, "Host": self.upstream_host})
        try:
            with urlopen(request, timeout=45) as response:
                content = response.read(2_000_001)
                if len(content) > 2_000_000:
                    raise BridgeError(502, "Voice Swap returned an unexpectedly large response.", "upstream_invalid_response")
                value = json.loads(content)
                if not isinstance(value, dict):
                    raise ValueError("Expected an object")
                self.authentication_verified = True
                return value
        except HTTPError as error:
            # Never reflect upstream request headers, secrets, or stack traces.
            if error.code in (401, 403):
                raise BridgeError(502, "Voice Swap rejected the configured API credentials.", "upstream_auth_failed") from error
            if error.code == 404:
                raise BridgeError(404, "Voice Swap could not find that job or model.", "upstream_not_found") from error
            raise BridgeError(502, f"Voice Swap returned HTTP {error.code}. Your local recording is still available.", "upstream_rejected") from error
        except (URLError, TimeoutError, OSError) as error:
            raise BridgeError(503, "Voice Swap could not be reached. Check the HOOK private network connection.", "upstream_unavailable") from error
        except (ValueError, UnicodeError) as error:
            raise BridgeError(502, "Voice Swap returned an invalid response.", "upstream_invalid_response") from error

    @staticmethod
    def public_job(job):
        return {key: value for key, value in job.items() if key not in ("audio_sha256", "source_key")}

    def record_job(self, response, kind, **metadata):
        job_id = response.get("job_id")
        if not isinstance(job_id, str) or not ID_RE.fullmatch(job_id):
            raise BridgeError(502, "Voice Swap did not return a valid job ID. Do not resubmit until the service is checked.", "submission_unknown")
        job = {"job_id": job_id, "kind": kind, "status": response.get("status", "queued"),
               "created_at": time.time(), **metadata}
        self.state["jobs"][job_id] = job
        self.save()
        return self.public_job(job)

    def train(self, data, training_id=None, model_name=None, capture_metadata=None):
        audio = validate_wav(data)
        training_id = safe_id(training_id or f"stardust_{uuid.uuid4().hex}", "training set ID")
        model_name = model_name or f"Stardust {time.strftime('%Y-%m-%d %H-%M')}"
        if not MODEL_NAME_RE.fullmatch(model_name) or not model_name.strip():
            raise BridgeError(400, "Use letters, numbers, spaces, underscores or hyphens for the model name (1–128 characters).", "invalid_model_name")
        digest = hashlib.sha256(data).hexdigest()
        with self.lock:
            previous = self.state["submissions"].get(training_id)
            if previous:
                if previous.get("audio_sha256") != digest:
                    raise BridgeError(409, "This training set ID belongs to another recording.", "duplicate_training_id")
                if previous.get("job_id"):
                    return self.public_job(self.state["jobs"][previous["job_id"]])
                if previous.get("status") == "submission_unknown":
                    raise BridgeError(409, "This recording may already have been submitted. Check the service before trying again.", "submission_unknown")
            self.resolve_api_key()
            client = self.s3()
            key = f"{INPUT_PREFIX}{training_id}/stardust-30-seconds.wav"
            try:
                client.put_object(Bucket=BUCKET, Key=key, Body=data, ContentType="audio/wav")
            except Exception as error:
                raise BridgeError(502, "The recording could not be uploaded to HOOK storage. Check AWS access.", "upload_failed") from error
            submission = {"audio_sha256": digest, "status": "submission_unknown", "source_key": key}
            self.state["submissions"][training_id] = submission
            self.save()
            # Persist uncertainty before sending; network timeouts must not silently
            # cause duplicate, potentially billable training when the page retries.
            try:
                response = self.upstream("POST", "/api/training", {
                    "training_set_id": training_id, "model_name": model_name,
                    "epochs": 400, "f0_method": "harvest",
                })
            except BridgeError as error:
                if error.code in ("upstream_auth_failed", "upstream_rejected", "upstream_not_found"):
                    submission["status"] = "rejected"
                    self.save()
                raise
            job = self.record_job(response, "training", training_set_id=training_id,
                                  model_name=model_name, audio=audio, capture_metadata=capture_metadata or {})
            submission.update({"job_id": job["job_id"], "status": "submitted"})
            self.save()
            return job

    def get_job(self, job_id):
        safe_id(job_id, "job ID")
        with self.lock:
            job = self.state["jobs"].get(job_id)
            if not job:
                raise BridgeError(404, "This job is not in this computer's Stardust history.", "job_not_found")
            if job.get("status") not in TERMINAL:
                response = self.upstream("GET", f"/api/jobs/{job_id}")
                status = response.get("status")
                if not isinstance(status, str):
                    raise BridgeError(502, "Voice Swap returned no job status.", "upstream_invalid_response")
                job["status"] = status
                job["updated_at"] = time.time()
                if isinstance(response.get("result"), dict):
                    job["result"] = response["result"]
                if isinstance(response.get("summary"), dict):
                    job["progress"] = {key: response["summary"][key]
                                       for key in ("stage", "percent_complete") if key in response["summary"]}
                if status == "failed":
                    job["error"] = "Voice Swap could not complete this job. Your source recording remains available locally."
                self.save()
            return self.public_job(job)

    def transform(self, data, model_id, filename, content_type):
        safe_id(model_id, "model ID")
        filename = Path(unquote(filename)).name
        if not re.fullmatch(r"[A-Za-z0-9_. -]{1,160}", filename) or Path(filename).suffix.lower() not in {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg"}:
            raise BridgeError(400, "Choose a WAV, MP3, FLAC, M4A, AAC or OGG audio file.", "invalid_audio")
        if not content_type.startswith("audio/"):
            raise BridgeError(400, "The source file must be audio.", "invalid_audio")
        if not data or len(data) >= MAX_TRANSFORM_BYTES:
            raise BridgeError(413, "Choose an audio file smaller than 50 MB.", "file_too_large")
        with self.lock:
            # Restrict this UI to real successful models returned to this session.
            known = any(j.get("status") == "succeeded" and j.get("result", {}).get("model_id") == model_id
                        for j in self.state["jobs"].values() if j.get("kind") == "training")
            if not known:
                raise BridgeError(409, "Wait for your Stardust voice model to finish training first.", "model_not_ready")
            boundary = "stardust" + uuid.uuid4().hex
            chunks = []
            for name, value in (("model_id", model_id), ("transpose", "0"), ("auto_transpose", "false")):
                chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
            chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'.encode())
            chunks += [data, f"\r\n--{boundary}--\r\n".encode()]
            response = self.upstream("POST", "/api/transformations", b"".join(chunks), f"multipart/form-data; boundary={boundary}")
            return self.record_job(response, "transformation", model_id=model_id, filename=filename)

    def result(self, job_id):
        job = self.get_job(job_id)
        if job.get("kind") != "transformation" or job.get("status") != "succeeded":
            raise BridgeError(409, "The transformed audio is not ready yet.", "result_not_ready")
        result = job.get("result", {})
        # Accept only explicit locations in a documented result, never construct
        # a guessed output filename or fetch arbitrary URLs supplied by a result.
        candidates = [result.get(k) for k in ("output_s3_uri", "s3_uri", "output_path", "output_url", "output_key", "s3_key")]
        prefix = f'{OUTPUT_PREFIX}{job["model_id"]}/'
        key = None
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            if candidate.startswith(f"s3://{BUCKET}/"):
                candidate = candidate[len(f"s3://{BUCKET}/"):]
            if candidate.startswith(prefix) and ".." not in candidate.split("/"):
                key = candidate
                break
        if not key:
            raise BridgeError(409, "Voice Swap finished but did not provide a supported output location.", "result_location_unavailable")
        try:
            result = self.s3().get_object(Bucket=BUCKET, Key=key)
            return result, Path(key).name
        except Exception as error:
            raise BridgeError(502, "The completed audio could not be read from HOOK storage.", "result_download_failed") from error


class Handler(BaseHTTPRequestHandler):
    server_version = "StardustLocal/1.0"

    @property
    def bridge(self):
        return self.server.bridge

    def log_message(self, format, *args):
        # Requests may contain private IDs. Keep the local log to status only.
        print(f"Stardust HTTP {args[1] if len(args) > 1 else 'request'}", flush=True)

    def headers_for(self, content_type, length):
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")

    def json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.headers_for("application/json; charset=utf-8", len(body))
        self.end_headers()
        self.wfile.write(body)

    def check_origin(self, mutation=False):
        host = self.headers.get("Host", "")
        port = self.server.server_address[1]
        if host not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            raise BridgeError(403, "Use the local Stardust address.", "invalid_host")
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
            raise BridgeError(403, "Open Stardust on this computer to continue.", "invalid_origin")
        if mutation and self.headers.get("X-Stardust-Client") != "1":
            raise BridgeError(403, "Submit audio from the Stardust app.", "invalid_client")

    def read_body(self, limit):
        if self.headers.get("Transfer-Encoding"):
            raise BridgeError(400, "Send audio with a known file length.", "invalid_body")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise BridgeError(400, "Invalid file length.", "invalid_body") from error
        if length <= 0 or length > limit:
            raise BridgeError(413, "The audio file is empty or too large.", "file_too_large")
        self.connection.settimeout(30)
        body = self.rfile.read(length)
        if len(body) != length:
            raise BridgeError(400, "The upload was interrupted.", "invalid_body")
        return body

    def do_GET(self):
        try:
            self.check_origin()
            path = urlsplit(self.path).path
            if path == "/api/status":
                return self.json(200, self.bridge.status())
            if path.startswith("/api/jobs/"):
                return self.json(200, self.bridge.get_job(path.removeprefix("/api/jobs/")))
            if path.startswith("/api/results/"):
                result, filename = self.bridge.result(path.removeprefix("/api/results/"))
                self.send_response(200)
                self.headers_for(result.get("ContentType", "audio/wav"), result["ContentLength"])
                safe_filename = re.sub(r"[^A-Za-z0-9_. -]", "_", filename)
                self.send_header("Content-Disposition", f'inline; filename="{safe_filename}"')
                self.end_headers()
                try:
                    for chunk in result["Body"].iter_chunks(chunk_size=64 * 1024):
                        if chunk:
                            self.wfile.write(chunk)
                finally:
                    result["Body"].close()
                return
            # Standalone build embeds its assets. No directory serving, source,
            # old commercial stems, recordings, environment, or runtime files.
            if path not in ("/", "/index.html", "/HOOK-Stardust.html"):
                raise BridgeError(404, "Not found.", "not_found")
            file = ROOT / ("HOOK-Stardust.html" if path.endswith("HOOK-Stardust.html") else "index.html")
            body = file.read_bytes()
            self.send_response(200)
            self.headers_for("text/html; charset=utf-8", len(body))
            self.end_headers()
            self.wfile.write(body)
        except BridgeError as error:
            self.json(error.status, {"error": str(error), "code": error.code})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.json(500, {"error": "The local bridge encountered an error.", "code": "internal_error"})

    def do_POST(self):
        try:
            self.check_origin(mutation=True)
            path = urlsplit(self.path).path
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
            if path == "/api/training":
                if content_type not in ("audio/wav", "audio/wave", "audio/x-wav"):
                    raise BridgeError(415, "Submit a WAV recording.", "invalid_content_type")
                metadata = {}
                if self.headers.get("X-Capture-Metadata"):
                    raw = unquote(self.headers["X-Capture-Metadata"])
                    if len(raw) > 8000:
                        raise BridgeError(400, "Recording metadata is too large.", "invalid_metadata")
                    try:
                        metadata = json.loads(raw)
                    except ValueError as error:
                        raise BridgeError(400, "Invalid recording metadata.", "invalid_metadata") from error
                    if not isinstance(metadata, dict):
                        raise BridgeError(400, "Invalid recording metadata.", "invalid_metadata")
                job = self.bridge.train(self.read_body(MAX_TRAINING_BYTES),
                                        self.headers.get("X-Training-Set-Id"),
                                        self.headers.get("X-Model-Name"), metadata)
                return self.json(202, job)
            if path == "/api/transformations":
                job = self.bridge.transform(self.read_body(MAX_TRANSFORM_BYTES - 1),
                                            self.headers.get("X-Model-Id", ""),
                                            self.headers.get("X-Filename", "source.wav"), content_type)
                return self.json(202, job)
            raise BridgeError(404, "Not found.", "not_found")
        except BridgeError as error:
            self.json(error.status, {"error": str(error), "code": error.code})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.json(500, {"error": "The local bridge encountered an error.", "code": "internal_error"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    load_local_env(ROOT / ".env.local")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.bridge = Bridge()
    print(f"Stardust: http://127.0.0.1:{args.port}", flush=True)
    print("Voice recordings are sent only when you choose to create your voice.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
