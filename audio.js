// audio.js (CHILD-3, part 2) — Web Audio synth. Import-safe in Node.
// Every export no-ops safely when AudioContext is unavailable (Node).
// Lazy AudioContext creation; resumeAudio() for the gesture unlock;
// setMuted toggles a master gain. NEVER throws in Node.

let ctx = null;        // AudioContext
let master = null;     // master GainNode
let muted = false;
let noiseBuffer = null; // shared noise buffer for explosion

function hasAudio() {
  return !(typeof AudioContext === 'undefined' && typeof webkitAudioContext === 'undefined');
}

function getCtxClass() {
  if (typeof AudioContext !== 'undefined') return AudioContext;
  if (typeof webkitAudioContext !== 'undefined') return webkitAudioContext;
  return null;
}

export function initAudio() {
  if (!hasAudio()) return;
  if (ctx) return;
  try {
    const Ctor = getCtxClass();
    if (!Ctor) return;
    ctx = new Ctor();
    master = ctx.createGain();
    master.gain.value = muted ? 0 : 0.5;
    master.connect(ctx.destination);
    // build a short white-noise buffer for the explosion
    const len = Math.floor(ctx.sampleRate * 0.5);
    noiseBuffer = ctx.createBuffer(1, len, ctx.sampleRate);
    const data = noiseBuffer.getChannelData(0);
    for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1;
  } catch (e) {
    ctx = null;
    master = null;
  }
}

export function resumeAudio() {
  if (!hasAudio()) return;
  try {
    if (!ctx) initAudio();
    if (ctx && ctx.state === 'suspended' && typeof ctx.resume === 'function') {
      ctx.resume();
    }
  } catch (e) {
    /* no-op */
  }
}

export function setMuted(m) {
  muted = !!m;
  if (!hasAudio()) return;
  try {
    if (master && ctx) {
      master.gain.setValueAtTime(muted ? 0 : 0.5, ctx.currentTime);
    }
  } catch (e) {
    /* no-op */
  }
}

// --- tone synthesis helpers ------------------------------------------------
function tone(opts) {
  // opts: { type, freq, freqEnd, dur, peak, delay, dest }
  const t0 = ctx.currentTime + (opts.delay || 0);
  const osc = ctx.createOscillator();
  const g = ctx.createGain();
  osc.type = opts.type || 'sine';
  osc.frequency.setValueAtTime(opts.freq, t0);
  if (opts.freqEnd != null) {
    osc.frequency.exponentialRampToValueAtTime(Math.max(1, opts.freqEnd), t0 + opts.dur);
  }
  const peak = opts.peak == null ? 0.3 : opts.peak;
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.exponentialRampToValueAtTime(peak, t0 + 0.01);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + opts.dur);
  osc.connect(g);
  g.connect(opts.dest || master);
  osc.start(t0);
  osc.stop(t0 + opts.dur + 0.02);
}

function noiseBurst(dur, peak, freq) {
  const t0 = ctx.currentTime;
  const src = ctx.createBufferSource();
  src.buffer = noiseBuffer;
  const g = ctx.createGain();
  const lp = ctx.createBiquadFilter();
  lp.type = 'lowpass';
  lp.frequency.setValueAtTime(freq || 1200, t0);
  lp.frequency.exponentialRampToValueAtTime(200, t0 + dur);
  g.gain.setValueAtTime(peak, t0);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  src.connect(lp);
  lp.connect(g);
  g.connect(master);
  src.start(t0);
  src.stop(t0 + dur + 0.02);
}

export function playSound(name) {
  if (!hasAudio()) return;
  try {
    if (!ctx) initAudio();
    if (!ctx || !master || muted) return;
    switch (name) {
      case 'shoot':
        tone({ type: 'square', freq: 720, freqEnd: 220, dur: 0.1, peak: 0.18 });
        break;
      case 'hit':
        tone({ type: 'triangle', freq: 320, freqEnd: 160, dur: 0.08, peak: 0.2 });
        break;
      case 'explosion':
        noiseBurst(0.45, 0.5, 1600);
        tone({ type: 'sawtooth', freq: 120, freqEnd: 40, dur: 0.4, peak: 0.25 });
        break;
      case 'waveStart':
        tone({ type: 'sine', freq: 440, dur: 0.16, peak: 0.25 });
        tone({ type: 'sine', freq: 660, dur: 0.18, peak: 0.25, delay: 0.14 });
        tone({ type: 'sine', freq: 880, dur: 0.22, peak: 0.25, delay: 0.3 });
        break;
      case 'playerHurt':
        tone({ type: 'sawtooth', freq: 300, freqEnd: 90, dur: 0.25, peak: 0.3 });
        break;
      case 'gameOver':
        tone({ type: 'sawtooth', freq: 440, freqEnd: 220, dur: 0.3, peak: 0.3 });
        tone({ type: 'sawtooth', freq: 330, freqEnd: 110, dur: 0.4, peak: 0.3, delay: 0.28 });
        tone({ type: 'sawtooth', freq: 220, freqEnd: 55, dur: 0.6, peak: 0.3, delay: 0.6 });
        break;
      case 'pickup':
        tone({ type: 'sine', freq: 660, dur: 0.1, peak: 0.25 });
        tone({ type: 'sine', freq: 990, dur: 0.12, peak: 0.25, delay: 0.09 });
        break;
      case 'upgrade':
        tone({ type: 'triangle', freq: 523, dur: 0.12, peak: 0.25 });
        tone({ type: 'triangle', freq: 659, dur: 0.12, peak: 0.25, delay: 0.1 });
        tone({ type: 'triangle', freq: 784, dur: 0.16, peak: 0.25, delay: 0.2 });
        break;
      default:
        /* unknown name: no-op */
        break;
    }
  } catch (e) {
    /* never throw */
  }
}
