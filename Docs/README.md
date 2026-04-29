# SpeakSecure

**Privacy-first, open-source voice authentication API with OAuth 2.0 support.**

SpeakSecure replaces passwords with your voice. It combines speaker verification (ECAPA-TDNN), one-time spoken digit codes (Whisper), voice activity detection (Silero VAD), and anti-spoofing detection (AASIST) behind a single REST API. Third-party sites can integrate it via the standard OAuth 2.0 authorization code flow — no proprietary SDK, no client libraries, just HTTP redirects and JSON.

All voice data stays on the device that runs the server. Embeddings are 192-dimensional vectors stored locally; raw audio is deleted immediately after processing.

---

## Features

- **Voice enrolment** — register a user with 3–10 seconds of voice
- **Voice verification** — sign in via a freshly generated 5-digit spoken challenge plus voice match
- **Anti-spoofing** — AASIST model detects TTS, deepfakes and replay attacks
- **Voice Activity Detection** — Silero VAD rejects silence, noise, and hallucinated transcriptions
- **Per-user lockout rate limiting** — configurable threshold of failed attempts before temporary lockout
- **OAuth 2.0 identity provider** — authorization code flow with state, exact redirect_uri match, server-to-server token exchange
- **API key system** — hashed keys with per-key origin policies, redirect-URI whitelists, and hourly request budgets
- **Two frontends served from the same backend:**
  - `Demo/` — self-service web app for SpeakSecure users (register, sign in, manage profile)
  - `OAuthFrontend/` — single-purpose `/authorize` page used by third-party integrators
- **66 unit tests** covering rate limiting, OAuth code generation, audio processing, challenge generation, and the full enrolment/verification pipelines

---

## Tech Stack

| Component | Purpose |
|---|---|
| FastAPI | REST API framework, async ML pipeline, dependency injection |
| ECAPA-TDNN (SpeechBrain) | 192-dim voice embeddings for speaker verification |
| faster-whisper (small) | Speech-to-text for challenge-digit recognition |
| AASIST | Anti-spoofing (detects TTS, deepfakes, replays) |
| Silero VAD | Voice Activity Detection to reject non-speech audio |
| torchaudio, PyTorch | Audio processing and model inference |
| ffmpeg | Audio format conversion (WAV, MP3, M4A, FLAC, OGG) |
| SQLite | API keys, OAuth authorization codes, per-key usage counters |
| Vanilla HTML / CSS / JS | Web frontends (no framework, instant load) |

---

## Architecture

The project follows a layered architecture to keep the API, business logic, storage, and ML code cleanly separated. All long-running ML calls are wrapped in `asyncio.to_thread` so concurrent requests don't block each other.

```
SpeakSecureFinal/
├── main.py                    # FastAPI app: lifespan, CORS, routes, static mounts
├── run.py                     # Local launcher (python run.py)
├── config.py                  # Device selection (CUDA/CPU), model settings, paths re-export
├── config_paths.py            # Torch-free path module (allows tests to run without ML deps)
├── constants.py               # Tunable thresholds, lockout policy, OAuth code TTL
├── requirements.txt
├── requirements-direct.txt    # Direct dependencies only (documentation)
├── pytest.ini
├── .gitignore
│
├── API/
│   ├── dependencies.py        # require_api_key dependency (origin + rate-limit check)
│   ├── router.py              # Aggregates all routers under /api/v1
│   └── Routes/
│       ├── health.py          # GET  /health
│       ├── status.py          # GET  /status
│       ├── challenge.py       # POST /challenge
│       ├── enrolment.py       # POST /enrol, /enrol/add-sample, GET /enrol/check, DELETE /enrol/{id}
│       ├── verification.py    # POST /verify
│       ├── authorize.py       # GET  /authorize (page), /oauth/client-info, POST /authorize/challenge, /authorize/submit-signin
│       └── token.py           # POST /token (server-to-server code exchange)
│
├── Services/                  # Business logic orchestrators
│   ├── dependencies.py        # Shared service singletons (dependency injection)
│   ├── audio_service.py
│   ├── challenge_service.py
│   ├── embedding_service.py
│   ├── enrolment_service.py
│   ├── speech_service.py
│   ├── spoofing_service.py
│   ├── verification_service.py
│   └── oauth_service.py       # Authorization code generation and exchange
│
├── Core/                      # ML wrappers and audio processing
│   ├── audio_processor.py     # Load, resample, normalise audio
│   ├── audio_validator.py     # Duration, speech-ratio, energy checks
│   ├── voice_encoder.py       # ECAPA-TDNN wrapper
│   ├── speech_recognizer.py   # Whisper wrapper
│   ├── anti_spoof.py          # AASIST wrapper
│   ├── vad.py                 # Silero VAD wrapper
│   └── AASIST/                # AASIST model code + AASIST.pth weights
│
├── Storage/
│   ├── database.py            # SQLite schema (3 tables) and connection helpers
│   ├── voiceprint_repository.py     # Per-user embedding storage on disk
│   ├── api_key_repository.py        # API key CRUD + lookup by hash
│   ├── authorization_code_repository.py  # OAuth code CRUD with atomic exchange
│   └── usage_repository.py    # Per-key per-hour request counters
│
├── Security/
│   ├── api_keys.py            # Key hashing (SHA-256) and validation
│   └── rate_limiter.py        # Per-user lockout + per-API-key rate limiter
│
├── Models/
│   └── schemas.py             # Pydantic request/response models
│
├── Utils/
│   ├── logger.py              # Structured logging via loguru
│   ├── cleanup.py             # Background sweeps: stale temp files, expired codes, old usage rows
│   └── model_loader.py        # Eager model loading on startup with retry
│
├── Tests/                     # 66 unit tests
│   ├── test_audio_processor.py
│   ├── test_challenge_service.py
│   ├── test_enrolment.py
│   ├── test_verification.py
│   ├── test_rate_limiter.py
│   └── test_oauth_service.py
│
├── Scripts/
│   └── create_api_key.py      # CLI for issuing new API keys
│
├── Demo/                      # Self-service web app (served at /)
│   ├── index.html
│   ├── style.css
│   └── Js/
│       ├── config.js          # API_BASE, API_KEY, global state
│       ├── helpers.js
│       ├── auth.js
│       ├── navigation.js
│       ├── recording.js       # Mic capture + WAV encoding
│       └── api.js             # HTTP calls to the backend
│
├── OAuthFrontend/             # Third-party-facing /authorize page
│   ├── authorize.html
│   ├── authorize.css
│   └── authorize.js
│
├── AcmeShopDemo/              # Standalone demo integrator (deployed separately)
│   ├── app.py                 # FastAPI server simulating a third-party shop
│   ├── config.py              # Reads SPEAKSECURE_BASE_URL, SPEAKSECURE_API_KEY from env
│   ├── requirements.txt
│   └── Templates/             # Jinja2 templates
│
├── Docs/
│   ├── README.md              # This file
│   ├── API.md                 # Full endpoint reference
│   └── ARCHITECTURE.md        # Layered architecture, OAuth flow, security model
│
└── Data/                      # Gitignored, created at runtime
    ├── Embeddings/            # Stored voice profiles (per user)
    ├── Temp_Audio/            # Temporary uploaded audio (auto-cleaned)
    ├── Logs/
    └── speaksecure.db         # SQLite (api_keys, authorization_codes, api_key_usage)
```

See `Docs/ARCHITECTURE.md` for a deep dive into the layered design and OAuth flow, and `Docs/API.md` for the full endpoint reference.

---

## Installation

### Prerequisites

- Python 3.11
- [ffmpeg](https://ffmpeg.org/download.html) installed and on PATH
- ~2 GB free disk space for ML model weights
- A working microphone

### Setup

```
# 1. Clone the repo
git clone https://github.com/<your-username>/SpeakSecureFinal.git
cd SpeakSecureFinal

# 2. Create and activate a virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

On first run, the server will download the required model weights:
- ECAPA-TDNN (~17 MB)
- Whisper small (~470 MB)
- Silero VAD (~2 MB)

AASIST weights ship with the repo at `Core/AASIST/AASIST.pth` (~1.3 MB).

---

## Running

### Start the server

```
python run.py
```

The server listens on `http://localhost:8000` by default.

| URL | What it shows |
|---|---|
| `http://localhost:8000/` | Self-service Demo web app |
| `http://localhost:8000/docs` | Interactive Swagger API docs |
| `http://localhost:8000/api/v1/health` | Health check |
| `http://localhost:8000/api/v1/status` | Loaded models and configuration |
| `http://localhost:8000/api/v1/authorize?...` | OAuth sign-in page (used by integrators) |

### Issue an API key

The Demo and any third-party integrator both need an API key. Issue one with the CLI:

```
python Scripts/create_api_key.py \
    --name "Demo" \
    --origins "http://localhost:8000,http://127.0.0.1:8000" \
    --redirect-uris "" \
    --rate-limit 1000
```

The script prints the plaintext key once — copy it into `Demo/Js/config.js` (`API_KEY` constant). Only the SHA-256 hash is stored in `Data/speaksecure.db`; the plaintext is unrecoverable.

For a third-party integrator (Acme Shop):

```
python Scripts/create_api_key.py \
    --name "Acme Shop" \
    --origins "https://acme.example.com" \
    --redirect-uris "https://acme.example.com/callback" \
    --rate-limit 5000
```

### Typical user flow via the Demo

1. Open `http://localhost:8000/`
2. Click **Register**, choose a username, record 3–10 seconds of your voice
3. Click **Sign in**, type the username, press **Get my code**
4. Speak the displayed digits clearly
5. Press **Sign me in** — if the voice matches and the digits are correct, you're in

### Typical OAuth flow (third-party integrator)

1. Acme Shop redirects the user to `https://speak-secure.example.com/api/v1/authorize?client_id=<key_prefix>&redirect_uri=<acme_callback>&state=<csrf_token>`
2. SpeakSecure shows the OAuth sign-in page; the user enters their SpeakSecure username and verifies their voice
3. SpeakSecure redirects back to Acme: `<acme_callback>?code=<short_lived_code>&state=<csrf_token>`
4. Acme's backend exchanges the code via `POST /api/v1/token` (authenticated with their API key) and receives `{"verified": true, "user_id": "..."}`
5. Acme creates its own session for the user

---

## API Endpoints

All routes are prefixed with `/api/v1`. See `Docs/API.md` for full request/response schemas with examples.

### Public (require API key)

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe |
| `GET` | `/status` | Loaded models and configuration |
| `POST` | `/enrol` | Register a new user (first voice sample) |
| `POST` | `/enrol/add-sample` | Add an extra voice sample to an existing profile |
| `GET` | `/enrol/check/{user_id}` | Check whether a username is taken |
| `DELETE` | `/enrol/{user_id}` | Delete a user's voice profile |
| `POST` | `/challenge` | Generate a one-time digit code for sign-in |
| `POST` | `/verify` | Verify a user's voice against a challenge |

### OAuth (used by third-party integrators)

| Method | Path | Description |
|---|---|---|
| `GET` | `/authorize` | OAuth sign-in HTML page |
| `GET` | `/oauth/client-info` | Public: returns the integrator's display name (for the OAuth banner) |
| `POST` | `/authorize/challenge` | Generate challenge inside the OAuth flow |
| `POST` | `/authorize/submit-signin` | Verify voice and issue an authorization code |
| `POST` | `/token` | Server-to-server code exchange (returns `{verified, user_id}`) |

---

## Configuration

All tunable parameters live in `constants.py`. The main ones:

| Constant | Default | Purpose |
|---|---|---|
| `SIMILARITY_THRESHOLD` | 0.35 | Minimum cosine similarity to accept a sign-in |
| `BORDERLINE_THRESHOLD` | 0.32 | Below this → rejected, above → retry zone |
| `CHALLENGE_LENGTH` | 5 | Number of digits in each challenge code |
| `CHALLENGE_EXPIRATION_SECONDS` | 60 | How long a challenge is valid |
| `MAX_FAILED_ATTEMPTS` | 5 | Lockout trigger |
| `LOCKOUT_DURATION_SECONDS` | 60 | Lockout length (set to 3600 for 1 hour) |
| `MAX_SAMPLES_PER_USER` | 3 | Enrolment sample cap |
| `SPOOF_CONFIDENCE_THRESHOLD_ENROL` | 0.5 | Strict spoof check at enrolment |
| `SPOOF_CONFIDENCE_THRESHOLD_VERIFY` | 1.0 | Lenient spoof check at sign-in |
| `AUTHORIZATION_CODE_TTL_SECONDS` | 10 | Lifetime of an OAuth authorization code |
| `ENROL_MIN_SPEECH_RATIO` | 0.40 | Minimum speech-vs-silence ratio at enrolment |
| `VERIFY_MIN_SPEECH_RATIO` | 0.30 | Minimum speech-vs-silence ratio at verification |

The two-tier anti-spoofing policy is deliberate: operations that modify the stored voice profile (enrolment and sample addition) use a strict threshold to prevent profile poisoning, while verification uses a lenient threshold because AASIST is over-sensitive to genuine but unusual microphone input.

---

## Testing

```
pytest
```

66 tests across 6 files cover:
- **Rate limiter** (11 tests): lockout thresholds, concurrent failures, time-based expiry, per-user isolation
- **OAuth service** (11 tests): code entropy, uniqueness, TTL propagation, repository binding fields
- **Audio processor** (9 tests): format conversion, sample rate, duration validation
- **Challenge service** (14 tests): code generation, atomic consumption, concurrent access
- **Enrolment** (12 tests): full pipeline with mocked ML, edge cases on duration and spoof detection
- **Verification** (9 tests): full pipeline, similarity scoring, lockout integration

Tests for `rate_limiter` and `oauth_service` are decoupled from torch via `config_paths.py`, so they run in environments without ML dependencies installed.

---

## Security Model

- **API key authentication.** Every endpoint (except `/health` and `/oauth/client-info`) requires `X-API-Key`. Keys are stored as SHA-256 hashes; the plaintext is shown only once at creation. Each key is bound to a list of allowed browser origins and (for OAuth integrators) a list of allowed `redirect_uri` values.
- **Per-key rate limiting.** Each API key has an hourly request budget (default 1000). Counts are tracked atomically in SQLite per `(api_key_id, hour_bucket)`.
- **Per-user lockout.** After `MAX_FAILED_ATTEMPTS` consecutive failed verifications, a user is locked out for `LOCKOUT_DURATION_SECONDS`. Successful verification resets the counter. Lockout state is in-memory only (intentional — it must not persist across restarts in case of an attack).
- **DoS-resistant verification.** Malformed audio (silence, too-short clips, mostly-noise) raises `ValueError` inside the verify pipeline, which is caught and counted as a failed attempt before re-raising. This prevents an attacker from bypassing per-user lockout by spamming malformed audio.
- **Challenge-response.** Every sign-in requires a freshly generated digit code, so a recorded voice sample cannot be replayed.
- **Atomic challenge consumption.** Challenges are verified and marked used inside an `asyncio.Lock` to prevent race conditions where two requests would consume the same code.
- **OAuth authorization codes.** Codes are generated via `secrets.token_urlsafe(32)`, valid for 10 seconds, single-use, and bound to `(user_id, api_key_id, redirect_uri)` at issue time. Exchange is atomic in SQLite (`UPDATE ... WHERE consumed_at IS NULL` checked via `rowcount`).
- **Open redirect protection.** Three layers on the register-redirect flow: URL parse + same-origin check + path whitelist (`/api/v1/authorize` only).
- **Voice identity check on add-sample.** A new sample must match the existing profile, preventing a session hijacker from replacing stored samples with their own.
- **Anti-spoofing on every enrolment and verification.** AASIST rejects TTS, deepfake, and replay input.

---

## Limitations and Future Work

- **Embeddings stored in plain `.pt` files.** A production deployment should encrypt them at rest (e.g. via age, libsodium, or a KMS).
- **AASIST domain shift.** AASIST is trained on ASVspoof 2019 LA and is sensitive to microphone changes. A more robust model or a domain-adaptation fine-tune would reduce false rejections during verification.
- **No batching for `/verify`.** Every request runs inference on a single file. For high-traffic deployments a request batcher would improve GPU utilisation.
- **Lockout state is in-memory.** Restarting the server clears active lockouts. This is deliberate (defence against an attacker repeatedly crashing the process), but means the system cannot be horizontally scaled without a shared lockout store (Redis would be the natural choice).
- **Sample management is intentionally limited to "add" and "delete profile."** Per-sample deletion was rejected because it opens a downgrade attack vector (a session hijacker could replace legitimate samples with their own).

---

## Project Background

This project was developed as a Final Year Project for the BSc Computer Science programme at the University of Westminster (2025/2026). The goal was to explore whether modern open-source speaker verification, speech recognition, and anti-spoofing models could be combined into a practical, privacy-preserving authentication service that runs entirely on the operator's own hardware — and could be integrated into third-party sites via the standard OAuth 2.0 flow rather than a proprietary SDK.

---

## License

MIT License. See `LICENSE` for details.

AASIST, ECAPA-TDNN, Whisper, and Silero VAD are used under their respective licenses — see each upstream project for details.