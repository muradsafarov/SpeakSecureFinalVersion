/* ===========================================================
   SpeakSecure - Recording
   Captures microphone audio and encodes it as WAV.
   Uses Web Audio API (AudioContext + ScriptProcessor) to get
   raw PCM samples, then manually builds a WAV file blob.
   =========================================================== */

/**
 * Encode Float32 samples as a 16-bit PCM WAV file blob.
 * The WAV format header is 44 bytes, followed by the raw samples.
 */
function encodeWAV(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);

    function writeString(offset, str) {
        for (let i = 0; i < str.length; i++) {
            view.setUint8(offset + i, str.charCodeAt(i));
        }
    }

    // WAV header
    writeString(0, 'RIFF');
    view.setUint32(4, 36 + samples.length * 2, true);
    writeString(8, 'WAVE');
    writeString(12, 'fmt ');
    view.setUint32(16, 16, true);           // fmt chunk size
    view.setUint16(20, 1, true);            // PCM format
    view.setUint16(22, 1, true);            // mono
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true); // byte rate
    view.setUint16(32, 2, true);            // block align
    view.setUint16(34, 16, true);           // bits per sample
    writeString(36, 'data');
    view.setUint32(40, samples.length * 2, true);

    // Convert Float32 [-1, 1] samples to 16-bit PCM
    for (let i = 0; i < samples.length; i++) {
        let s = Math.max(-1, Math.min(1, samples[i]));
        view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }

    return new Blob([buffer], { type: 'audio/wav' });
}

// Global flag — true while a verify/enrol/improve request is in flight.
// Mirrors the setChallengeButton pattern in api.js. Inline onclick handlers
// on <button> bypass the disabled attribute, so we use this flag as the
// SOURCE OF TRUTH for whether a new recording can start.
let recordingLocked = false;

/**
 * Toggle recording state - start if idle, stop if recording.
 * Does nothing if a verify/enrol request is currently in flight.
 */
async function toggleRecording(target) {
    if (recordingLocked) return;
    isRecording ? stopRecording(target) : await startRecording(target);
}

/**
 * Lock or unlock the record button for a given target (enrol/verify/improve).
 * Same shape as setChallengeButton — single source of truth (the global flag),
 * plus a CSS class for visual feedback (greyed out + not-allowed cursor).
 */
function setRecordButton(target, locked) {
    recordingLocked = locked;
    const btn = document.getElementById(target + '-record-btn');
    if (!btn) return;
    btn.disabled = locked;
    btn.classList.toggle('locked', locked);
}

/**
 * Start capturing audio from the microphone.
 * Requests microphone access, sets up audio processing, starts timer.
 */
async function startRecording(target) {
    try {
        // Request microphone with specific constraints for speech processing
        mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                sampleRate: SAMPLE_RATE,
                channelCount: 1,
                echoCancellation: false,
                noiseSuppression: false,
                autoGainControl: false,
            }
        });

        audioContext = new AudioContext();
        const source = audioContext.createMediaStreamSource(mediaStream);

        // ScriptProcessor captures raw PCM samples in chunks
        const processor = audioContext.createScriptProcessor(4096, 1, 1);
        recordedSamples = [];
        isRecording = true;
        recordingTarget = target;

        // Collect samples as they arrive
        processor.onaudioprocess = (e) => {
            if (isRecording) {
                recordedSamples.push(new Float32Array(e.inputBuffer.getChannelData(0)));
            }
        };

        source.connect(processor);
        processor.connect(audioContext.destination);

        // Update UI - show recording state
        document.getElementById(target + '-record-btn').classList.add('recording');
        document.getElementById(target + '-record-label').textContent = 'Recording... tap to stop';

        // Start recording timer
        timerSeconds = 0;
        const timerEl = document.getElementById(target + '-timer');
        timerEl.classList.add('visible', 'active');
        timerInterval = setInterval(() => {
            timerSeconds++;
            timerEl.textContent = String(Math.floor(timerSeconds / 60)).padStart(2, '0') +
                ':' + String(timerSeconds % 60).padStart(2, '0');
        }, 1000);
    } catch (err) {
        showResult(target, 'error', 'Microphone access denied',
            'Please allow microphone access in your browser and try again.');
    }
}

/**
 * Stop capturing audio and produce a WAV blob.
 * Merges all captured sample chunks, encodes as WAV, stores blob.
 */
function stopRecording(target) {
    isRecording = false;
    clearInterval(timerInterval);

    // Merge all sample chunks into a single Float32Array
    let totalLength = 0;
    for (const chunk of recordedSamples) totalLength += chunk.length;
    const merged = new Float32Array(totalLength);
    let offset = 0;
    for (const chunk of recordedSamples) {
        merged.set(chunk, offset);
        offset += chunk.length;
    }

    // Encode merged samples as a WAV blob
    const wavBlob = encodeWAV(merged, audioContext.sampleRate);

    // Store the blob for the correct target (enrol, verify, or improve)
    // and update the step indicator.
    if (target === 'enrol') {
        enrolBlob = wavBlob;
        document.getElementById('enrol-submit-btn').disabled = false;
        document.getElementById('enrol-record-label').textContent = 'Recording saved, ready to register';
        document.getElementById('enrol-step-1').className = 'step-dot done';
        document.getElementById('enrol-step-2').className = 'step-dot active';
    } else if (target === 'verify') {
        verifyBlob = wavBlob;
        document.getElementById('verify-submit-btn').disabled = false;
        document.getElementById('verify-record-label').textContent = 'Recording saved, ready to sign in';
        document.getElementById('verify-step-2').className = 'step-dot done';
        document.getElementById('verify-step-3').className = 'step-dot active';
    } else if (target === 'improve') {
        improveBlob = wavBlob;
        document.getElementById('improve-submit-btn').disabled = false;
        document.getElementById('improve-record-label').textContent = 'Recording saved, ready to add';
    }

    // Remove pulsing animation from mic button AND active state from timer,
    // so both visually return to the "idle" grey state.
    document.getElementById(target + '-record-btn').classList.remove('recording');
    const timerEl = document.getElementById(target + '-timer');
    if (timerEl) timerEl.classList.remove('active');

    if (mediaStream) mediaStream.getTracks().forEach(t => t.stop());
    if (audioContext) audioContext.close();
    audioContext = null;
    mediaStream = null;
}