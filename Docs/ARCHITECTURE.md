# SpeakSecure — Architecture

This document describes the layered architecture of SpeakSecure, the OAuth 2.0 flow, the security model, and the design decisions behind the major choices. For the API surface, see `API.md`. For setup and running instructions, see `README.md`.

---

## Architectural overview

SpeakSecure follows a **layered architecture** in which each layer has a single, well-defined responsibility and depends only on layers below it:

```
┌─────────────────────────────────────────────────────────────────┐
│  Frontends                                                      │
│  Demo/  (self-service)         OAuthFrontend/  (/authorize)     │
└─────────────────────────────────────────────────────────────────┘
                                 ↓ HTTP
┌─────────────────────────────────────────────────────────────────┐
│  API layer  (FastAPI)                                           │
│  Routes/         Validates HTTP, parses input, calls Services   │
│  dependencies.py require_api_key dependency                     │
└─────────────────────────────────────────────────────────────────┘
                                 ↓
┌─────────────────────────────────────────────────────────────────┐
│  Services layer  (business logic)                               │
│  enrolment_service, verification_service, oauth_service, ...    │
│  Orchestrates Core + Storage; no HTTP concerns                  │
└─────────────────────────────────────────────────────────────────┘
                  ↓                                ↓
┌────────────────────────────┐  ┌──────────────────────────────────┐
│  Core layer  (ML + audio)  │  │  Storage layer  (SQLite + disk)  │
│  voice_encoder, vad,       │  │  api_key_repository,             │
│  speech_recognizer,        │  │  authorization_code_repository,  │
│  anti_spoof,               │  │  voiceprint_repository,          │
│  audio_processor,          │  │  usage_repository                │
│  audio_validator           │  │                                  │
└────────────────────────────┘  └──────────────────────────────────┘
```

**Why this layering matters.** The API layer never touches torch directly — it talks to Services, which call Core. The Storage layer never touches torch either — it lives behind `config_paths.py`, a torch-free path module. This means the unit tests for the rate limiter and OAuth service can run **without ML dependencies installed** (`pytest Tests/test_rate_limiter.py` works even if torch isn't installed). For a production deployment this is also useful: a healthcheck container or a CI smoke test can validate the security layer without needing 2 GB of ML weights.

---

## Request lifecycle

Every request goes through the same 4 stages:

1. **Routing** (`API/Routes/*.py`). FastAPI matches the URL, parses the body, and runs `Depends(require_api_key)`.
2. **Authentication** (`API/dependencies.py`). The `require_api_key` dependency hashes the incoming key with SHA-256, looks it up in `api_keys`, checks the request `Origin` against the key's allowed origins, and atomically increments the hourly usage counter — failing with 429 if the budget is exceeded.
3. **Service orchestration** (`Services/*.py`). The route handler calls the appropriate service method. Long-running ML calls are wrapped in `asyncio.to_thread` so they don't block the event loop:
   ```
   waveform = await asyncio.to_thread(self.audio_processor.process, saved_path)
   await asyncio.to_thread(self.audio_validator.validate, waveform, "verification")
   ```
4. **Response shaping**. Services return plain Python dicts; FastAPI serialises them through Pydantic schemas in `Models/schemas.py`.

---

## OAuth 2.0 authorization code flow

SpeakSecure implements the **authorization code grant** from RFC 6749, the same flow used by Google, GitHub, and most identity providers. There are three actors:

- **User-Agent** — the user's browser
- **Integrator** — a third-party site (e.g. Acme Shop). Has a registered API key with a `redirect_uri` whitelist.
- **SpeakSecure** — the identity provider. Has the user's voice profile.

### Sequence

```
User clicks "Sign in with SpeakSecure" on Acme
                           ↓
   1. Acme backend → 302 to SpeakSecure /authorize
        ?client_id=ssk_live_abc&redirect_uri=https://acme/callback&state=xyz
                           ↓
   2. SpeakSecure validates client_id + redirect_uri exact match
        Renders OAuthFrontend/authorize.html with the integrator's name
                           ↓
   3. User enters their SpeakSecure username, gets a digit challenge,
      records their voice. Browser POSTs to /authorize/submit-signin.
                           ↓
   4. SpeakSecure runs verification, generates a one-time code
      bound to (user_id, api_key_id, redirect_uri), TTL 10s
                           ↓
   5. Browser redirects to https://acme/callback?code=...&state=xyz
                           ↓
   6. Acme backend POSTs to SpeakSecure /token
        Authenticated with Acme's API key
        Body: { "code": "...", "redirect_uri": "https://acme/callback" }
                           ↓
   7. SpeakSecure atomically consumes the code (UPDATE ... WHERE consumed_at IS NULL)
        Returns { "verified": true, "user_id": "alice" }
                           ↓
   8. Acme creates a session for alice, sets a session cookie,
      redirects to its dashboard
```

### Why this design

The flow has three security properties that fall out naturally from RFC 6749:

- **The code never travels through Acme's frontend except as a query parameter in the redirect URL.** Acme's *backend* is what exchanges it. This means even if Acme's frontend is XSS'd, an attacker can read the code but cannot exchange it without Acme's API key (which lives only on Acme's server).

- **The `state` parameter prevents CSRF.** Acme generates `state` before redirecting to `/authorize`, stores it in a short-lived cookie, and verifies it matches when the callback fires. Without `state`, an attacker could trick a victim's browser into hitting Acme's `/callback` with the attacker's own code, logging the victim into the attacker's account.

- **The `redirect_uri` is checked at both `/authorize` and `/token`.** Exact-match against a whitelist registered with the API key. This blocks the [authorization code interception attack](https://datatracker.ietf.org/doc/html/rfc6819#section-4.4.1.1) where an attacker registers a malicious redirect_uri to capture codes for legitimate users.

### The register-redirect flow

A specific design choice: the SpeakSecure `/authorize` page is **sign-in only**. If a user clicks "Don't have an account? Create one," they are redirected to the standalone Demo (which has the full enrolment UI), with the original `/authorize` URL preserved in an `oauth_return` query parameter. After enrolment, the Demo offers a "Continue to Acme Shop →" button that brings them back to `/authorize` to complete the OAuth flow.

This mirrors the pattern used by Google and Microsoft: their OAuth login screens never embed account creation. Doing so would couple two unrelated user-flows in one URL and make the OAuth screen do double duty as a sign-up form.

The `oauth_return` redirect is protected against open-redirect abuse by three layers: URL parse + same-origin check + path whitelist (only paths starting with `/api/v1/authorize` are honoured).

---

## Voice authentication pipeline

Each `/verify` (or `/authorize/submit-signin`) call runs a 6-step pipeline:

```
1. Save uploaded audio to Data/Temp_Audio/   (audio_service)
   ↓
2. Check rate limit + lockout state          (rate_limiter)
   ↓
3. Convert to 16kHz mono WAV via ffmpeg       (audio_processor)
   ↓
4. Validate (duration, speech ratio, energy)  (audio_validator)
   — raises ValueError on garbage input;
     caught and counted as a failed attempt
   ↓
5. Anti-spoofing check                        (anti_spoof / AASIST)
   ↓
6. Speech recognition for digit challenge     (speech_recognizer / Whisper)
   ↓
7. Voice embedding + cosine similarity        (voice_encoder / ECAPA-TDNN)
   ↓
8. Decision logic                             (verification_service)
   — verified IFF: spoof not detected
                  AND digits match
                  AND similarity ≥ SIMILARITY_THRESHOLD
   ↓
9. Update rate limiter (success → reset, fail → record_failed_attempt)
   ↓
10. Delete the temp audio file               (audio_service)
```

Steps 5–7 are the heaviest (each is a forward pass through a neural network). They each run inside `asyncio.to_thread`, so concurrent verifications don't block each other on the event loop.

### Why three models, not one

Each model handles a different attack surface and they are **deliberately independent**:

- **AASIST (anti-spoofing)** rejects synthetic / replayed audio. Trained on ASVspoof 2019. Without this, a deepfake or a recording would pass step 7.
- **Whisper (speech recognition)** ensures the user is speaking the *current* challenge code. Without this, an attacker could record a user's voice once and replay it forever.
- **ECAPA-TDNN (speaker verification)** confirms the voice belongs to the enrolled user. Without this, anyone who memorised the digit challenge could log in.

Compromising one of them isn't enough to forge a sign-in. The attacker would need to defeat all three simultaneously.

---

## Storage model

SQLite, three tables. Atomic operations everywhere security matters.

```
CREATE TABLE api_keys (
    id                  INTEGER PRIMARY KEY,
    key_hash            TEXT NOT NULL UNIQUE,    -- SHA-256(plaintext)
    key_prefix          TEXT NOT NULL,           -- first 16 chars, used as client_id
    name                TEXT NOT NULL,           -- "Acme Shop", shown in OAuth banner
    origins             TEXT NOT NULL,           -- JSON array: ["https://acme.com"]
    redirect_uris       TEXT NOT NULL,           -- JSON array: ["https://acme.com/callback"]
    rate_limit_per_hour INTEGER NOT NULL,
    created_at          TEXT NOT NULL,
    revoked_at          TEXT                     -- NULL = active
);

CREATE TABLE authorization_codes (
    id               INTEGER PRIMARY KEY,
    code             TEXT NOT NULL UNIQUE,        -- secrets.token_urlsafe(32)
    user_id          TEXT NOT NULL,
    verified         INTEGER NOT NULL,
    api_key_id       INTEGER NOT NULL,
    redirect_uri     TEXT NOT NULL,
    similarity_score REAL,
    decision         TEXT,
    created_at       TEXT NOT NULL,
    expires_at       TEXT NOT NULL,               -- created_at + 10s
    consumed_at      TEXT,                        -- NULL until exchanged
    FOREIGN KEY (api_key_id) REFERENCES api_keys(id)
);

CREATE TABLE api_key_usage (
    id            INTEGER PRIMARY KEY,
    api_key_id    INTEGER NOT NULL,
    hour_bucket   TEXT NOT NULL,                  -- "2026-04-29T13"
    request_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(api_key_id, hour_bucket)
);
```

Voice embeddings are stored on disk (not in SQLite) because they are 192-float tensors that change rarely and don't need transactional semantics. Each user gets a `Data/Embeddings/<user_id>.pt` file containing a stack of their enrolled embeddings.

### Atomic operations

- **API key lookup** is a single `SELECT WHERE key_hash = ?` — no race window.
- **Authorization code exchange** uses `UPDATE authorization_codes SET consumed_at = ? WHERE code = ? AND consumed_at IS NULL` and inspects `cursor.rowcount`. Two simultaneous exchanges of the same code: exactly one succeeds.
- **Rate limit increment** uses `INSERT ... ON CONFLICT DO UPDATE SET request_count = request_count + 1 RETURNING request_count`. SQLite serialises this; no double-count under load.

### Path traversal protection

User IDs flow into filenames (`Data/Embeddings/<user_id>.pt`). Without sanitisation, a user_id of `../../../etc/passwd` would read or write outside the embeddings directory. The username regex `^[a-zA-Z0-9_-]{3,32}$` is enforced at the Pydantic schema level, so any request with path-traversal characters is rejected with 422 before reaching the storage layer.

---

## Rate limiting

Two independent limiters:

### Per-API-key hourly budget

Configured per key (`rate_limit_per_hour`, default 1000). Stored in `api_key_usage` per `(api_key_id, hour_bucket)`. The bucket is the current UTC hour as `"YYYY-MM-DDTHH"`, so a key gets a fresh budget every hour on the hour.

This is a **fixed-window** scheme rather than a sliding window. Sliding windows are more accurate but require either Redis or a complex SQLite query. The fixed-window is good enough for the threat model: an attacker can briefly burst at the boundary, but cannot sustain abuse.

### Per-user lockout

After `MAX_FAILED_ATTEMPTS` consecutive failed verifications, the user is locked out for `LOCKOUT_DURATION_SECONDS`. Lockout state is in-memory only. Concurrent failures are serialised inside an `asyncio.Lock` per user, so two simultaneous failed attempts don't race past each other.

**Why in-memory.** Persisting lockout state to disk would let an attacker who can crash the server reset their own lockout. By keeping it in memory, a crash actually clears all active lockouts, but the database itself (which stores hashed keys, not lockout state) is unaffected. The trade-off is intentional.

### DoS-resistant verification

A naive lockout implementation has a hole: if validation throws *before* `record_failed_attempt` is called, the attacker can spam malformed audio to keep the verify pipeline busy without ever incrementing the counter. SpeakSecure closes this by wrapping audio validation in a try/except:

```
try:
    waveform = await asyncio.to_thread(self.audio_processor.process, saved_path)
    await asyncio.to_thread(self.audio_validator.validate, waveform, "verification")
except ValueError:
    await self.rate_limiter.record_failed_attempt(user_id)
    raise
```

Now garbage audio also counts. Five rounds of silence triggers a lockout just like five rounds of voice mismatch.

---

## Frontends

Two single-purpose vanilla JS apps, served from the same backend:

- **`Demo/`** — what a SpeakSecure user sees. Register, sign in, manage profile, delete account. Authenticated to the backend with a public API key embedded in `config.js`. This is the same pattern as the Stripe Dashboard using a Stripe API key — the key is bound to specific origins and rate-limited, so leaking it doesn't grant API abuse from elsewhere.
- **`OAuthFrontend/`** — the `/authorize` page. Single-purpose: sign in only. Talks to a *different* set of endpoints (`/authorize/challenge`, `/authorize/submit-signin`) that issue authorization codes instead of just a verification result.

Both share the same recording UI (`recording.js`-style mic capture + WAV encoding). They are kept as separate trees rather than one shared codebase to avoid coupling: the OAuth frontend should never gain the Demo's profile-management features by accident, and the Demo should never gain the OAuth issuance flow.

The `Demo/Js/config.js` `API_BASE` is set to `/api/v1` (relative path). This means the same code works locally (`http://localhost:8000/api/v1`) and on a deployed Hugging Face Space (`https://murad-speak-secure.hf.space/api/v1`) without changing the file.

---

## Acme Shop demo integrator

`AcmeShopDemo/` is a separate FastAPI app simulating a third-party e-commerce site that consumes SpeakSecure via OAuth. It is deployed as its **own Hugging Face Space**, separate from SpeakSecure itself, to demonstrate that the integration is genuinely cross-domain.

Acme has its own API key issued via `Scripts/create_api_key.py`, registered with origins `["https://murad-acme-shop.hf.space"]` and redirect_uris `["https://murad-acme-shop.hf.space/callback"]`. The base URL of SpeakSecure and the API key value are both injected via environment variables (`SPEAKSECURE_BASE_URL`, `SPEAKSECURE_API_KEY`) — never hardcoded.

Acme's own pages are integrator-agnostic in the OAuth flow direction: SpeakSecure's `/authorize` page reads the integrator's display name from `/oauth/client-info?client_id=...`, so the banner shown to the user ("Sign in to **Acme Shop**") comes from the registered `name` field of the API key, not from anything Acme sends. Adding a new integrator requires only issuing a new key — no backend code changes.

---

## Lifespan and startup

`main.py` defines a FastAPI `lifespan` async context manager that runs on startup and shutdown:

**Startup**
1. `init_database()` creates the three SQLite tables if they don't exist (idempotent, safe on every start).
2. `ModelLoader.load_all()` eagerly loads ECAPA-TDNN, Silero VAD, Whisper, and AASIST. Each loader is wrapped with retry logic (3 attempts, 5s between). If any model fails after retries, the server raises `RuntimeError` and refuses to start — better to fail loudly than serve a half-broken pipeline.
3. The cleanup scheduler starts as a background task (sweeps stale temp files, expired authorization codes, and old usage rows every 10 minutes).

**Shutdown**
- The cleanup task is cancelled gracefully.
- FastAPI flushes any in-flight requests.

Eager model loading on startup pays a one-time cost (~30s) but means the first user request doesn't see the full model load latency. On Hugging Face Spaces this also means the Space appears "Running" only after models are ready, not while they're still loading in the background — fewer false-positive early requests.

---

## Why these technology choices

**FastAPI over Flask.** Async-native (the ML pipeline is naturally I/O + CPU-bound), automatic OpenAPI/Swagger generation (`/docs` works for free), built-in dependency injection via `Depends(...)` for `require_api_key`. Flask would require Flask-RESTX or Flask-OpenAPI plus manual async wrappers around the ML calls.

**SQLite over Postgres.** Single-file, zero-config, atomic, fast enough for the project's scale (one user at a time per voice profile, OAuth codes that live 10 seconds). Postgres would be the right choice for horizontal scaling, but at this stage adds operational complexity without a benefit.

**Vanilla JS over React.** The frontends are forms with mic capture — no state machines, no reactive data. React would add a build step (Webpack/Vite), 30+ npm dependencies, and a separate deploy pipeline for ~600 lines of UI code. The current frontend loads in under 100ms with zero JavaScript dependencies.

**ECAPA-TDNN over wav2vec or x-vector.** Best published EER on VoxCeleb at the time of evaluation, ships as a single file via SpeechBrain, 192-dim embedding (compact for storage). x-vector is older with worse accuracy; wav2vec is far heavier and tuned for transcription, not speaker identity.

**AASIST over RawNet2 or LCNN.** Best ASVspoof 2019 LA EER among open-source models. Ships with a 1.3 MB checkpoint that fits in the repo. The trade-off is that AASIST is over-sensitive to genuine but unusual microphone input — addressed by the two-tier confidence threshold (strict at enrolment, lenient at verification).

**faster-whisper over openai-whisper.** 4× faster CPU inference with the same accuracy — important because verification has a budget of about 2 seconds total (challenge transcription + voice embedding + spoof check + similarity). The `small` model strikes a balance: large enough to transcribe 5-digit codes correctly even with mediocre microphones, small enough to fit in 470 MB.

**OAuth 2.0 over a proprietary token format.** Integrators are already familiar with OAuth from Google/GitHub/Auth0. Using the standard means the Acme Shop integration code looks like every other OAuth integration, with no SpeakSecure-specific SDK or quirks.