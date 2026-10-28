# Local Voice Swap service bridge

The Stardust game sends audio to the real HOOK Voice Swap development service
through a local Python bridge. The browser never receives API keys or AWS
credentials. The bridge serves only the built HTML entry points; it does not
serve source files, old commercial stems, local settings, or job history.

## Start

From `games/stardust`, run:

```sh
./run.sh
```

Open `http://127.0.0.1:8765/`. The script creates `.venv`, installs boto3 if it is
missing, rebuilds the standalone games, and binds only to `127.0.0.1`. Select a
different port with `./run.sh --port 8766`.

Python 3.9 and the locally installed boto3 dependency were verified on this Mac.
Game capture works before the external service is configured; training requires
the three connections below.

## Configure

1. Copy `.env.example` to `.env.local`.
2. Use an existing HOOK AWS profile with `AWS_PROFILE`, or provide standard AWS
   credentials to the server process. For SSO profiles, sign in through the
   organisation's AWS tooling first. The bridge uses the normal boto3 credential
   chain. Do not reuse credentials from an unrelated AWS account. The server
   automatically reads `voice-swap-dev/api-key` from AWS Secrets Manager in
   `us-east-2`; the profile therefore needs `secretsmanager:GetSecretValue` for
   this secret. `VOICE_SWAP_API_KEY` is an optional server-only override. The
   separate Voice-Swap bootstrap token belongs to the upstream service and is
   not needed by this bridge.
3. Connect to the HOOK network or approved tunnel that resolves and reaches
   `voice-swap-dev.develop.internal` on port 80. If an approved tunnel supplies a
   different local service address, set `VOICE_SWAP_BASE_URL` accordingly. The
   bridge preserves `Host: voice-swap-dev.develop.internal` for the internal
   load balancer; `VOICE_SWAP_UPSTREAM_HOST` can override that hostname if the
   approved access configuration explicitly requires it.
4. Restart the local server after changing credentials or settings.

Required S3 access is scoped to bucket `hookmlbucket` in `us-east-2`:

- Upload: `voice_swap/inputs/raw_vocals_for_training/{training_set_id}/`.
- Read transformed audio: `voice_swap/outputs/{model_id}/`.

`.env.local`, `.venv`, and `.runtime` are ignored by Git. Keep secrets in the
server process or `.env.local`; never put them into `source/app.html`, generated
HTML, the browser console, or a committed settings file. `.env.local` is parsed
as values and is never executed as a shell script.

`GET /api/status` reports configuration and service readiness. Its `ready`
field means that credentials are available and the service's real `/health`
and `/ready` endpoints respond successfully. Those endpoints do not validate
the caller's API key, so readiness is not proof that the key or S3 write
permissions have been accepted. `authentication_verified` becomes true only
after an authenticated upstream API operation succeeds. Status may read the
verified API-key secret; it never trains a model or uploads audio.

## Browser contract

All requests use the page's origin. Mutating requests require
`X-Stardust-Client: 1`; requests with another browser origin are rejected. The
server has no cross-origin allowance.

| Request | Input | Response |
| --- | --- | --- |
| `GET /api/status` | None | Configuration, blockers, reachability, and saved jobs |
| `POST /api/training` | Raw `audio/wav`; optional headers below | HTTP 202 with real `job_id`, status and capture metadata |
| `GET /api/jobs/{job_id}` | Job created through this local bridge | Current upstream status, result, `progress.stage`, `progress.percent_complete`, and saved metadata |
| `POST /api/transformations` | Raw audio, `X-Model-Id`, URI-encoded `X-Filename` | HTTP 202 with real transformation `job_id` |
| `GET /api/results/{job_id}` | Completed transformation job | Streams the result from its allowed S3 location |

Training headers:

- `X-Training-Set-Id`: keep this ID stable while retrying the same recording;
  letters, numbers, underscores and hyphens, 1–64 characters, starting with a
  letter or number. A new recording must use a new ID.
- `X-Model-Name`: letters, numbers, spaces, underscores and hyphens, 1–128
  characters. A default name is generated when omitted.
- `X-Capture-Metadata`: optional URI-encoded JSON object, at most 8 KB decoded.

Training audio must be complete, non-silent, mono 16-bit PCM WAV at 44.1 or 48
kHz, at least 30 and at most 31 seconds. The game exports exactly 30 seconds; the
small server tolerance supports rounding without accepting shorter source
audio. The request limit is 12,000,000 bytes.

The bridge writes `stardust-30-seconds.wav` to the training-set S3 folder and then
submits:

```json
{
  "training_set_id": "the_stable_capture_id",
  "model_name": "The chosen voice name",
  "epochs": 400,
  "f0_method": "harvest"
}
```

Training uses `POST /api/training` on the documented private service, with
server-only `X-Api-Key` authentication. Polling uses `GET /api/jobs/{job_id}`.
Training is queued and can take a substantial time; there is no simulated timer
or fabricated model ID. Success reads the real `result.model_id`.

Transformation accepts a WAV, MP3, FLAC, M4A, AAC or OGG file smaller than
50,000,000 bytes, with an audio content type. If the browser omits its MIME type,
the frontend supplies an audio MIME type based on its extension. The bridge
requires a model returned by a successful local training job, and sends upstream
multipart form data with `model_id`, one `file`, `transpose=0`, and
`auto_transpose=false`. It does not submit an ISRC alongside a file.

Result downloads accept an explicit S3 URI/key from the service's result only
when it is inside `hookmlbucket/voice_swap/outputs/{that_model_id}/`. Supported
result field names are `output_s3_uri`, `s3_uri`, `output_path`, `output_url`,
`output_key`, and `s3_key`. A response without a supported location is reported
as unavailable rather than guessing an output filename or fetching an arbitrary
URL.

## Recovery

Job IDs and capture metadata are saved in `.runtime/jobs.json` with private file
permissions. Raw recordings are not persisted by the server. The frontend
keeps the current recording available to download.

Repeating the same recording and training-set ID returns its existing job.
Reusing an ID for different audio is rejected. If the upstream connection fails
after upload, the bridge conservatively records that submission as uncertain:
do not generate a fresh ID and retry blindly, because the service may already
have queued training. Check the service first. A definite service rejection
allows retry with the same recording and ID after its cause is fixed.

## Verification and current connection state

Verified on 24 October 2026:

- 12 passing tests cover WAV validation, exact documented upload/training
  payload, repeated/uncertain submission handling, persistent job recovery,
  real model IDs, transformation multipart data, S3 output restrictions, and
  localhost request/static-file protections, and server-only Secrets Manager
  retrieval without returning key values to the browser or job history.
- The running HTML and `/api/status` both returned HTTP 200.
- The local environment had no HOOK Voice Swap API key and no available HOOK
  AWS profile or environment credentials.
- `voice-swap-dev.develop.internal` did not resolve, including in a network
  check outside the execution sandbox.
- Current private GitHub source was accessible through the existing local
  GitHub login. It confirms the key's Secrets Manager location, health routes,
  result schema, and private internal load-balancer routing. GitHub access
  itself does not provide AWS credentials.
- The current `hook-toolbox` README documents SSH access through
  `ec2-user@jump.develop.hookmusic.com`, requiring
  `~/.aws/pems/dev-db-access.pem`. That private key and AWS configuration are
  absent on this Mac. The documented helper tunnels are for the database;
  a service-specific approved tunnel still needs HOOK's access configuration.

The tests use local stubs. No source audio was uploaded to AWS, no real model was
trained, and no external paid operation was invoked during implementation.
End-to-end service testing remains dependent on the key, AWS access, and private
network connection above.

Run the tests from `games/stardust`:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v
```

Contract sources:

- HOOK-provided document:
  `https://docs.google.com/document/d/1Xs_GoNDm83UzezFsqODOVjbTlWFNlN5R/edit`.
- Current private service source:
  `https://github.com/hookworldtech/music-services/tree/b6f6b2d973507ba4f2153b8b3a01917808f254ad/voice_swap_service`.
- Private routing:
  `https://github.com/hookworldtech/api-infra/blob/main/terraform-api/develop/voice-swap-dev.tf`.
- Existing access tools:
  `https://github.com/hookworldtech/hook-toolbox/blob/main/README.md`.
