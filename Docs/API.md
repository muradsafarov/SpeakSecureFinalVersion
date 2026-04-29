# SpeakSecure API Reference

Full reference for all `/api/v1` endpoints. All endpoints respond with JSON unless noted otherwise.

---

## Authentication

Every endpoint except `/health` and `/oauth/client-info` requires an API key in the `X-API-Key` header:

```
X-API-Key: ssk_live_<your-key>
```

Keys are issued via `python Scripts/create_api_key.py` and stored in the database as SHA-256 hashes. Each key is bound to a list of allowed browser `Origin` values and (for OAuth integrators) a list of allowed `redirect_uri` values.

The `require_api_key` dependency checks, in order:
1. Header is present and not malformed
2. Hash matches a non-revoked key in the database
3. Origin (if the request comes from a browser) is in the key's allowed origins
4. Per-key hourly rate limit not exceeded

If any check fails, the response is `401 Unauthorized` or `429 Too Many Requests` with no information about which check failed.

---

## Health and status

### `GET /health`

Liveness probe. No authentication required. Used by uptime monitors and HF Spaces health checks.

**Response 200**
```
{
  "status": "ok",
  "version": "1.0.0"
}
```

---

### `GET /status`

Returns information about loaded ML models and configuration. Useful for verifying that all models loaded correctly after deployment.

**Response 200**
```
{
  "models": {
    "ecapa_tdnn": "loaded",
    "whisper": "loaded",
    "silero_vad": "loaded",
    "aasist": "loaded"
  },
  "device": "cpu",
  "config": {
    "similarity_threshold": 0.35,
    "challenge_length": 5,
    "max_failed_attempts": 5
  }
}
```

---

## Enrolment

### `POST /enrol`

Register a new user with their first voice sample.

**Request** (`multipart/form-data`)

| Field | Type | Required | Description |
|---|---|---|---|
| `user_id` | string | yes | Unique username. Must match `^[a-zA-Z0-9_-]{3,32}$`. |
| `audio` | file | yes | WAV/MP3/M4A/FLAC/OGG, 3–10 seconds of clear speech. |

**Response 200** — Enrolment accepted
```
{
  "user_id": "alice",
  "samples_count": 1,
  "message": "Voice profile created"
}
```

**Response 400** — Invalid input
```
{ "detail": "Audio too short — please record at least 3 seconds" }
```

**Response 409** — User already exists
```
{ "detail": "User 'alice' is already enrolled" }
```

**Response 422** — Spoof detected
```
{ "detail": "Audio failed anti-spoofing check (confidence: 0.61)" }
```

---

### `POST /enrol/add-sample`

Add an additional voice sample to an existing user's profile. Limited to `MAX_SAMPLES_PER_USER` (default 3).

A new sample must match the existing profile (cosine similarity ≥ `SIMILARITY_THRESHOLD`) — this prevents a session hijacker from replacing stored samples with their own.

**Request** — same fields as `/enrol`.

**Response 200**
```
{
  "user_id": "alice",
  "samples_count": 2,
  "similarity_to_existing": 0.84,
  "message": "Sample added"
}
```

**Response 403** — Voice doesn't match existing profile
```
{ "detail": "Voice does not match the existing profile (similarity: 0.21)" }
```

---

### `GET /enrol/check/{user_id}`

Check whether a username is already enrolled. Used by the Demo to validate username availability before recording.

**Response 200**
```
{ "user_id": "alice", "exists": true, "samples_count": 2 }
```

---

### `DELETE /enrol/{user_id}`

Delete a user's voice profile entirely. Removes the embeddings file and any related state. This is irreversible.

**Response 200**
```
{ "user_id": "alice", "deleted": true }
```

**Response 404**
```
{ "detail": "User 'alice' not found" }
```

---

## Challenge / Verification

### `POST /challenge`

Generate a one-time digit code for a user. The code is bound to the user, expires in `CHALLENGE_EXPIRATION_SECONDS` (default 60), and is consumed atomically when `/verify` succeeds.

**Request**
```
{ "user_id": "alice" }
```

**Response 200**
```
{
  "challenge_id": "c_8f3a...",
  "digits": "47291",
  "expires_in_seconds": 60
}
```

**Response 404** — User not enrolled
```
{ "detail": "User 'alice' not found" }
```

**Response 423** — Locked out
```
{
  "detail": "Too many failed attempts",
  "lockout_seconds_remaining": 38
}
```

---

### `POST /verify`

Verify a user's voice against a previously issued challenge.

**Request** (`multipart/form-data`)

| Field | Type | Required | Description |
|---|---|---|---|
| `user_id` | string | yes | Username |
| `challenge_id` | string | yes | The `challenge_id` returned by `POST /challenge` |
| `audio` | file | yes | The user's recording of the spoken digits |

**Response 200** — Accepted
```
{
  "user_id": "alice",
  "verified": true,
  "similarity": 0.78,
  "challenge_passed": true,
  "transcribed": "47291"
}
```

**Response 200** — Rejected (still 200, with `verified: false`)
```
{
  "user_id": "alice",
  "verified": false,
  "similarity": 0.22,
  "challenge_passed": true,
  "transcribed": "47291",
  "reason": "voice_mismatch"
}
```

The `reason` field is one of: `voice_mismatch`, `wrong_digits`, `spoof_detected`, `borderline`.

**Response 400** — Bad audio (counts as a failed attempt)
```
{ "detail": "Audio is mostly silent — please re-record" }
```

**Response 423** — Locked out
```
{ "detail": "Too many failed attempts", "lockout_seconds_remaining": 41 }
```

---

## OAuth 2.0 (third-party integrators)

SpeakSecure implements the OAuth 2.0 authorization code flow (RFC 6749). Integrators redirect the user's browser to `/authorize`, the user verifies their voice, SpeakSecure redirects back with a one-time `code`, and the integrator's backend exchanges that code for the verification result via `POST /token`.

### `GET /authorize`

The OAuth sign-in HTML page. Returns rendered HTML, not JSON.

**Query parameters**

| Param | Required | Description |
|---|---|---|
| `client_id` | yes | API key prefix (e.g. `ssk_live_abc123`) |
| `redirect_uri` | yes | Where to redirect after sign-in. Must exactly match one of the integrator's registered redirect URIs. |
| `state` | yes | Opaque CSRF token, returned unchanged in the redirect |

**Response 200** — HTML page

**Response 400** — Bad parameters (rendered as HTML error, never as a redirect, to avoid open-redirect leakage)

---

### `GET /oauth/client-info`

Public endpoint (no auth) used by the OAuth page to display the integrator's name in the consent banner ("Sign in to {name}"). This is the only endpoint that returns information about an API key without authentication, and it returns only the public display name — never the rate limit, origins, or any other metadata.

**Query parameters**

| Param | Required | Description |
|---|---|---|
| `client_id` | yes | API key prefix |

**Response 200**
```
{ "name": "Acme Shop" }
```

**Response 404**
```
{ "detail": "Unknown client" }
```

---

### `POST /authorize/challenge`

Generate a digit challenge inside the OAuth flow. Same logic as `POST /challenge`, but bound to the OAuth context.

**Request**
```
{
  "client_id": "ssk_live_abc123",
  "user_id": "alice"
}
```

**Response 200** — Same shape as `/challenge`.

---

### `POST /authorize/submit-signin`

Verify the user's voice inside the OAuth flow and issue an authorization code.

**Request** (`multipart/form-data`) — same fields as `/verify`, plus `client_id`, `redirect_uri`, `state`.

**Response 200** — Verification accepted, code issued
```
{
  "verified": true,
  "redirect_url": "https://acme.example.com/callback?code=AbCdEf123...&state=xyz"
}
```

The integrator's frontend is expected to redirect the browser to `redirect_url`. The code is valid for `AUTHORIZATION_CODE_TTL_SECONDS` (default 10 seconds).

**Response 200** — Verification rejected (still 200; the integrator decides what to show)
```
{
  "verified": false,
  "redirect_url": "https://acme.example.com/callback?code=AbCdEf123...&state=xyz"
}
```

A code is issued either way so the integrator's callback fires. The token-exchange step (`/token`) reveals whether the verification actually passed.

---

### `POST /token`

Server-to-server: exchange an authorization code for the verification result. **Authenticated with the integrator's API key**, not with the code itself.

The exchange is atomic and single-use — calling `/token` twice with the same code returns `400` on the second call.

**Request**
```
{
  "code": "AbCdEf123...",
  "redirect_uri": "https://acme.example.com/callback"
}
```

**Response 200**
```
{
  "verified": true,
  "user_id": "alice"
}
```

**Response 400** — Code expired, already consumed, or `redirect_uri` doesn't match the one bound at issue time
```
{ "detail": "Invalid authorization code" }
```

The `redirect_uri` parameter must match the one passed to `/authorize`. This prevents an attacker who steals the code from exchanging it under a different integrator's credentials.

---

## Error response format

All error responses follow the same shape:

```
{ "detail": "<human-readable message>" }
```

For validation errors, FastAPI's default 422 shape applies:

```
{
  "detail": [
    {
      "loc": ["body", "user_id"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

---

## Rate limiting

Two independent limiters apply:

1. **Per-API-key hourly budget.** Each key has a `rate_limit_per_hour` value (default 1000). Counts are stored in SQLite per `(api_key_id, hour_bucket)`. Exceeding the budget returns `429 Too Many Requests`.

2. **Per-user lockout.** After `MAX_FAILED_ATTEMPTS` consecutive failed verifications for a given user, the user is locked out for `LOCKOUT_DURATION_SECONDS`. Lockout state is in-memory only and resets on successful verification.

A failed attempt is counted whenever:
- `/verify` returns `verified: false`
- `/verify` raises a `ValueError` from audio validation (silent/garbage audio)
- `/authorize/submit-signin` produces either of the above

This prevents an attacker from bypassing the lockout by spamming malformed audio.