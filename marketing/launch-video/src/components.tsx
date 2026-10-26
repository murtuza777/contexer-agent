import React from 'react';
import {AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {color, mono, sans} from './theme';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const ease = Easing.bezier(0.16, 1, 0.3, 1);

/** 0 → 1 over `duration` frames from `start`, eased. */
export const useAppear = (start: number, duration = 14) => {
	const frame = useCurrentFrame();
	return interpolate(frame, [start, start + duration], [0, 1], {...clamp, easing: ease});
};

/** A spring that starts at `start`. */
export const usePop = (start: number, damping = 14) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	return spring({frame: frame - start, fps, config: {damping, stiffness: 140}});
};

export const Background: React.FC<{children: React.ReactNode}> = ({children}) => (
	<AbsoluteFill
		style={{
			background: `radial-gradient(circle at 20% 0%, #13213a 0%, ${color.bg} 55%), ${color.bg}`,
			fontFamily: sans,
			color: color.text,
		}}
	>
		<AbsoluteFill
			style={{
				backgroundImage: 'linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px)',
				backgroundSize: '64px 64px',
			}}
		/>
		{children}
	</AbsoluteFill>
);

/** Burned-in caption: most people watch launch videos muted. */
export const Caption: React.FC<{text: string; start?: number}> = ({text, start = 6}) => {
	const t = useAppear(start, 16);
	return (
		<div
			style={{
				position: 'absolute',
				left: 0,
				right: 0,
				bottom: 64,
				display: 'flex',
				justifyContent: 'center',
				opacity: t,
				translate: `0 ${(1 - t) * 24}px`,
			}}
		>
			<div
				style={{
					maxWidth: 1700,
					padding: '16px 36px',
					borderRadius: 18,
					background: 'rgba(10,14,20,0.82)',
					border: `1px solid ${color.border}`,
					fontSize: 38,
					fontWeight: 500,
					lineHeight: 1.3,
					textAlign: 'center',
				}}
			>
				{text}
			</div>
		</div>
	);
};

export const StepBadge: React.FC<{n: number; text: string}> = ({n, text}) => {
	const t = useAppear(0, 14);
	return (
		<div
			style={{
				position: 'absolute',
				top: 72,
				left: 110,
				display: 'flex',
				alignItems: 'center',
				gap: 24,
				opacity: t,
				translate: `${(1 - t) * -30}px 0`,
			}}
		>
			<div
				style={{
					width: 72,
					height: 72,
					borderRadius: 20,
					background: color.cyan,
					color: color.bg,
					fontSize: 42,
					fontWeight: 800,
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
				}}
			>
				{n}
			</div>
			<div style={{fontSize: 56, fontWeight: 700, letterSpacing: -1}}>{text}</div>
		</div>
	);
};

export const Window: React.FC<{
	title?: string;
	width: number;
	height?: number;
	children: React.ReactNode;
	style?: React.CSSProperties;
}> = ({title, width, height, children, style}) => (
	<div
		style={{
			width,
			height,
			borderRadius: 20,
			background: color.panel,
			border: `1px solid ${color.border}`,
			boxShadow: '0 40px 120px rgba(0,0,0,0.55)',
			overflow: 'hidden',
			...style,
		}}
	>
		<div
			style={{
				height: 52,
				display: 'flex',
				alignItems: 'center',
				gap: 10,
				padding: '0 20px',
				borderBottom: `1px solid ${color.border}`,
				background: color.bgSoft,
			}}
		>
			{['#FF5F57', '#FEBC2E', '#28C840'].map((c) => (
				<div key={c} style={{width: 14, height: 14, borderRadius: 7, background: c}} />
			))}
			<div style={{marginLeft: 16, fontSize: 22, color: color.muted, fontFamily: mono}}>{title}</div>
		</div>
		{children}
	</div>
);

/** A terminal line that fades in at `at`; `type` types it out character by character. */
export const Line: React.FC<{
	at: number;
	children: string;
	tint?: string;
	type?: boolean;
	indent?: number;
	weight?: number;
	size?: number;
}> = ({at, children, tint = color.text, type = false, indent = 0, weight = 400, size = 28}) => {
	const frame = useCurrentFrame();
	if (frame < at) return null;
	const shown = type ? children.slice(0, Math.floor((frame - at) * 1.6) + 1) : children;
	const t = interpolate(frame, [at, at + 6], [0, 1], clamp);
	return (
		<div
			style={{
				fontFamily: mono,
				fontSize: size,
				lineHeight: 1.55,
				color: tint,
				paddingLeft: indent,
				opacity: type ? 1 : t,
				fontWeight: weight,
				whiteSpace: 'pre',
			}}
		>
			{shown}
		</div>
	);
};

type Mark = 'pass' | 'fail' | 'open' | 'pending';

export const MarkIcon: React.FC<{mark: Mark; size?: number}> = ({mark, size = 34}) => {
	const map = {
		pass: {c: color.green, s: '✓'},
		fail: {c: color.red, s: '✗'},
		open: {c: color.amber, s: '?'},
		pending: {c: color.dim, s: '•'},
	}[mark];
	return (
		<div
			style={{
				width: size,
				height: size,
				borderRadius: size / 2,
				border: `2px solid ${map.c}`,
				color: map.c,
				fontSize: size * 0.62,
				fontWeight: 800,
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'center',
				flexShrink: 0,
			}}
		>
			{map.s}
		</div>
	);
};

export const CheckRow: React.FC<{at: number; text: string; mark: Mark; tag?: string; size?: number; pad?: number; icon?: number}> = ({
	at,
	text,
	mark,
	tag = 'proven',
	size = 30,
	pad = 12,
	icon = 34,
}) => {
	const t = useAppear(at, 10);
	return (
		<div
			style={{
				display: 'flex',
				alignItems: 'center',
				gap: 20,
				padding: `${pad}px 0`,
				borderBottom: `1px solid ${color.border}`,
				opacity: t,
				translate: `${(1 - t) * 20}px 0`,
			}}
		>
			<MarkIcon mark={mark} size={icon} />
			<div style={{flex: 1, fontSize: size}}>{text}</div>
			{tag ? (
				<div
					style={{
						fontSize: 22,
						padding: '4px 14px',
						borderRadius: 999,
						border: `1.5px solid ${mark === 'pass' ? color.green : color.border}`,
						color: mark === 'pass' ? color.green : color.muted,
					}}
				>
					{tag}
				</div>
			) : null}
		</div>
	);
};

export const Pill: React.FC<{text: string; tint: string; filled?: boolean; size?: number}> = ({text, tint, filled, size = 24}) => (
	<span
		style={{
			display: 'inline-flex',
			alignItems: 'center',
			padding: '4px 16px',
			borderRadius: 999,
			fontSize: size,
			fontWeight: 600,
			color: filled ? color.bg : tint,
			background: filled ? tint : 'transparent',
			border: `1.5px solid ${tint}`,
		}}
	>
		{text}
	</span>
);

export const Logo: React.FC<{size?: number}> = ({size = 120}) => (
	<div
		style={{
			width: size,
			height: size,
			borderRadius: size * 0.26,
			background: `linear-gradient(135deg, ${color.cyan}, #2563EB)`,
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'center',
			boxShadow: `0 0 ${size * 0.5}px rgba(34,211,238,0.35)`,
		}}
	>
		<svg width={size * 0.56} height={size * 0.56} viewBox="0 0 24 24" fill="none">
			<path d="M4 12.5l5 5L20 6.5" stroke={color.bg} strokeWidth={3.2} strokeLinecap="round" strokeLinejoin="round" />
		</svg>
	</div>
);
