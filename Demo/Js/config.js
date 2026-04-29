/* ===========================================================
   SpeakSecure - Configuration
   API endpoint and global state shared across scripts.
   =========================================================== */

// API endpoint - change this if the backend runs on a different host
// Relative path — works for both local development (python run.py)
// and the deployed Hugging Face Space, since the frontend is
// served from the same origin as the backend. Avoids the need to
// rewrite this file when the public URL changes.
const API_BASE = "/api/v1";

// API key for the SpeakSecure self-service Demo.
//
// SECURITY MODEL:
//   This key is intentionally embedded in the browser. The Demo is
//   itself a first-party client of the SpeakSecure API — analogous
//   to how the Stripe Dashboard uses a Stripe API key when consuming
//   the Stripe API. It's not a secret in the same way a server-to-
//   server integration key is.
//
//   Three layers of protection prevent abuse if this key is copied:
//     1. Origin check: the key is bound to the SpeakSecure host
//        (http://localhost:8000 + http://127.0.0.1:8000). Calling it
//        from another origin in a browser is blocked by the backend.
//     2. Per-key rate limit: hourly request budget enforced server-side.
//     3. The key can be revoked at any time via the CLI; users keep
//        their voice profiles, only the Demo would need a new key.
//
//   For full third-party authentication (where the integrator wants
//   the user identity without trusting their frontend), the OAuth
//   flow at /api/v1/authorize is used instead — that's how Acme Shop
//   integrates with SpeakSecure, not via this key.
const API_KEY = "Here was a Key";

// Target sample rate for audio recording (must match backend)
const SAMPLE_RATE = 16000;

// ==================== Global recording state ====================
// These variables are shared between recording.js and api.js

let audioContext = null;
let mediaStream = null;
let recordedSamples = [];
let isRecording = false;
let recordingTarget = null;

// ==================== Global timer state ====================

let timerInterval = null;
let timerSeconds = 0;
let challengeInterval = null;

// ==================== Audio blobs ====================
// Store the recorded audio blob for each operation

let enrolBlob = null;
let verifyBlob = null;
let improveBlob = null;  // For adding extra samples on the Improve Voice page