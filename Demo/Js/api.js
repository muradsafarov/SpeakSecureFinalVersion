/* ===========================================================
   SpeakSecure - API Calls
   All HTTP requests to the backend (enrol, verify, challenge, delete).
   Uses the global blobs and API_BASE defined in config.js.

   Every request includes the X-API-Key header. The backend rejects
   any call without it (401), enforces an Origin allowlist for this
   key (browser-side abuse protection), and tracks per-key usage
   counters for hourly rate limiting.
   =========================================================== */

/**
 * Build the standard request headers for authenticated calls.
 * Use this when a fetch call sends NO body or a JSON body.
 *
 * For FormData uploads (audio files), do NOT set Content-Type
 * manually — the browser must set it including the multipart boundary.
 * In those cases, use only `apiKeyOnlyHeaders()` below.
 */
function authHeaders() {
    return {
        'X-API-Key': API_KEY,
    };
}

/**
 * Just the X-API-Key header. Use for FormData uploads where the
 * browser must set Content-Type itself (multipart/form-data with
 * the correct boundary).
 */
function apiKeyOnlyHeaders() {
    return {
        'X-API-Key': API_KEY,
    };
}

/**
 * Request a new verification challenge from the backend.
 * Shows the digit code to the user and starts the countdown timer.
 */
async function getChallenge() {
    const userId = document.getElementById('verify-user-id').value.trim();
    if (!userId) {
        showResult('verify', 'error', 'Username required', 'Please enter your username first.');
        return;
    }

    // Lock the "Get my code" button until the verification attempt finishes
    // (accepted, rejected, retry, spoof, error...). This prevents the user
    // from requesting a new code while a previous one is still in progress.
    setChallengeButton(true);

    try {
        const fd = new FormData();
        fd.append('user_id', userId);
        const res = await fetch(API_BASE + '/challenge', {
            method: 'POST',
            headers: apiKeyOnlyHeaders(),
            body: fd,
        });
        const data = await res.json();

        if (!res.ok) {
            // Challenge request failed - unlock the button so user can retry
            showResult('verify', 'error', "Couldn't get a code",
                friendlyError(data.detail || 'Unknown error'));
            setChallengeButton(false);
            return;
        }

        // Success - keep button disabled until verify completes.
        // Only reset the submit button + step 3 (step 2 becomes active below).
        verifyBlob = null;
        const submitBtn = document.getElementById('verify-submit-btn');
        if (submitBtn) submitBtn.disabled = true;

        // Reveal the next steps (challenge display and record button)
        document.getElementById('challenge-card').style.display = 'block';
        document.getElementById('verify-record-card').style.display = 'block';
        document.getElementById('verify-submit-btn').style.display = 'block';

        // Show the challenge digits
        document.getElementById('challenge-digits').textContent = data.challenge;
        document.getElementById('challenge-digits').style.color = 'var(--accent)';

        // Advance step indicator
        document.getElementById('verify-step-1').className = 'step-dot done';
        document.getElementById('verify-step-2').className = 'step-dot active';
        document.getElementById('verify-step-3').className = 'step-dot';

        // Start countdown timer (shows seconds until challenge expires)
        let remaining = data.expires_in_seconds;
        document.getElementById('challenge-countdown').textContent = remaining;
        clearInterval(challengeInterval);
        challengeInterval = setInterval(() => {
            remaining--;
            document.getElementById('challenge-countdown').textContent = remaining;
            if (remaining <= 0) {
                clearInterval(challengeInterval);
                document.getElementById('challenge-digits').textContent = 'EXPIRED';
                document.getElementById('challenge-digits').style.color = 'var(--danger)';
                // Code expired without an attempt - unlock so user can request new one
                setChallengeButton(false);
            }
        }, 1000);

        hideResult('verify');
    } catch (err) {
        showResult('verify', 'error', 'Connection error',
            'Could not reach the server. Please try again.');
        // Network error - unlock the button so user can retry
        setChallengeButton(false);
    }
}

/**
 * Enable or disable the "Get my code" button.
 * Has THREE visual states that reflect the full lifecycle:
 *   1. "Get my code"    - initial state, before any attempt
 *   2. "Getting code..." - locked, request/verify in progress
 *   3. "Get new code"   - unlocked, user can request a fresh code
 *                         (shown after the first successful challenge)
 *
 * The `challengeWasRequested` flag persists across calls so that after
 * the first attempt we show "Get new code" instead of "Get my code".
 */
let challengeWasRequested = false;

function setChallengeButton(locked) {
    const btn = document.getElementById('get-challenge-btn');
    if (!btn) return;

    btn.disabled = locked;

    if (locked) {
        // Pending state - show spinner and lock interaction
        btn.innerHTML = '<span class="spinner"></span> Getting code...';
        challengeWasRequested = true;
    } else {
        // Unlocked - label depends on whether this is first attempt or not
        btn.innerHTML = challengeWasRequested ? 'Get new code' : 'Get my code';
    }
}

/**
 * Check if a username is already registered.
 * Returns { exists, num_samples, max_samples, can_add_sample } or null on error.
 */
async function checkUsername(userId) {
    try {
        const res = await fetch(API_BASE + '/enrol/check/' + encodeURIComponent(userId), {
            headers: authHeaders(),
        });
        if (!res.ok) return null;
        return await res.json();
    } catch (err) {
        return null;
    }
}

/**
 * Shared helper that performs an audio-upload POST request.
 * Handles the spinner, FormData construction, JSON parsing, and network
 * errors — caller decides what to do with the successful/error response.
 *
 * Params:
 *   endpoint       - e.g. '/enrol' or '/enrol/add-sample'
 *   userId, blob   - the form fields to upload
 *   target         - 'enrol' | 'verify' | 'improve' (for showResult)
 *   btn            - the submit button (will be disabled + show spinner)
 *   spinnerLabel   - text shown next to the spinner while pending
 *
 * Returns an object:
 *   { ok: true,  res, data }  — network succeeded, caller inspects res/data
 *   { ok: false }              — network failed, error already shown to user
 */
async function uploadAudio({ endpoint, userId, blob, target, btn, spinnerLabel }) {
    btn.innerHTML = '<span class="spinner"></span> ' + spinnerLabel;
    btn.disabled = true;

    try {
        const fd = new FormData();
        fd.append('user_id', userId);
        fd.append('audio_file', blob, 'recording.wav');
        const res = await fetch(API_BASE + endpoint, {
            method: 'POST',
            headers: apiKeyOnlyHeaders(),
            body: fd,
        });
        const data = await res.json();
        return { ok: true, res, data };
    } catch (err) {
        showResult(target, 'error', 'Connection error',
            'Could not reach the server. Please try again.');
        return { ok: false };
    }
}

/**
 * Register a brand new user with their first voice sample.
 * Checks username availability BEFORE uploading audio, so the user gets
 * fast feedback if the name is taken.
 */
async function submitEnrol() {
    const userId = document.getElementById('enrol-user-id').value.trim();
    if (!userId) {
        showResult('enrol', 'error', 'Username required', 'Please choose a username.');
        return;
    }
    if (!enrolBlob) {
        showResult('enrol', 'error', 'No recording', 'Please record your voice first.');
        return;
    }

    const btn = document.getElementById('enrol-submit-btn');

    // Fast pre-check: is the username already taken? Show spinner while checking.
    btn.innerHTML = '<span class="spinner"></span> Processing...';
    btn.disabled = true;

    const check = await checkUsername(userId);
    if (check && check.exists) {
        showResult('enrol', 'error', 'Username taken',
            'The username <strong>' + userId + '</strong> is already registered. ' +
            'Please choose a different username, or sign in if this is your account.'
        );
        btn.innerHTML = 'Register my voice';
        btn.disabled = false;
        return;
    }

    // Lock record button — user can't record again while we upload.
    setRecordButton('enrol', true);

    // Upload the audio — helper handles network errors and spinner
    const result = await uploadAudio({
        endpoint: '/enrol',
        userId, blob: enrolBlob, target: 'enrol', btn,
        spinnerLabel: 'Processing...',
    });

    if (result.ok) {
        const { res, data } = result;
        if (res.ok && data.success) {
            // If we got here from an OAuth /authorize redirect, the success
            // message and continue button should send the user BACK to the
            // integrator's auth flow rather than to Demo's local sign-in.
            const oauthRedirect = typeof hasOAuthRedirect === 'function' && hasOAuthRedirect();
            const integratorName = oauthRedirect && typeof getOAuthIntegratorName === 'function'
                ? getOAuthIntegratorName()
                : null;

            if (oauthRedirect) {
                showResult('enrol', 'success', '✓ Account created',
                    '<strong>Username:</strong> ' + data.user_id + '<br><br>' +
                    'You can now return to <strong>' + integratorName + '</strong> ' +
                    'and sign in with your voice.'
                );
            } else {
                showResult('enrol', 'success', '✓ Voice registered successfully',
                    '<strong>Username:</strong> ' + data.user_id + '<br>' +
                    '<strong>Samples stored:</strong> ' + data.num_samples + ' of ' + data.max_samples + '<br><br>' +
                    'You can now sign in with your voice.'
                );
            }

            // Reveal the "Continue" button — its label and click handler
            // depend on whether we're inside an OAuth flow or standalone.
            const gotoBtn = document.getElementById('goto-verify-btn');
            if (gotoBtn) {
                gotoBtn.style.display = 'block';
                if (oauthRedirect) {
                    gotoBtn.textContent = 'Continue to ' + integratorName + ' →';
                    gotoBtn.onclick = () => returnToOAuth();
                }
                // else: keep the original onclick (navigateTo('verify')) and label
            }
            const verifyInput = document.getElementById('verify-user-id');
            if (verifyInput) verifyInput.value = data.user_id;

            // Hide the submit button since registration is complete
            btn.style.display = 'none';
        } else {
            showResult('enrol', 'error', "Couldn't register",
                friendlyError(data.detail || 'Unknown error'));
            btn.innerHTML = 'Register my voice';
            btn.disabled = false;
        }
    } else {
        // Network error - reset the button
        btn.innerHTML = 'Register my voice';
        btn.disabled = false;
    }

    enrolBlob = null;
    resetRecordingUI('enrol');
    setRecordButton('enrol', false);
}

/**
 * Add an extra voice sample to an existing user's profile.
 * The "Improve voice recognition" page calls this to expand the
 * stored profile up to MAX_SAMPLES_PER_USER samples.
 */
async function submitImproveSample() {
    const userId = document.getElementById('improve-user-id').value.trim();
    if (!userId) {
        showResult('improve', 'error', 'Not signed in',
            'You must be signed in to improve your voice profile.');
        return;
    }
    if (!improveBlob) {
        showResult('improve', 'error', 'No recording',
            'Please record an extra sample first.');
        return;
    }

    const btn = document.getElementById('improve-submit-btn');

    setRecordButton('improve', true);

    const result = await uploadAudio({
        endpoint: '/enrol/add-sample',
        userId, blob: improveBlob, target: 'improve', btn,
        spinnerLabel: 'Adding sample...',
    });

    if (result.ok) {
        const { res, data } = result;
        if (res.ok && data.success) {
            showResult('improve', 'success', '✓ Sample added',
                'Your voice profile now has <strong>' + data.num_samples + '</strong> ' +
                'sample' + (data.num_samples === 1 ? '' : 's') +
                ' out of ' + data.max_samples + ' allowed.'
            );
            // Update the counter and disable button if limit reached
            updateImproveCounter(data.num_samples, data.max_samples);
        } else {
            showResult('improve', 'error', "Couldn't add sample",
                friendlyError(data.detail || data.message || 'Unknown error'));
        }
    }

    btn.innerHTML = 'Add voice sample';
    btn.disabled = true;  // Require a new recording before allowing another submission
    improveBlob = null;

    // Reset the recording UI so user can record again if they want
    resetRecordingUI('improve');
    setRecordButton('improve', false);
}

/**
 * Update the "X of Y samples" display on the Improve page.
 * Disables the record button if the limit has been reached.
 */
function updateImproveCounter(current, max) {
    const counterEl = document.getElementById('improve-counter');
    if (counterEl) {
        counterEl.textContent = current + ' of ' + max + ' samples';
    }

    const recordBtn = document.getElementById('improve-record-btn');
    const submitBtn = document.getElementById('improve-submit-btn');
    const limitMsg = document.getElementById('improve-limit-msg');

    if (current >= max) {
        // Limit reached - disable recording
        if (recordBtn) recordBtn.disabled = true;
        if (submitBtn) submitBtn.style.display = 'none';
        if (limitMsg) limitMsg.style.display = 'block';
    } else {
        if (recordBtn) recordBtn.disabled = false;
        if (submitBtn) submitBtn.style.display = 'block';
        if (limitMsg) limitMsg.style.display = 'none';
    }
}

/**
 * Submit a voice verification (sign-in).
 * Uploads the recorded audio and displays detailed result based on
 * whether the voice matched, challenge passed, or a spoof was detected.
 */
async function submitVerify() {
    const userId = document.getElementById('verify-user-id').value.trim();
    if (!userId) {
        showResult('verify', 'error', 'Username required', 'Please enter your username.');
        return;
    }
    if (!verifyBlob) {
        showResult('verify', 'error', 'No recording', 'Please record your voice first.');
        return;
    }

    const btn = document.getElementById('verify-submit-btn');
    btn.innerHTML = '<span class="spinner"></span> Checking...';
    btn.disabled = true;
    // Lock record button — user can't record again while we verify.
    setRecordButton('verify', true);

    // Track whether this attempt ended in a successful sign-in.
    // If yes, we redirect to home (no need to unlock the challenge button).
    // If no, we unlock so the user can request a new code and try again.
    let wasSuccess = false;

    try {
        const fd = new FormData();
        fd.append('user_id', userId);
        fd.append('audio_file', verifyBlob, 'recording.wav');
        const res = await fetch(API_BASE + '/verify', {
            method: 'POST',
            headers: apiKeyOnlyHeaders(),
            body: fd,
        });
        const data = await res.json();

        if (res.ok && data.success) {
            let type, title, summary;

            // Determine result category - each case gets its own message
            if (data.verified) {
                wasSuccess = true;
                type = 'success';
                title = '✓ Welcome back!';
                summary = 'Your voice has been confirmed. Taking you to your home page...';
                document.getElementById('verify-step-3').className = 'step-dot done';

                // Mark user as signed in - profile menu appears in nav bar
                setCurrentUser(data.user_id);

                // Redirect to the signed-in home (dashboard) after a short delay
                // so the user has time to read the success message.
                setTimeout(() => navigateTo('home'), 1800);
            }
            else if (data.spoof_detected) {
                type = 'error';
                title = 'Fake voice detected';
                summary = 'The recording appears to be synthetic or replayed. ' +
                    'Please record your own voice directly into the microphone, ' +
                    'not from a speaker or another device.';
            }
            else if (!data.challenge_passed) {
                type = 'error';
                title = 'Numbers did not match';
                summary = 'The numbers you said did not match the code. Please get a new code and try again.';
            }
            else if (data.retry_required) {
                type = 'warning';
                title = 'Almost there, please try again';
                summary = 'Your voice is close to your profile, but not quite close enough. ' +
                    'Try again in a quiet place, speaking clearly into the microphone.';
            }
            else {
                type = 'error';
                title = 'Voice does not match';
                summary = 'This voice does not match the registered profile for this username.';
            }

            // Build the detailed field breakdown
            const details = buildVerifyDetails(summary, data);
            showResult('verify', type, title, details);
        } else {
            showResult('verify', 'error', 'Sign-in failed',
                friendlyError(data.detail || 'Unknown error'));
        }
    } catch (err) {
        showResult('verify', 'error', 'Connection error',
            'Could not reach the server. Please try again.');
    }

    btn.innerHTML = 'Sign me in';
    btn.disabled = false;
    verifyBlob = null;

    // Always unlock the record button, even on success — the page navigates
    // away anyway, but if the user lands back on a recording screen later
    // (e.g. Improve voice), the global recordingLocked flag would otherwise
    // stay stuck at true and freeze the mic forever.
    setRecordButton('verify', false);

    // Unlock "Get my code" only on failure — on success we redirect.
    if (!wasSuccess) {
        setChallengeButton(false);
    }
}

/**
 * Delete a user's voice profile from the server.
 * Requires username confirmation and a browser confirm dialog.
 */
async function submitDelete() {
    const userId = document.getElementById('delete-user-id').value.trim();
    if (!userId) {
        showResult('delete', 'error', 'Not signed in',
            'You must be signed in to delete your account.');
        return;
    }

    // Safety check: only allow deleting the currently signed-in account
    const currentUser = getCurrentUser();
    if (currentUser !== userId) {
        showResult('delete', 'error', 'Access denied',
            'You can only delete your own account. Please sign in first.');
        return;
    }

    // Final confirmation dialog
    if (!confirm('Are you sure you want to delete "' + userId + '"? This cannot be undone.')) {
        return;
    }

    const btn = document.getElementById('delete-btn');
    btn.innerHTML = '<span class="spinner"></span> Deleting...';
    btn.disabled = true;

    try {
        const res = await fetch(API_BASE + '/enrol/' + encodeURIComponent(userId), {
            method: 'DELETE',
            headers: authHeaders(),
        });
        const data = await res.json();

        if (res.ok && data.success) {
            showResult('delete', 'success', '✓ Profile deleted',
                'Voice profile for <strong>' + userId + '</strong> has been removed.<br>' +
                'Redirecting to home page...'
            );

            // Clear auth so sessionStorage is wiped before reload.
            // Then do a full page reload to guarantee a clean state -
            // this prevents any leftover UI state (challenge, recording,
            // step indicators) from appearing on the next sign-in.
            clearCurrentUser();
            setTimeout(() => {
                window.location.href = '/';
            }, 1500);
        } else {
            showResult('delete', 'error', "Couldn't delete profile",
                friendlyError(data.detail || 'Unknown error'));
        }
    } catch (err) {
        showResult('delete', 'error', 'Connection error',
            'Could not reach the server. Please try again.');
    }

    btn.innerHTML = 'Delete my profile';
    btn.disabled = false;
}