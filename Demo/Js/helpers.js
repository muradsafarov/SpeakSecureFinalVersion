/* ===========================================================
   SpeakSecure - UI Helpers
   Utility functions for showing results, building detailed
   verification reports, and translating backend errors into
   friendly English.
   =========================================================== */

/**
 * Show a result message box (success, error, or warning).
 * Used across all pages (enrol, verify, delete).
 */
function showResult(target, type, title, details) {
    const el = document.getElementById(target + '-result');
    el.className = 'result visible ' + type;
    el.innerHTML = '<div class="result-header">' + title + '</div>' +
                   '<div class="result-details">' + details + '</div>';
}

/**
 * Hide a previously-shown result message.
 */
function hideResult(target) {
    document.getElementById(target + '-result').className = 'result';
}

/**
 * Build a detailed verification result showing all backend fields
 * translated into user-friendly labels.
 *
 * Backend returns technical fields like `similarity_score`, `spoof_label`,
 * `challenge_passed`, etc. This function displays them as a readable table
 * with human-friendly labels and values.
 */
function buildVerifyDetails(summary, data) {
    // Translate backend decision into a friendly label
    const decisionMap = {
        'accepted': 'Accepted',
        'rejected': 'Rejected',
        'retry': 'Try again',
    };
    const decisionLabel = decisionMap[data.decision] || data.decision;

    // Translate spoof label (bonafide = real voice in AASIST terminology)
    const spoofLabel = data.spoof_label === 'bonafide' ? 'Real voice' : 'Possibly fake';

    // Build the table rows, showing only fields that make sense for this case
    let rows = '';

    rows += row('Username', data.user_id);
    rows += row('Result', decisionLabel);

    // Voice match % is only meaningful if spoof check passed and challenge passed
    if (!data.spoof_detected && data.challenge_passed) {
        const pct = (data.similarity_score * 100).toFixed(0);
        rows += row('Voice match', pct + '%');
    }

    // Spoken digits are shown whenever the backend reported them
    if (data.recognized_digits !== undefined && data.recognized_digits !== null) {
        const heard = data.recognized_digits || '(nothing heard)';
        rows += row('Numbers heard', heard);
    }

    rows += row('Code check', data.challenge_passed ? 'Passed' : 'Failed');
    rows += row('Voice check', spoofLabel);
    rows += row('Tries left', data.remaining_attempts);

    return '<p style="margin-bottom: 14px;">' + summary + '</p>' +
           '<div class="result-table">' + rows + '</div>';
}

/**
 * Build a single row of the result table (label on left, value on right).
 */
function row(label, value) {
    return '<div class="result-row">' +
           '<span class="result-row-label">' + label + '</span>' +
           '<span class="result-row-value">' + value + '</span>' +
           '</div>';
}

/**
 * Translate a raw backend error message into a friendly user-facing message.
 * Handles common error patterns by keyword matching.
 * If nothing matches, strips technical terms from the raw message.
 */
function friendlyError(raw) {
    const msg = (raw || '').toLowerCase();

    if (msg.includes('too many failed') || msg.includes('temporarily locked') || msg.includes('rate limit')) {
        // Extract the seconds number if present
        const match = raw.match(/(\d+)\s*seconds?/i);
        if (match) {
            return 'Too many failed attempts. Your account is temporarily locked. ' +
                   'Please try again in ' + match[1] + ' seconds.';
        }
        return 'Too many failed attempts. Your account is temporarily locked. Please wait and try again.';
    }
    if (msg.includes('spoofed') || msg.includes('spoofing')) {
        return "The recording doesn't sound like a real person speaking.";
    }
    if (msg.includes('no active challenge')) {
        return 'Your code expired. Please get a new code.';
    }
    if (msg.includes("doesn't match the enrolled") || msg.includes("doesn't match")) {
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

    // Fallback: strip technical terminology from raw message
    return raw
        .replace(/embedding/gi, 'voice profile')
        .replace(/cosine similarity/gi, 'voice match')
        .replace(/threshold/gi, 'minimum')
        .replace(/AASIST/gi, 'voice check');
}