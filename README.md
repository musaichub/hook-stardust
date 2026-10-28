# HOOK Stardust — 30-second voice capture

Four vocal games collect **one exact 30-second mono WAV** per microphone session. The app now uses newly synthesized guides for five traditional melodies: Twinkle, Twinkle, Little Star; Frère Jacques; Mary Had a Little Lamb; Row, Row, Row Your Boat; and London Bridge. Commercial recordings and separated stems are no longer loaded or embedded.

## Play locally

From this folder, run `./run.sh`, then open **http://127.0.0.1:8765/** in Chrome or Safari. The launcher creates its local Python environment, builds the page and starts the private-service bridge. A file opened directly can play, but service requests require the local server.

1. Pick Rocket Fuel, Moonshot, Echo or Jetpack, and choose three melodies.
2. Select **Play with mic**. Use headphones and a quiet room, with the mic about a hand’s width away.
3. Stay quiet during the brief room check, then sing a comfortable note for the level check.
4. Play the rounds. The guide sounds first; the singing window is quiet. Sing words, “la”, or the prompted vowels in your comfortable octave.
5. Complete extra rounds when needed until **30 seconds are kept**. Quiet, badly clipped or interrupted phrases do not count. Pitch score is separate from recording quality.
6. Review with **Hear my take**, save the WAV, or choose **Create my voice** to upload it to HOOK and start real Voice Swap training.

**Touch mode is practice only** and never records. An Exit game button stops microphone use. A new game starts a new recording; audio is held in browser memory and is lost on reload unless downloaded. Voice Swap job IDs are remembered so **Check my voice job** can resume polling after a reload.

## The games

| Game | Capture changes |
| --- | --- |
| Rocket Fuel | A familiar melody plays once, then a count-in and quiet singing window. Lyrics and pitch planets guide the take. |
| Moonshot | Three comfortable notes, held for 3.8 seconds each, with ah/ee/oo prompts and a quiet interval after each guide. |
| Echo | Increasing 3/5/8-note phrases, heard first and sung back in a separate recording window. Internal pauses and consonants are preserved. |
| Jetpack | Hear each step, then hold the note for 1.4 seconds to jump. Each step has its own recording window; guide and effects stay outside it. |

Recording uses an AudioWorklet on the audio thread, with no speaker monitoring or game-output connection to the recorded signal. Browser echo cancellation, noise suppression and automatic gain are requested off. A room-noise check informs conservative phrase quality checks. Only quiet edges are trimmed; a short edge fade avoids clicks when phrases are joined. No tuning, normalization or denoising is applied to the saved voice. The final sample count is capped at exactly 30 seconds. Headphones remain necessary to avoid acoustic speaker bleed.

## Real Voice Swap integration

The previous animated training simulation has been removed. The local backend follows the [HOOK service document](https://docs.google.com/document/d/1Xs_GoNDm83UzezFsqODOVjbTlWFNlN5R/edit): upload a single WAV of at least 30 seconds to HOOK S3, submit the training-set ID, and poll the returned job ID. A model is shown only when the real service reports success and supplies its model ID. A completed model can be used with a user-supplied dry vocal file through the documented transformation API.

Credentials remain on the server. The app shows unavailable configuration or connection errors and keeps the source recording available for download. Training may queue for a long time. See [docs/SERVICE.md](docs/SERVICE.md) and `.env.example` for local access setup and endpoint details.

As of 24 October 2026, the local app runs, while live service verification requires the HOOK private-network route and HOOK AWS credentials. The backend reads the verified `voice-swap-dev/api-key` secret automatically after AWS sign-in. The current implementation was checked against the private GitHub `voice-swap` branch as well as the supplied service document. See `qa/` for current browser evidence; mocked API tests do not establish live training success.

## Editable source and checks

- `source/app.html`: UI and all four games.
- `source/capture.js`: microphone AudioWorklet, quality checks and sample accounting.
- `source/melodies.py`: melody notes, lyric timing, original artwork and provenance.
- `source/melody-audio.js`: cached synthesized guides, generated in the browser.
- `source/build.py`: embeds the source, fonts, lockups and compact melody data into `index.html` and `HOOK-Stardust.html`.
- `server.py`: local S3/private-service bridge; `run.sh`: launcher.
- `docs/MELODIES.md`: historical composition sources and arrangement scope.
- `source/test_capture.cjs`: quality, sample-accounting and recorder lifecycle tests.
- `source/test_capture_browser.cjs`: real Chromium AudioWorklet test with generated input.
- `source/test_games.cjs`: all four mic flows, WAV download and mocked API job lifecycle.
- `tests/test_server.py`: local HTTP and service-contract tests.

Rebuild with `python3 source/build.py`. Run recorder checks with `node source/test_capture.cjs`; browser tests use an installed Chrome and Playwright (the scripts locate the bundled Codex runtime). Backend checks use `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests`.

The prior app and README are preserved in `archive/2026-10-24-before-public-domain/`. Historical `songs/`, `hook_top5_prod 2/`, `source/analyze.py`, `source/template.html` and the old `source/test.py` are retained as legacy material; the new build and server do not load or expose them. The separate HOOK Arcade project is unchanged.
