/* ===========================================================
   SpeakSecure — /authorize page logic
   Single-file JS. Same coding style as the original frontend
   (procedural, global state, no module system).
   Constants CLIENT_ID / REDIRECT_URI / STATE / INTEGRATOR_NAME
   are injected by the backend before this file loads.
   =========================================================== */

const API_BASE = "/api/v1";
const SAMPLE_RATE = 16000;
const MAX_RECORDING_SECONDS = 10;

// ==================== Global recording state ====================
// Same pattern as the original recording.js — kept simple on purpose

let audioContext = null;
let mediaStream = null;
let recordedSamples = [];
let isRecording = false;
let recordingTarget = null;

let timerInterval = null;
let timerSeconds = 0;
let challengeInterval = null;

let signinBlob = null;

// ==================== Init on load ====================

document.addEventListener('DOMContentLoaded', () => {
    // Set the integrator name in the banner
    document.getElementById('integrator-name-1').textContent = INTEGRATOR_NAME;

    // Wire up live "enable Get my code button on input".
    // We only enable when the field is non-empty AND no challenge is
    // already in flight (challengeWasRequested below) — otherwise
    // typing while a challenge is active would re-enable the button.
    const signinUserId = document.getElementById('signin-user-id');
    if (signinUserId) {
        signinUserId.addEventListener('input', () => {
            const btn = document.getElementById('signin-get-challenge-btn');
            const empty = signinUserId.value.trim().length === 0;
            // If a challenge is currently locked (in flight or active),
            // don't override its state from a keystroke.
            if (btn.dataset.locked === 'true') return;
            btn.disabled = empty;
        });
    }
});


// ==================== Register redirect ====================
// Demo standalone handles all account creation. We hand off the entire OAuth
// context (the current /authorize URL with all its query params) as a single
// `oauth_return` parameter. Demo validates it (same-origin + /api/v1/authorize
// pathname) before honouring the return — see Demo/Js/auth.js.
//
// Why pass the whole URL rather than reconstruct: keeps the source of truth
// in one place. If we ever add new OAuth params (scope, prompt, nonce), they
// ride along automatically without changing this code.

function redirectToRegister() {
    const oauthReturn = encodeURIComponent(window.location.href);
    window.location.href = '/?oauth_return=' + oauthReturn;
}


// ==================== UI helpers ====================

function showResult(target, type, title, details) {
    const el = document.getElementById(target + '-result');
    el.className = 'result visible ' + type;
    el.innerHTML = '<div class="result-header">' + title + '</div>' +
                   '<div class="result-details">' + details + '</div>';
}

function hideResult(target) {
    document.getElementById(target + '-result').className = 'result';
}

/**
 * Build a detailed verification result table — same format as the
 * original frontend so the user sees familiar friendly fields.
 */
function buildVerifyDetails(summary, data) {
    const decisionMap = {
        'accepted': 'Accepted',
        'rejected': 'Rejected',
        'retry':    'Try again',
    };
    const decisionLabel = decisionMap[data.decision] || data.decision;
    const spoofLabel = data.spoof_label === 'bonafide' ? 'Real voice' : 'Possibly fake';

    let rows = '';
    rows += row('Username', data.user_id || '');
    rows += row('Result', decisionLabel || '');

    if (!data.spoof_detected && data.challenge_passed) {
        const pct = (data.similarity_score * 100).toFixed(0);
        rows += row('Voice match', pct + '%');
    }

    if (data.recognized_digits !== undefined && data.recognized_digits !== null) {
        rows += row('Numbers heard', data.recognized_digits || '(nothing heard)');
    }

    rows += row('Code check', data.challenge_passed ? 'Passed' : 'Failed');
    rows += row('Voice check', spoofLabel);
    rows += row('Tries left', data.remaining_attempts);

    return '<p style="margin-bottom:14px;">' + summary + '</p>' +
           '<div class="result-table">' + rows + '</div>';
}

function row(label, value) {
    return '<div class="result-row">' +
               '<span class="result-row-label">' + label + '</span>' +
               '<span class="result-row-value">' + value + '</span>' +
           '</div>';
}

/**
 * Translate raw backend error messages into friendly user-facing strings.
 * Same heuristics as the original helpers.js so behaviour matches.
 */
function friendlyError(raw) {
    const msg = (raw || '').toLowerCase();

    if (msg.includes('too many failed') || msg.includes('temporarily locked') || msg.includes('rate limit')) {
        const match = raw.match(/(\d+)\s*seconds?/i);
        if (match) {
            return 'Too many failed attempts. Your account is temporarily locked. ' +
                   'Please try again in ' + match[1] + ' seconds.';
        }
        return 'Too many failed attempts. Your account is temporarily locked.';
    }
    if (msg.includes('spoofed') || msg.includes('spoofing')) {
        return "The recording doesn't sound like a real person speaking.";
    }
    if (msg.includes('no active challenge')) {
        return 'Your code expired. Please get a new code.';
    }
    if (msg.includes("doesn't match")) {
        return "This voice doesn't match your registered profile. Samples must come from the same person.";
    }
    if (msg.includes('too short')) {
        return 'The recording is too short. Please speak for at least 1 second.';
    }
    if (msg.includes('too long')) {
        return 'The recording is too long. Please keep it under 15 seconds.';
    }
    if (msg.includes('insufficient speech') || msg.includes('too quiet')) {
        return "We couldn't hear enough speech. Please speak clearly and louder.";
    }
    if (msg.includes('no recognizable') || msg.includes('hallucination')) {
        return "We couldn't recognize any speech. Please try again in a quieter place.";
    }
    if (msg.includes('no enrolled voice profile')) {
        return 'No voice profile found for this username. Please register first.';
    }
    if (msg.includes('already used') || msg.includes('used once')) {
        return 'This code was already used. Please get a new one.';
    }
    if (msg.includes('already taken')) {
        return 'This username is already registered. Please choose another or sign in instead.';
    }
    return raw
        .replace(/embedding/gi, 'voice profile')
        .replace(/cosine similarity/gi, 'voice match')
        .replace(/threshold/gi, 'minimum')
        .replace(/AASIST/gi, 'voice check');
}


// ==================== Recording (lifted from recording.js) ====================
// Web Audio API + ScriptProcessor → mono 16kHz WAV blob.
// Same as the standalone Demo's recording.js, with target='signin'
// (single recording flow — register has been moved out of /authorize).

function encodeWAV(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);

    function writeString(offset, str) {
        for (let i = 0; i < str.length; i++) {
            view.setUint8(offset + i, str.charCodeAt(i));
        }
    }

    writeString(0, 'RIFF');
    view.setUint32(4, 36 + samples.length * 2, true);
    writeString(8, 'WAVE');
    writeString(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeString(36, 'data');
    view.setUint32(40, samples.length * 2, true);

    for (let i = 0; i < samples.length; i++) {
        let s = Math.max(-1, Math.min(1, samples[i]));
        view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }

    return new Blob([buffer], { type: 'audio/wav' });
}

// Global flag — true while a signin verify request is in flight.
// Inline onclick handlers on <button> bypass the disabled attribute,
// so we use this flag as the SOURCE OF TRUTH for whether a new
// recording can start. Mirrors the recordingLocked pattern from Demo.
let recordingLocked = false;

async function toggleRecording(target) {
    if (recordingLocked) return;
    if (isRecording) {
        stopRecording(target);
    } else {
        await startRecording(target);
    }
}

/**
 * Lock or unlock the record button. Single source of truth (the global
 * flag), plus a CSS class for visual feedback (greyed out + not-allowed).
 */
function setRecordButton(target, locked) {
    recordingLocked = locked;
    const btn = document.getElementById(target + '-record-btn');
    if (!btn) return;
    btn.disabled = locked;
    btn.classList.toggle('locked', locked);
}

async function startRecording(target) {
    try {
        mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                sampleRate: SAMPLE_RATE,
                channelCount: 1,
                echoCancellation: false,
                noiseSuppression: false,
                autoGainControl: false,
            },
        });

        audioContext = new AudioContext();
        const source = audioContext.createMediaStreamSource(mediaStream);
        const processor = audioContext.createScriptProcessor(4096, 1, 1);

        recordedSamples = [];
        isRecording = true;
        recordingTarget = target;

        processor.onaudioprocess = (e) => {
            if (isRecording) {
                recordedSamples.push(new Float32Array(e.inputBuffer.getChannelData(0)));
            }
        };

        source.connect(processor);
        processor.connect(audioContext.destination);

        document.getElementById(target + '-record-btn').classList.add('recording');
        document.getElementById(target + '-record-label').textContent = 'Recording... tap to stop';

        // Start timer
        timerSeconds = 0;
        const timerEl = document.getElementById(target + '-timer');
        timerEl.classList.add('visible', 'active');
        timerInterval = setInterval(() => {
            timerSeconds++;
            timerEl.textContent =
                String(Math.floor(timerSeconds / 60)).padStart(2, '0') + ':' +
                String(timerSeconds % 60).padStart(2, '0');

            // Auto-stop at MAX_RECORDING_SECONDS
            if (timerSeconds >= MAX_RECORDING_SECONDS) {
                stopRecording(target);
            }
        }, 1000);
    } catch (err) {
        showResult(target, 'error', 'Microphone access denied',
            'Please allow microphone access in your browser and try again.');
    }
}

function stopRecording(target) {
    isRecording = false;
    clearInterval(timerInterval);

    let totalLength = 0;
    for (const chunk of recordedSamples) totalLength += chunk.length;
    const merged = new Float32Array(totalLength);
    let offset = 0;
    for (const chunk of recordedSamples) {
        merged.set(chunk, offset);
        offset += chunk.length;
    }

    const wavBlob = encodeWAV(merged, audioContext.sampleRate);

    if (target === 'signin') {
        signinBlob = wavBlob;
        document.getElementById('signin-submit-btn').disabled = false;
        document.getElementById('signin-record-label').textContent = 'Recording saved, ready to sign in';
        document.getElementById('signin-step-2').className = 'step-dot done';
        document.getElementById('signin-step-3').className = 'step-dot active';
    }
    // 'register' branch removed — registration happens on Demo standalone now.

    document.getElementById(target + '-record-btn').classList.remove('recording');
    const timerEl = document.getElementById(target + '-timer');
    if (timerEl) timerEl.classList.remove('active');

    if (mediaStream) mediaStream.getTracks().forEach(t => t.stop());
    if (audioContext) audioContext.close();
    audioContext = null;
    mediaStream = null;
}


// ==================== Sign-in flow ====================

// ==================== Challenge button lock ====================
// Mirrors the original frontend's setChallengeButton helper.
// While locked, the user cannot generate a NEW challenge until
// the current one either completes (verify success/fail) or
// expires (timer reaches 0). This prevents the bug where typing
// in the username field re-enables the button mid-flow.
//
// `challengeWasRequested` persists across calls so the unlocked
// label changes from "Get my code" → "Get a new code" after the
// first attempt.
let challengeWasRequested = false;

function setChallengeButton(locked) {
    const btn = document.getElementById('signin-get-challenge-btn');
    if (!btn) return;

    btn.disabled = locked;
    btn.dataset.locked = locked ? 'true' : 'false';

    if (locked) {
        // Pending state — show spinner and lock the button
        btn.innerHTML = '<span class="spinner"></span> Getting code...';
        challengeWasRequested = true;
    } else {
        // Unlocked — label depends on whether this is the first try
        btn.innerHTML = challengeWasRequested ? 'Get a new code' : 'Get my code';
    }
}

async function getChallenge() {
    const userId = document.getElementById('signin-user-id').value.trim();
    if (!userId) return;

    const btn = document.getElementById('signin-get-challenge-btn');
    setChallengeButton(true);
    document.getElementById('signin-user-id').disabled = true;
    hideResult('signin');

    try {
        const fd = new FormData();
        fd.append('user_id', userId);
        fd.append('client_id', CLIENT_ID);
        fd.append('redirect_uri', REDIRECT_URI);
        fd.append('state', STATE);

        const res = await fetch(API_BASE + '/authorize/challenge', { method: 'POST', body: fd });
        const data = await res.json();

        if (!res.ok) {
            if (res.status === 404) {
                showResult('signin', 'error', 'User not found',
                    'No voice profile exists for "<strong>' + userId + '</strong>". ' +
                    'Click <a onclick="redirectToRegister()" style="color:var(--accent);cursor:pointer;text-decoration:underline;">Create one</a> to register a new voice profile.');
            } else {
                showResult('signin', 'error', "Couldn't get code", friendlyError(data.detail || 'Unknown error'));
            }
            // Failed to get a code — unlock so user can retry
            setChallengeButton(false);
            document.getElementById('signin-user-id').disabled = false;
            return;
        }

        // Show challenge + record cards
        document.getElementById('signin-challenge-card').style.display = 'block';
        document.getElementById('signin-record-card').style.display = 'block';
        document.getElementById('signin-submit-btn').style.display = 'flex';
        document.getElementById('signin-challenge-digits').textContent = data.challenge;
        document.getElementById('signin-step-1').className = 'step-dot done';
        document.getElementById('signin-step-2').className = 'step-dot active';

        // Countdown
        let remaining = data.expires_in_seconds;
        const timerEl = document.getElementById('signin-challenge-timer');
        timerEl.textContent = remaining;
        timerEl.style.color = '';

        if (challengeInterval) clearInterval(challengeInterval);
        challengeInterval = setInterval(() => {
            remaining--;
            timerEl.textContent = remaining;
            if (remaining <= 10) timerEl.style.color = 'var(--danger)';
            if (remaining <= 0) {
                clearInterval(challengeInterval);
                timerEl.textContent = 'expired';
                document.getElementById('signin-submit-btn').disabled = true;
                showResult('signin', 'warning', 'Code expired',
                    'Please request a new code to continue.');
                // Unlock — user can request a fresh code now
                setChallengeButton(false);
            }
        }, 1000);

        // Challenge is now active — keep the button LOCKED until either:
        //   (a) the timer expires (handled above)
        //   (b) submit-signin completes (success → redirect, fail → unlock)
        // This prevents the user from generating a new code mid-flow.
        document.getElementById('signin-user-id').disabled = false;
    } catch (err) {
        showResult('signin', 'error', 'Connection error', 'Could not reach the server.');
        // Network error — unlock so user can retry
        setChallengeButton(false);
        document.getElementById('signin-user-id').disabled = false;
    }
}

async function submitSignin() {
    if (!signinBlob) return;
    const userId = document.getElementById('signin-user-id').value.trim();

    const btn = document.getElementById('signin-submit-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Verifying...';
    // Lock record button — user can't record again while verify runs.
    setRecordButton('signin', true);
    hideResult('signin');

    try {
        const fd = new FormData();
        fd.append('user_id', userId);
        fd.append('client_id', CLIENT_ID);
        fd.append('redirect_uri', REDIRECT_URI);
        fd.append('state', STATE);
        fd.append('audio_file', signinBlob, 'recording.wav');

        const res = await fetch(API_BASE + '/authorize/submit-signin', {
            method: 'POST',
            body: fd,
        });
        const data = await res.json();

        if (!res.ok) {
            showResult('signin', 'error', 'Sign-in failed', friendlyError(data.detail || 'Unknown error'));
            resetSigninForRetry();
            return;
        }

        if (data.verified && data.redirect_url) {
            // SUCCESS — show full details, then redirect
            const summary = '<strong>Welcome back, ' + data.user_id + '.</strong> ' +
                            'Returning you to ' + INTEGRATOR_NAME + '...';
            showResult('signin', 'success', '✓ Verified', buildVerifyDetails(summary, data));

            // Mark final step as done
            document.getElementById('signin-step-3').className = 'step-dot done';

            if (challengeInterval) clearInterval(challengeInterval);
            // Brief pause so the user sees the success message, then redirect
            setTimeout(() => { window.location.href = data.redirect_url; }, 1400);
        } else if (data.retry_required) {
            const summary = "Almost there — your voice was close but we'd like another try.";
            showResult('signin', 'warning', 'Try again', buildVerifyDetails(summary, data));
            resetSigninForRetry();
        } else if (data.spoof_detected) {
            const summary = 'The recording was flagged as possibly synthetic. ' +
                            'Please record again with your microphone.';
            showResult('signin', 'error', 'Suspicious audio', buildVerifyDetails(summary, data));
            resetSigninForRetry();
        } else if (!data.challenge_passed) {
            const summary = 'The digits you spoke did not match the code. Please try again.';
            showResult('signin', 'error', 'Wrong code', buildVerifyDetails(summary, data));
            resetSigninForRetry();
        } else {
            const summary = 'Voice did not match the registered profile. ' +
                (data.remaining_attempts > 0
                    ? data.remaining_attempts + ' attempt(s) remaining.'
                    : 'Account temporarily locked.');
            showResult('signin', 'error', 'Sign-in failed', buildVerifyDetails(summary, data));
            if (data.remaining_attempts > 0) resetSigninForRetry();
        }
    } catch (err) {
        showResult('signin', 'error', 'Connection error', 'Could not reach the server.');
        resetSigninForRetry();
    }
}

function resetSigninForRetry() {
    const btn = document.getElementById('signin-submit-btn');
    btn.innerHTML = 'Sign me in';
    btn.disabled = true;
    document.getElementById('signin-record-label').textContent = 'Tap the button and say the digits';
    signinBlob = null;
    document.getElementById('signin-step-3').className = 'step-dot';
    document.getElementById('signin-step-2').className = 'step-dot active';
    // Unlock challenge button — user can request a fresh code for retry.
    setChallengeButton(false);
    // Unlock record button — user can record their next attempt.
    setRecordButton('signin', false);
    // Stop any countdown still running from the previous code.
    if (challengeInterval) clearInterval(challengeInterval);
}