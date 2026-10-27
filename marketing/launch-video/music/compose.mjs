// Composes the launch video's soundtrack and sound cues from scratch: no samples, no
// licences. 100 BPM, so one bar is 2.4 s, exactly 72 frames at 30 fps, and scene cuts
// land on bar lines.
//
//   node music/compose.mjs   → public/music.wav, public/sfx-*.wav

import {mkdirSync, writeFileSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', 'public');
const SR = 44100;
const BPM = 100;
const BEAT = 60 / BPM;
const BAR = BEAT * 4;
const STEP = BEAT / 4;
export const BARS = 28;
const TAIL = 3;
const N = Math.ceil((BARS * BAR + TAIL) * SR);

const midi = (n) => 440 * Math.pow(2, (n - 69) / 12);
const at = (t) => Math.floor(t * SR);

// Am9 · Fmaj7 · C(add9) · G6, then F · G · C to resolve at the end.
const AM = {root: 45, notes: [57, 60, 64, 67, 71]};
const F = {root: 41, notes: [53, 57, 60, 64]};
const C = {root: 48, notes: [55, 60, 62, 64]};
const G = {root: 43, notes: [55, 59, 62, 64]};
const LOOP = [AM, F, C, G];
const chordFor = (bar) => (bar >= 25 ? [F, G, C][bar - 25] : LOOP[bar % 4]);

// Sections: 0-2 intro (tension), 3-4 title (impact), 5-24 groove, 25-27 outro.
const groove = (bar) => bar >= 5 && bar < 25;

// -- buffers ---------------------------------------------------------------------------------
const buf = () => new Float32Array(N);
const padL = buf(), padR = buf(), bass = buf();
const drumL = buf(), drumR = buf(), pluckL = buf(), pluckR = buf();
const revIn = buf(), dlyIn = buf();
const duck = new Float32Array(N).fill(1);

// -- building blocks -------------------------------------------------------------------------
function blep(t, dt) {
	if (t < dt) {
		t /= dt;
		return t + t - t * t - 1;
	}
	if (t > 1 - dt) {
		t = (t - 1) / dt;
		return t * t + t + t + 1;
	}
	return 0;
}

function biquad(type, freq, q) {
	const w = (2 * Math.PI * freq) / SR, cos = Math.cos(w), alpha = Math.sin(w) / (2 * q);
	let b0, b1, b2;
	if (type === 'lp') [b0, b1, b2] = [(1 - cos) / 2, 1 - cos, (1 - cos) / 2];
	else if (type === 'hp') [b0, b1, b2] = [(1 + cos) / 2, -(1 + cos), (1 + cos) / 2];
	else [b0, b1, b2] = [alpha, 0, -alpha]; // band-pass
	const a0 = 1 + alpha, a1 = -2 * cos, a2 = 1 - alpha;
	let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
	return (x) => {
		const y = (b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2) / a0;
		x2 = x1; x1 = x; y2 = y1; y1 = y;
		return y;
	};
}

let seed = 7;
const noise = () => {
	seed = (seed * 1664525 + 1013904223) >>> 0;
	return seed / 2147483648 - 1;
};

// -- instruments -----------------------------------------------------------------------------
function padNote(start, length, note, gain, cutoff) {
	const detunes = [-0.07, 0, 0.07];
	const pans = [0.25, 0.5, 0.75];
	const a = 1 - Math.exp((-2 * Math.PI * cutoff) / SR);
	const phase = detunes.map(() => (noise() + 1) / 2);
	const s1 = [0, 0, 0], s2 = [0, 0, 0];
	const attack = 0.5, release = 1.2;
	for (let i = at(start), end = Math.min(N, at(start + length + release)); i < end; i++) {
		const t = i / SR - start;
		const env = Math.min(1, t / attack) * (t > length ? Math.exp(-(t - length) / (release / 3)) : 1);
		for (let v = 0; v < 3; v++) {
			const f = midi(note + detunes[v]);
			const dt = f / SR;
			phase[v] += dt;
			if (phase[v] >= 1) phase[v] -= 1;
			let x = 2 * phase[v] - 1 - blep(phase[v], dt);
			s1[v] += a * (x - s1[v]);
			s2[v] += a * (s1[v] - s2[v]);
			x = s2[v] * env * gain;
			padL[i] += x * (1 - pans[v]);
			padR[i] += x * pans[v];
			revIn[i] += x * 0.35;
		}
	}
}

function bassNote(start, length, note, gain) {
	const f = midi(note);
	const lp = biquad('lp', 380, 0.7);
	let ph = 0;
	for (let i = at(start), end = Math.min(N, at(start + length + 0.05)); i < end; i++) {
		const t = i / SR - start;
		ph += f / SR;
		const tri = 4 * Math.abs((ph % 1) - 0.5) - 1;
		const env = Math.min(1, t / 0.006) * Math.exp(-t * 2.2) * (t > length ? Math.exp(-(t - length) * 60) : 1);
		bass[i] += lp(Math.sin(2 * Math.PI * ph) * 0.8 + tri * 0.35) * env * gain;
	}
}

function kick(start, gain) {
	let ph = 0;
	for (let i = at(start), end = Math.min(N, at(start + 0.45)); i < end; i++) {
		const t = i / SR - start;
		ph += (46 + 95 * Math.exp(-t * 32)) / SR;
		const x = (Math.sin(2 * Math.PI * ph) * Math.exp(-t * 7) + noise() * Math.exp(-t * 400) * 0.25) * gain;
		drumL[i] += x;
		drumR[i] += x;
		duck[i] = Math.min(duck[i], 1 - 0.5 * Math.exp(-t * 9));
	}
}

function clap(start, gain) {
	const bp = biquad('bp', 1400, 0.8);
	for (let i = at(start), end = Math.min(N, at(start + 0.35)); i < end; i++) {
		const t = i / SR - start;
		const bursts = [0, 0.011, 0.022].reduce((sum, o) => sum + (t >= o ? Math.exp(-(t - o) * 260) : 0), 0);
		const x = bp(noise()) * (bursts * 0.6 + Math.exp(-t * 14) * 0.5) * gain;
		drumL[i] += x * 0.9;
		drumR[i] += x;
		revIn[i] += x * 0.4;
	}
}

function hat(start, gain, pan = 0.6) {
	const hp = biquad('hp', 7000, 0.7);
	for (let i = at(start), end = Math.min(N, at(start + 0.08)); i < end; i++) {
		const t = i / SR - start;
		const x = hp(noise()) * Math.exp(-t * 70) * gain;
		drumL[i] += x * (1 - pan);
		drumR[i] += x * pan;
	}
}

function pluck(start, note, gain, pan) {
	const f = midi(note);
	let ph = (noise() + 1) / 2, s1 = 0, s2 = 0;
	for (let i = at(start), end = Math.min(N, at(start + 0.5)); i < end; i++) {
		const t = i / SR - start;
		const dt = f / SR;
		ph += dt;
		if (ph >= 1) ph -= 1;
		const a = 1 - Math.exp((-2 * Math.PI * (900 + 6500 * Math.exp(-t * 14))) / SR);
		s1 += a * (2 * ph - 1 - blep(ph, dt) - s1);
		s2 += a * (s1 - s2);
		const x = s2 * Math.exp(-t * 8) * Math.min(1, t / 0.003) * gain;
		pluckL[i] += x * (1 - pan);
		pluckR[i] += x * pan;
		dlyIn[i] += x * 0.5;
		revIn[i] += x * 0.25;
	}
}

function swell(start, length, gain) {
	let lp = 0;
	for (let i = at(start), end = Math.min(N, at(start + length)); i < end; i++) {
		const p = (i / SR - start) / length;
		const a = 1 - Math.exp((-2 * Math.PI * (300 + 6000 * p * p)) / SR);
		lp += a * (noise() - lp);
		const x = lp * p * p * gain;
		drumL[i] += x;
		drumR[i] += x;
		revIn[i] += x * 0.5;
	}
}

function boom(start, gain) {
	let ph = 0;
	for (let i = at(start), end = Math.min(N, at(start + 2.2)); i < end; i++) {
		const t = i / SR - start;
		ph += (38 + 30 * Math.exp(-t * 10)) / SR;
		const x = Math.sin(2 * Math.PI * ph) * Math.exp(-t * 2.2) * gain;
		drumL[i] += x;
		drumR[i] += x;
		revIn[i] += noise() * Math.exp(-t * 3) * gain * 0.08;
	}
}

// -- the arrangement -------------------------------------------------------------------------
const ARP = [0, 2, 1, 3, 2, 4, 1, 3, 0, 2, 3, 1, 4, 2, 3, 1];

for (let bar = 0; bar < BARS; bar++) {
	const t0 = bar * BAR;
	const chord = chordFor(bar);
	const intro = bar < 3;
	const outro = bar >= 25;
	const cutoff = intro ? 900 + bar * 400 : outro ? 2200 : 3600;
	const padGain = intro ? 0.055 : 0.08;
	const last = bar === BARS - 1;
	for (const n of chord.notes) padNote(t0, last ? BAR + 1.5 : BAR, n, padGain, cutoff);

	if (intro) {
		for (let s = 0; s < 16; s++) hat(t0 + s * STEP, s % 4 === 2 ? 0.09 : 0.045, 0.65);
		bassNote(t0, BEAT * 2, chord.root, 0.22);
		if (bar === 2) swell(t0 + BAR / 2, BAR / 2, 0.22);
	}
	if (bar === 3) boom(t0, 0.55);
	if (bar === 3 || bar === 4) {
		kick(t0, 0.55);
		bassNote(t0, BAR, chord.root, 0.26);
		for (let s = 0; s < 16; s += 2) pluck(t0 + s * STEP, chord.notes[ARP[s] % chord.notes.length] + 12, 0.05, s % 4 ? 0.3 : 0.7);
	}
	if (groove(bar)) {
		const full = bar >= 7;
		for (let b = 0; b < 4; b++) kick(t0 + b * BEAT, 0.45);
		if (full) for (const b of [1, 3]) clap(t0 + b * BEAT, 0.42);
		for (let e = 0; e < 8; e++) hat(t0 + e * 2 * STEP, e % 2 ? 0.26 : 0.12);
		if (full) for (let s = 1; s < 16; s += 2) hat(t0 + s * STEP, 0.07, 0.35);
		for (let e = 0; e < 8; e++) bassNote(t0 + e * 2 * STEP, STEP * 1.6, chord.root + (e === 6 ? 12 : 0), 0.22);
		const step = full ? 1 : 2;
		for (let s = 0; s < 16; s += step) {
			const note = chord.notes[ARP[s] % chord.notes.length] + 12;
			pluck(t0 + s * STEP, note, full ? 0.1 : 0.08, s % 2 ? 0.3 : 0.7);
		}
	}
	if (outro) {
		for (let s = 0; s < 16; s += 2) pluck(t0 + s * STEP, chord.notes[ARP[s] % chord.notes.length] + 12, 0.045 * (1 - (bar - 25) * 0.25), s % 4 ? 0.3 : 0.7);
		if (bar === 25) kick(t0, 0.6);
		bassNote(t0, BAR, chord.root, 0.25);
	}
}

// -- effects ---------------------------------------------------------------------------------
function pingPong(input, time, feedback) {
	const d = at(time), outL = buf(), outR = buf();
	const lp = biquad('lp', 3500, 0.7);
	for (let i = 0; i < N; i++) {
		const fromR = i >= d ? outR[i - d] : 0;
		const fromL = i >= d ? outL[i - d] : 0;
		outL[i] = lp(input[i] + fromR * feedback);
		outR[i] = fromL * 0.95;
	}
	return [outL, outR];
}

function reverb(input) {
	const combs = [1116, 1188, 1277, 1356, 1422, 1491];
	const outL = buf(), outR = buf();
	for (const [channel, offset] of [[outL, 0], [outR, 23]]) {
		for (const size of combs) {
			const len = size + offset, line = new Float32Array(len);
			let idx = 0, store = 0;
			for (let i = 0; i < N; i++) {
				const y = line[idx];
				store = y * 0.75 + store * 0.25;
				line[idx] = input[i] + store * 0.83;
				idx = (idx + 1) % len;
				channel[i] += y / combs.length;
			}
		}
		for (const size of [556, 441]) {
			const len = size + offset, line = new Float32Array(len);
			let idx = 0;
			for (let i = 0; i < N; i++) {
				const b = line[idx], x = channel[i];
				line[idx] = x + b * 0.5;
				channel[i] = b - x * 0.5;
				idx = (idx + 1) % len;
			}
		}
	}
	return [outL, outR];
}

const [dL, dR] = pingPong(dlyIn, STEP * 3, 0.38);
const [rL, rR] = reverb(revIn);

// -- mix and master --------------------------------------------------------------------------
const L = buf(), R = buf();
// A high shelf (about +6 dB above 3 kHz) keeps the mix clear on laptop and phone speakers.
const shelfL = biquad('hp', 3000, 0.7), shelfR = biquad('hp', 3000, 0.7);
for (let i = 0; i < N; i++) {
	const d = duck[i];
	const l = (padL[i] + bass[i]) * d + drumL[i] + pluckL[i] + dL[i] * 0.55 + rL[i] * 0.9;
	const r = (padR[i] + bass[i]) * d + drumR[i] + pluckR[i] + dR[i] * 0.55 + rR[i] * 0.9;
	L[i] = l + shelfL(l);
	R[i] = r + shelfR(r);
}
master(L, R, 2.8);
writeWav(join(OUT, 'music.wav'), L, R);

// -- sound cues ------------------------------------------------------------------------------
function cue(name, seconds, render) {
	const n = Math.ceil(seconds * SR), l = new Float32Array(n), r = new Float32Array(n);
	render(l, r, n);
	master(l, r, 0.05);
	writeWav(join(OUT, `sfx-${name}.wav`), l, r, 0.5);
}

cue('tick', 0.12, (l, r, n) => {
	for (let i = 0; i < n; i++) {
		const t = i / SR, x = (Math.sin(2 * Math.PI * 2100 * t) + 0.4 * Math.sin(2 * Math.PI * 3150 * t)) * Math.exp(-t * 60);
		l[i] = x;
		r[i] = x;
	}
});
cue('pass', 0.9, (l, r, n) => {
	for (const [start, note] of [[0, 88], [0.09, 93]]) {
		for (let i = at(start); i < n; i++) {
			const t = i / SR - start, x = Math.sin(2 * Math.PI * midi(note) * t) * Math.exp(-t * 5) * Math.min(1, t / 0.004);
			l[i] += x * 0.6;
			r[i] += x * 0.6;
		}
	}
});
cue('fail', 0.6, (l, r, n) => {
	let ph = 0;
	const lp = biquad('lp', 900, 0.7);
	for (let i = 0; i < n; i++) {
		const t = i / SR;
		ph += (150 - 60 * Math.min(1, t * 4)) / SR;
		const x = (Math.sin(2 * Math.PI * ph) * Math.exp(-t * 7) + lp(noise()) * Math.exp(-t * 40) * 0.6) * 0.9;
		l[i] = x;
		r[i] = x;
	}
});
cue('whoosh', 0.7, (l, r, n) => {
	let lp = 0;
	for (let i = 0; i < n; i++) {
		const p = i / n, a = 1 - Math.exp((-2 * Math.PI * (400 + 5000 * Math.sin(Math.PI * p))) / SR);
		lp += a * (noise() - lp);
		const x = lp * Math.sin(Math.PI * p) ** 2;
		l[i] = x * (1 - p);
		r[i] = x * p;
	}
});

// -- helpers ---------------------------------------------------------------------------------
function master(L, R, fadeOut) {
	let peak = 0;
	for (let i = 0; i < L.length; i++) {
		L[i] = Math.tanh(L[i] * 1.3) / Math.tanh(1.3);
		R[i] = Math.tanh(R[i] * 1.3) / Math.tanh(1.3);
		peak = Math.max(peak, Math.abs(L[i]), Math.abs(R[i]));
	}
	const gain = 0.89 / (peak || 1), fade = at(fadeOut);
	for (let i = 0; i < L.length; i++) {
		const tail = L.length - i;
		const g = gain * Math.min(1, i / at(0.02)) * (tail < fade ? tail / fade : 1);
		L[i] *= g;
		R[i] *= g;
	}
}

function writeWav(path, L, R, level = 1) {
	const n = L.length, data = Buffer.alloc(44 + n * 4);
	data.write('RIFF', 0);
	data.writeUInt32LE(36 + n * 4, 4);
	data.write('WAVEfmt ', 8);
	data.writeUInt32LE(16, 16);
	data.writeUInt16LE(1, 20);
	data.writeUInt16LE(2, 22);
	data.writeUInt32LE(SR, 24);
	data.writeUInt32LE(SR * 4, 28);
	data.writeUInt16LE(4, 32);
	data.writeUInt16LE(16, 34);
	data.write('data', 36);
	data.writeUInt32LE(n * 4, 40);
	for (let i = 0; i < n; i++) {
		data.writeInt16LE(Math.round(Math.max(-1, Math.min(1, L[i] * level)) * 32767), 44 + i * 4);
		data.writeInt16LE(Math.round(Math.max(-1, Math.min(1, R[i] * level)) * 32767), 46 + i * 4);
	}
	mkdirSync(dirname(path), {recursive: true});
	writeFileSync(path, data);
	console.log(`${path} ${(n / SR).toFixed(1)}s`);
}
