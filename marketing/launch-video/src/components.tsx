import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame} from 'remotion';
import {PRODUCT, color, mono, sans} from './theme';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const easeOut = Easing.bezier(0.16, 1, 0.3, 1);

/** 0 → 1 over a few frames from `start`, eased out. */
export const useReveal = (start: number, duration = 9) => {
	const frame = useCurrentFrame();
	return interpolate(frame, [start, start + duration], [0, 1], {...clamp, easing: easeOut});
};

export const Page: React.FC<{children: React.ReactNode; tone?: 'white' | 'subtle'}> = ({children, tone = 'white'}) => (
	<AbsoluteFill style={{background: tone === 'white' ? color.page : color.subtle, color: color.text, fontFamily: sans}}>
		{children}
	</AbsoluteFill>
);

/** Fades and lifts its children in at `at`. */
export const Reveal: React.FC<{at: number; children: React.ReactNode; style?: React.CSSProperties; distance?: number}> = ({
	at,
	children,
	style,
	distance = 16,
}) => {
	const t = useReveal(at);
	return <div style={{...style, opacity: t, translate: `0 ${(1 - t) * distance}px`}}>{children}</div>;
};

/** The step label at the top of a scene, set like the website's numbered steps. */
export const Kicker: React.FC<{step?: string; text: string}> = ({step, text}) => (
	<Reveal at={0} style={{position: 'absolute', top: 84, left: 120, right: 120}}>
		{step ? <div style={{fontFamily: mono, fontSize: 30, color: color.faint}}>{step}</div> : null}
		<div style={{fontSize: 68, fontWeight: 600, lineHeight: 1.1, marginTop: step ? 10 : 0, textWrap: 'balance'}}>{text}</div>
	</Reveal>
);

/** Burned-in caption: most people watch launch videos muted. */
export const Caption: React.FC<{text: string; at?: number}> = ({text, at = 8}) => (
	<Reveal at={at} distance={8} style={{position: 'absolute', left: 0, right: 0, bottom: 56, display: 'flex', justifyContent: 'center'}}>
		<div
			style={{
				maxWidth: 1600,
				padding: '14px 30px',
				borderRadius: 14,
				background: color.term,
				color: '#fafafa',
				fontSize: 36,
				fontWeight: 500,
				lineHeight: 1.3,
				textAlign: 'center',
			}}
		>
			{text}
		</div>
	</Reveal>
);

export type Tone = 'plain' | 'dim' | 'pass' | 'fail' | 'warn' | 'cmd';
const tones: Record<Tone, string> = {
	plain: color.termText,
	dim: color.termDim,
	pass: color.passOnDark,
	fail: color.failOnDark,
	warn: color.warnOnDark,
	cmd: '#ffffff',
};

/** How a line of Contexer's real output is coloured, the way the terminal shows it. */
export const toneOf = (text: string): Tone => {
	const t = text.trim();
	if (t.startsWith('$')) return 'cmd';
	if (t.startsWith('✓')) return 'pass';
	if (t.startsWith('✗')) return 'fail';
	if (t.startsWith('?') || t.startsWith('!')) return 'warn';
	if (t.startsWith('›')) return 'cmd';
	if (/^(glob|read|edit|write|bash|OpenCode session|Attempt \d+: proving)\b/.test(t)) return 'dim';
	return 'plain';
};

export const Terminal: React.FC<{
	title: string;
	width: number;
	height?: number;
	fontSize?: number;
	children: React.ReactNode;
	style?: React.CSSProperties;
}> = ({title, width, height, fontSize = 26, children, style}) => (
	<div
		style={{
			width,
			height,
			borderRadius: 18,
			background: color.term,
			border: `1px solid ${color.termBorder}`,
			overflow: 'hidden',
			boxShadow: '0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1)',
			...style,
		}}
	>
		<div style={{padding: '14px 26px', borderBottom: `1px solid ${color.termBorder}`, fontFamily: mono, fontSize: 22, color: color.termDim}}>
			{title}
		</div>
		{/* With a fixed height, the newest lines stay in view and older ones scroll off the top, as in a terminal. */}
		<div
			style={{
				padding: '18px 26px',
				fontFamily: mono,
				fontSize,
				lineHeight: 1.5,
				whiteSpace: 'pre',
				...(height ? {height: height - 54, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', overflow: 'hidden'} : {}),
			}}
		>
			{children}
		</div>
	</div>
);

/** One terminal line, shown from `at`; `type` types it out like a person at the keyboard. */
export const Line: React.FC<{at: number; text: string; tone?: Tone; type?: boolean}> = ({at, text, tone, type}) => {
	const frame = useCurrentFrame();
	if (frame < at) return null;
	const shown = type ? text.slice(0, Math.floor((frame - at) * 2.4) + 1) : text;
	return <div style={{color: tones[tone ?? toneOf(text)], minHeight: '1.5em'}}>{shown}</div>;
};

/** A plain browser window around real footage of the app. */
export const Browser: React.FC<{url: string; width: number; height: number; children: React.ReactNode; style?: React.CSSProperties}> = ({
	url,
	width,
	height,
	children,
	style,
}) => (
	<div
		style={{
			width,
			height,
			borderRadius: 18,
			background: color.page,
			border: `1px solid ${color.border}`,
			overflow: 'hidden',
			boxShadow: '0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1)',
			...style,
		}}
	>
		<div style={{height: 56, display: 'flex', alignItems: 'center', padding: '0 20px', borderBottom: `1px solid ${color.border}`, background: color.subtle}}>
			<div style={{flex: 1, height: 34, borderRadius: 8, background: color.page, border: `1px solid ${color.border}`, display: 'flex', alignItems: 'center', padding: '0 14px', fontFamily: mono, fontSize: 20, color: color.muted}}>
				{url}
			</div>
		</div>
		<div style={{position: 'relative', height: height - 56, overflow: 'hidden'}}>{children}</div>
	</div>
);

export const Check: React.FC<{ok: boolean; size?: number}> = ({ok, size = 30}) => (
	<svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true" style={{flexShrink: 0}}>
		<circle cx="12" cy="12" r="11" stroke={ok ? color.pass : color.fail} strokeWidth="1.6" />
		{ok ? (
			<path d="M7 12.5l3.2 3.2L17 9" stroke={color.pass} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
		) : (
			<path d="M8.5 8.5l7 7m0-7l-7 7" stroke={color.fail} strokeWidth="2" strokeLinecap="round" />
		)}
	</svg>
);

export const Wordmark: React.FC<{size: number}> = ({size}) => (
	<div style={{display: 'flex', alignItems: 'center', gap: size * 0.28}}>
		<svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
			<rect width="32" height="32" rx="7" fill={color.text} />
			<path d="M9 16.5l4.5 4.5L23 11.5" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
		</svg>
		<div style={{fontSize: size * 0.95, fontWeight: 600, lineHeight: 1}}>{PRODUCT}</div>
	</div>
);
