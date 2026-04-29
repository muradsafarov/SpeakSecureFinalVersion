/* ===========================================================
   SpeakSecure - Authentication state
   Manages the "signed in" state using browser sessionStorage.
   Session persists across page reloads but resets when:
     - The user signs out manually
     - The browser tab is closed
     - The backend server is restarted (sessionStorage remains,
       but if the profile was deleted, the next action will fail)
   =========================================================== */

// Storage key for the signed-in username
const AUTH_KEY = 'speaksecure_user';

/**
 * Get the currently signed-in username, or null if nobody is signed in.
 */
function getCurrentUser() {
    return sessionStorage.getItem(AUTH_KEY);
}

/**
 * Mark the user as signed in - stores username in sessionStorage
 * and updates the profile menu in the nav bar.
 */
function setCurrentUser(username) {
    sessionStorage.setItem(AUTH_KEY, username);
    updateAuthUI();
}

/**
 * Clear the signed-in state - removes username from sessionStorage
 * and hides the profile menu.
 */
function clearCurrentUser() {
    sessionStorage.removeItem(AUTH_KEY);
    updateAuthUI();
}

/**
 * Update the nav bar and home page based on whether the user is signed in.
 * - Shows/hides the profile menu in the nav bar
 * - Switches the home page between guest view and signed-in dashboard
 */
function updateAuthUI() {
    const user = getCurrentUser();
    const menu = document.getElementById('profile-menu');
    const homeGuest = document.getElementById('home-guest');
    const homeSignedIn = document.getElementById('home-signed-in');

    if (!menu) return;

    if (user) {
        // Signed in: show profile menu, switch home to dashboard view
        menu.style.display = 'block';
        document.getElementById('profile-name').textContent = user;
        document.getElementById('profile-dropdown-name').textContent = user;

        if (homeGuest) homeGuest.style.display = 'none';
        if (homeSignedIn) {
            homeSignedIn.style.display = 'block';
            const usernameEl = document.getElementById('dashboard-username');
            if (usernameEl) usernameEl.textContent = user;
        }
    } else {
        // Signed out: hide profile menu, show guest home
        menu.style.display = 'none';
        closeProfileDropdown();

        if (homeGuest) homeGuest.style.display = '';
        if (homeSignedIn) homeSignedIn.style.display = 'none';
    }
}

/**
 * Toggle the profile dropdown (the panel below the profile button).
 */
function toggleProfileDropdown() {
    const dropdown = document.getElementById('profile-dropdown');
    dropdown.classList.toggle('open');
}

/**
 * Close the profile dropdown.
 */
function closeProfileDropdown() {
    const dropdown = document.getElementById('profile-dropdown');
    if (dropdown) dropdown.classList.remove('open');
}

/**
 * Sign out the current user.
 * Clears sessionStorage, resets all form state, and navigates back home.
 */
function signOut() {
    closeProfileDropdown();
    clearCurrentUser();
    resetAllForms();
    navigateTo('home');
}

/**
 * Reset the state of the verify and enrol pages.
 * Called on sign out to prevent the previous session from leaking
 * (e.g. showing the old challenge code or the recorded audio).
 */
function resetAllForms() {
    // === Reset verify page ===
    const verifyUserIdEl = document.getElementById('verify-user-id');
    if (verifyUserIdEl) verifyUserIdEl.value = '';

    // Hide challenge display and record step (shown only after "Get my code")
    const challengeCard = document.getElementById('challenge-card');
    if (challengeCard) challengeCard.style.display = 'none';

    const verifyRecordCard = document.getElementById('verify-record-card');
    if (verifyRecordCard) verifyRecordCard.style.display = 'none';

    const verifySubmitBtn = document.getElementById('verify-submit-btn');
    if (verifySubmitBtn) {
        verifySubmitBtn.style.display = 'none';
        verifySubmitBtn.disabled = true;
        verifySubmitBtn.innerHTML = 'Sign me in';
    }

    // Reset "Get my code" button to its initial state.
    // Also clear the flag that tracks whether a challenge was ever requested,
    // so the next fresh sign-in shows "Get my code" not "Get new code".
    const challengeBtn = document.getElementById('get-challenge-btn');
    if (challengeBtn) {
        challengeBtn.disabled = false;
        challengeBtn.innerHTML = 'Get my code';
    }
    challengeWasRequested = false;

    // Reset challenge display
    const challengeDigits = document.getElementById('challenge-digits');
    if (challengeDigits) {
        challengeDigits.textContent = '';
        challengeDigits.style.color = 'var(--accent)';
    }

    // Reset recording UI
    resetRecordingUI('verify');

    // Reset step indicators
    const v1 = document.getElementById('verify-step-1');
    const v2 = document.getElementById('verify-step-2');
    const v3 = document.getElementById('verify-step-3');
    if (v1) v1.className = 'step-dot active';
    if (v2) v2.className = 'step-dot';
    if (v3) v3.className = 'step-dot';

    // Hide any result from the last session
    hideResult('verify');

    // Clear the challenge countdown interval and the recorded blob
    if (challengeInterval) clearInterval(challengeInterval);
    verifyBlob = null;

    // === Reset enrol page ===
    const enrolUserIdEl = document.getElementById('enrol-user-id');
    if (enrolUserIdEl) enrolUserIdEl.value = '';

    const enrolSubmitBtn = document.getElementById('enrol-submit-btn');
    if (enrolSubmitBtn) {
        enrolSubmitBtn.disabled = true;
        enrolSubmitBtn.innerHTML = 'Register my voice';
    }

    const gotoVerifyBtn = document.getElementById('goto-verify-btn');
    if (gotoVerifyBtn) gotoVerifyBtn.style.display = 'none';

    resetRecordingUI('enrol');

    const e1 = document.getElementById('enrol-step-1');
    const e2 = document.getElementById('enrol-step-2');
    if (e1) e1.className = 'step-dot active';
    if (e2) e2.className = 'step-dot';

    hideResult('enrol');

    enrolBlob = null;
}

/**
 * Reset the recording UI for a given target (enrol or verify).
 * Stops the timer, clears the label, removes the recording animation.
 */
function resetRecordingUI(target) {
    const recordBtn = document.getElementById(target + '-record-btn');
    if (recordBtn) recordBtn.classList.remove('recording');

    const timerEl = document.getElementById(target + '-timer');
    if (timerEl) {
        timerEl.classList.remove('visible', 'active');
        timerEl.textContent = '00:00';
    }

    const labelEl = document.getElementById(target + '-record-label');
    if (labelEl) {
        if (target === 'enrol') {
            labelEl.textContent = 'Tap the button and speak for 3-10 seconds';
        } else if (target === 'improve') {
            labelEl.textContent = 'Tap and speak to add another sample';
        } else {
            labelEl.textContent = 'Tap to start recording';
        }
    }

    // Stop any ongoing recording
    if (isRecording) {
        isRecording = false;
        if (timerInterval) clearInterval(timerInterval);
        if (mediaStream) mediaStream.getTracks().forEach(t => t.stop());
        if (audioContext) audioContext.close();
    }
}

/**
 * Navigate to the Delete Account page.
 * The username field is auto-filled and readonly, so only the
 * currently signed-in user can be deleted.
 */
function goToDeleteAccount() {
    closeProfileDropdown();
    const user = getCurrentUser();
    if (!user) return;

    // Auto-fill the username field (it's readonly on the page)
    const input = document.getElementById('delete-user-id');
    if (input) input.value = user;

    navigateTo('delete');
}

/**
 * Navigate to the Improve Voice Recognition page.
 * Fetches the current sample count for the signed-in user so the
 * UI can show "X of Y samples" and disable recording if limit is reached.
 */
async function goToImproveVoice() {
    closeProfileDropdown();
    const user = getCurrentUser();
    if (!user) return;

    // Fill the username field (readonly)
    const input = document.getElementById('improve-user-id');
    if (input) input.value = user;

    // Reset any previous recording state on the improve page
    resetRecordingUI('improve');
    hideResult('improve');
    const submitBtn = document.getElementById('improve-submit-btn');
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = 'Add voice sample';
    }
    improveBlob = null;

    // Show loading placeholder in the counter while we fetch from the server
    const counterEl = document.getElementById('improve-counter');
    if (counterEl) counterEl.textContent = 'Loading...';

    navigateTo('improve');

    // Fetch current sample count so we can show accurate progress
    try {
        const res = await fetch(API_BASE + '/enrol/check/' + encodeURIComponent(user), { headers: authHeaders() });
        if (res.ok) {
            const data = await res.json();
            updateImproveCounter(data.num_samples, data.max_samples);
        }
    } catch (err) {
        // Silent fail - page still usable, just won't show accurate count
        if (counterEl) counterEl.textContent = '';
    }
}

/**
 * Close the dropdown when clicking anywhere outside of it.
 */
document.addEventListener('click', (e) => {
    const menu = document.getElementById('profile-menu');
    if (menu && !menu.contains(e.target)) {
        closeProfileDropdown();
    }
});

/**
 * Initialize auth UI when the page loads.
 * If sessionStorage has a username, show the profile menu.
 */
document.addEventListener('DOMContentLoaded', updateAuthUI);


// ==================== OAuth register-redirect handler ====================
// When the OAuth /authorize page sends a user here to create an account,
// it includes the original /authorize URL as a single `oauth_return` query
// parameter. We detect it on page load, validate it (same-origin + path
// whitelist to block open-redirect attacks), look up the integrator name
// from a public backend endpoint, show a banner, and auto-switch to the
// Register page so the user starts in the right place.
//
// After successful registration, submitEnrol (in api.js) checks for the
// stored oauth_return and replaces the post-enrol button with a 'Continue
// to <integrator>' link that returns the user to /authorize.
//
// Security:
//   1. Same-origin check  — return URL must point to OUR server
//   2. Path whitelist     — must be /api/v1/authorize, nothing else
//   3. URL parsing        — malformed URLs are silently dropped
// These three together prevent attackers from using us as an open redirect.

async function detectOAuthContext() {
    const params = new URLSearchParams(window.location.search);
    const oauthReturn = params.get('oauth_return');
    if (!oauthReturn) return;

    // 1. Parse the URL (rejects malformed input)
    let url;
    try {
        url = new URL(oauthReturn);
    } catch {
        return;
    }

    // 2. Same-origin check — return URL must be on our own server
    if (url.origin !== window.location.origin) return;

    // 3. Path whitelist — only the OAuth authorize endpoint is acceptable
    if (url.pathname !== '/api/v1/authorize') return;

    // 4. client_id must be present (otherwise it isn't a real OAuth flow)
    const clientId = url.searchParams.get('client_id');
    if (!clientId) return;

    // Save the return URL for after-register redirect
    sessionStorage.setItem('oauth_return', oauthReturn);

    // Look up the integrator's human-readable name. The endpoint is
    // public (no API key required) and returns 404 for any client_id
    // that isn't a registered OAuth integrator.
    let integratorName = 'a third-party site';
    try {
        const res = await fetch('/api/v1/oauth/client-info?client_id=' +
                                encodeURIComponent(clientId));
        if (res.ok) {
            const data = await res.json();
            if (data && data.name) integratorName = data.name;
        }
    } catch {
        // Network error — keep the generic name and continue
    }

    // Save the name too so submitEnrol can use it without another fetch
    sessionStorage.setItem('oauth_integrator_name', integratorName);

    showOAuthBanner(integratorName);
    // Auto-switch to the Register page (Demo's enrol page is page-enrol)
    if (typeof navigateTo === 'function') {
        navigateTo('enrol');
    }
}

/**
 * Show the OAuth context banner on the home/enrol page.
 * Banner is integrator-agnostic — name is whatever the backend returns.
 */
function showOAuthBanner(integratorName) {
    const banner = document.getElementById('oauth-context-banner');
    if (!banner) return;

    const nameEl = document.getElementById('oauth-banner-integrator');
    if (nameEl) nameEl.textContent = integratorName;

    banner.style.display = 'flex';
}

/**
 * Cancel the OAuth flow — clear the stored return URL and hide the banner.
 * Called when user clicks the X on the banner: they decided to use Demo
 * standalone after all, not return to the integrator.
 */
function cancelOAuthRedirect() {
    sessionStorage.removeItem('oauth_return');
    sessionStorage.removeItem('oauth_integrator_name');
    const banner = document.getElementById('oauth-context-banner');
    if (banner) banner.style.display = 'none';
}

/**
 * Return to the OAuth /authorize page using the stored URL.
 * Called from the post-register success button and from the optional
 * 'go back to <integrator> sign-in' link if the user navigated to the
 * Sign-in page instead of registering.
 */
function returnToOAuth() {
    const oauthReturn = sessionStorage.getItem('oauth_return');
    if (!oauthReturn) return;
    sessionStorage.removeItem('oauth_return');
    sessionStorage.removeItem('oauth_integrator_name');
    window.location.href = oauthReturn;
}

/**
 * Helper for other pages: is there an active OAuth redirect waiting?
 * Used by api.js submitEnrol success branch.
 */
function hasOAuthRedirect() {
    return sessionStorage.getItem('oauth_return') !== null;
}

function getOAuthIntegratorName() {
    return sessionStorage.getItem('oauth_integrator_name') || 'the site';
}

// Run detection on every page load
document.addEventListener('DOMContentLoaded', detectOAuthContext);