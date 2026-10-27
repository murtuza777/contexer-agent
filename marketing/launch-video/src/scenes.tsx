import React from 'react';
import {Audio, Video} from '@remotion/media';
import {AbsoluteFill, interpolate, Sequence, staticFile, useCurrentFrame} from 'remotion';
import captions from './captions.json';
import {Browser, Caption, Check, Kicker, Line, Page, Reveal, Terminal, Wordmark, useReveal} from './components';
import data from './data.json';
import {INSTALL, REPO, color, mono} from './theme';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

/** A sound cue at a frame of the scene. */
const Cue: React.FC<{at: number; name: 'tick' | 'pass' | 'fail'; volume?: number}> = ({at, name, volume = 0.35}) => (
	<Sequence from={at} durationInFrames={30} layout="none">
		<Audio src={staticFile(`sfx-${name}.wav`)} volume={volume} />
	</Sequence>
);

/** Real footage of the todo app while Contexer checks it, cropped to the app's card. */
const Footage: React.FC<{src: string; width: number; from?: number}> = ({src, width, from = 0}) => {
	const scale = width / 600; // the card sits in x 340–940, y 20–380 of the 1280 × 800 recording
	return (
		<Sequence from={from} layout="none">
			<div style={{position: 'absolute', left: -340 * scale, top: -20 * scale, width: 1280 * scale, height: 800 * scale}}>
				<Video src={staticFile(src)} style={{width: '100%', height: '100%'}} muted />
			</div>
		</Sequence>
	);
};

// 1 · The agent's claim against the browser's verdict (3 bars).
export const Hook: React.FC = () => {
	const verdict = useReveal(172, 10);
	return (
		<Page tone="subtle">
			<Reveal at={4} style={{position: 'absolute', left: 120, top: 250, width: 640}}>
				<div style={{fontFamily: mono, fontSize: 28, color: color.muted}}>coding agent</div>
				<div style={{fontSize: 64, fontWeight: 600, lineHeight: 1.15, marginTop: 18, textWrap: 'balance'}}>
					“Done. Completing a task now updates the count.”
				</div>
			</Reveal>
			<Reveal at={12} style={{position: 'absolute', left: 880, top: 150}}>
				<Browser url="127.0.0.1:5173 · checked by Contexer in Chromium" width={920} height={612}>
					<Footage src="check-bug.mp4" width={920} from={12} />
				</Browser>
			</Reveal>
			<div
				style={{
					position: 'absolute',
					left: 880,
					top: 800,
					width: 920,
					display: 'flex',
					gap: 18,
					alignItems: 'center',
					padding: '18px 24px',
					borderRadius: 14,
					background: color.page,
					border: `1px solid ${color.border}`,
					opacity: verdict,
					translate: `0 ${(1 - verdict) * 12}px`,
				}}
			>
				<Check ok={false} size={40} />
				<div style={{fontSize: 30, lineHeight: 1.35}}>
					Completing a task lowers the remaining count
					<div style={{fontFamily: mono, fontSize: 26, color: color.muted}}>
						expected <span style={{color: color.text}}>"1 left"</span> · actual <span style={{color: color.fail}}>"2 left"</span>
					</div>
				</div>
			</div>
			<Cue at={174} name="fail" volume={0.5} />
			<Caption text={captions.Hook} at={24} />
		</Page>
	);
};

// 2 · The name and the promise (2 bars), on the music's first downbeat.
export const Title: React.FC = () => (
	<Page>
		<AbsoluteFill style={{justifyContent: 'center', padding: '0 160px'}}>
			<Reveal at={0} distance={10}>
				<Wordmark size={120} />
			</Reveal>
			<Reveal at={10} style={{marginTop: 48}}>
				<div style={{fontSize: 76, fontWeight: 600, lineHeight: 1.1, maxWidth: 1400, textWrap: 'balance'}}>
					Proof that your coding agent is actually done.
				</div>
			</Reveal>
			<Reveal at={22} style={{marginTop: 28, fontSize: 36, color: color.muted}}>
				Open source · works with Claude Code, Codex and OpenCode
			</Reveal>
		</AbsoluteFill>
	</Page>
);

// 3 · The goal becomes checks the person approves (4 bars). Text from Contexer's own renderer.
export const Approve: React.FC = () => {
	const lines = data.approve.filter((l, i, all) => !(l === '' && (i === 0 || all[i - 1] === '')));
	const done = 64 + lines.length * 6;
	return (
		<Page tone="subtle">
			<Kicker step="01" text="Describe the goal. Approve what “done” means." />
			<div style={{position: 'absolute', left: 120, top: 300}}>
				<Terminal title="~/todo-app" width={1680} height={600} fontSize={23}>
					<Line at={6} type text={`$ contexer run "${data.goal}" --pr`} />
					{lines.map((text, i) => (
						<Line key={i} at={64 + i * 6} text={text} />
					))}
					<Line at={done + 18} text="Approve these checks as the definition of done? [y/N]: y" tone="plain" />
					<Line at={done + 34} text="✓ Approved todo-basics" />
				</Terminal>
			</div>
			<Cue at={done + 34} name="tick" />
			<Caption text={captions.Approve} at={20} />
		</Page>
	);
};

// 4 · The coding agent at work: the live run's real lines at their real relative times, sped up (3 bars).
const RUN_START = 2.5;
const RUN_END = 84.2;
const toFrame = (t: number) => Math.round(interpolate(t, [RUN_START, RUN_END], [10, 168], clamp));

export const Build: React.FC = () => {
	const frame = useCurrentFrame();
	const lines = data.run.filter((l) => l.t >= RUN_START && l.t <= RUN_END + 0.1 && l.text !== '');
	const realSeconds = interpolate(frame, [10, 168], [RUN_START, RUN_END], clamp);
	const tools = lines.filter((l) => /^ {4}(glob|read|edit|write|bash) /.test(l.text) && toFrame(l.t) <= frame).length;
	const working = frame >= toFrame(3) && frame < toFrame(84.18);
	const spinner = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'[Math.floor(frame / 3) % 10];
	const elapsed = Math.max(0, realSeconds - 3);
	return (
		<Page tone="subtle">
			<Kicker step="02" text="Your coding agent builds it." />
			<Reveal at={4} style={{position: 'absolute', right: 120, top: 120, fontSize: 26, color: color.muted, textAlign: 'right'}}>
				A real run · OpenCode with a free model
				<br />
				sped up from {Math.round(RUN_END - RUN_START)} seconds
			</Reveal>
			<div style={{position: 'absolute', left: 120, top: 300}}>
				<Terminal title="contexer run" width={1680} fontSize={25}>
					{lines.map((l, i) => (
						<Line key={i} at={toFrame(l.t)} text={l.text} />
					))}
					{working ? (
						<div style={{color: color.termDim}}>
							{`  ${spinner} Agent working · ${Math.floor(elapsed / 60)}:${String(Math.floor(elapsed % 60)).padStart(2, '0')} · ${tools} tool call(s)`}
						</div>
					) : null}
				</Terminal>
			</div>
			<Caption text={captions.Build} at={20} />
		</Page>
	);
};

// 5 · Every check proven in the browser, then the result (5 bars).
export const Prove: React.FC = () => {
	const result = data.run.filter((l) => l.t > 90);
	const checkAt = (i: number) => 40 + i * 16;
	return (
		<Page tone="subtle">
			<Kicker step="03" text="Contexer proves every check in a real browser." />
			<div style={{position: 'absolute', left: 120, top: 300, width: 1000}}>
				<Terminal title="contexer run" width={1000} fontSize={22}>
					<Line at={6} text="  Attempt 1: proving 7 checks in Chromium" />
					{data.prChecks.map((c, i) => (
						<Line key={i} at={checkAt(i)} text={`    ✓ ${c.text}`} />
					))}
					<Line at={checkAt(7) + 8} text="  ✓ Attempt 1: PASS: 7 verified, 0 refuted, 0 unverified" />
				</Terminal>
			</div>
			<Reveal at={10} style={{position: 'absolute', left: 1150, top: 300}}>
				<Browser url="127.0.0.1:5173 · after the agent's change" width={650} height={460}>
					<Footage src="check-fixed.mp4" width={650} from={18} />
				</Browser>
			</Reveal>
			<Reveal at={checkAt(7) + 30} style={{position: 'absolute', left: 1150, top: 790, width: 650}}>
				{result
					.filter((l) => /Succeeded|Pull request|Took/.test(l.text))
					.map((l, i) => (
						<div key={i} style={{fontFamily: mono, fontSize: 22, lineHeight: 1.6, color: i === 0 ? color.pass : color.muted, whiteSpace: 'pre'}}>
							{l.text.trim().replace(' · Every check proven in the browser.', ': every check proven')}
						</div>
					))}
			</Reveal>
			{data.prChecks.map((_, i) => (
				<Cue key={i} at={checkAt(i)} name="tick" volume={0.18} />
			))}
			<Cue at={checkAt(7) + 8} name="pass" volume={0.4} />
			<Caption text={captions.Prove} at={20} />
		</Page>
	);
};

const GitHubPage: React.FC<{children: React.ReactNode; top?: number; scroll?: number}> = ({children, top = 290, scroll = 0}) => (
	<div style={{position: 'absolute', left: 120, right: 120, top, bottom: 150, overflow: 'hidden', borderRadius: 18, border: `1px solid ${color.border}`, background: color.page}}>
		<div style={{padding: '32px 44px', translate: `0 ${scroll}px`}}>{children}</div>
	</div>
);

const Pill: React.FC<{text: string; tone: 'open' | 'label'}> = ({text, tone}) => (
	<span
		style={{
			display: 'inline-block',
			padding: '6px 18px',
			borderRadius: 999,
			fontSize: 24,
			fontWeight: 500,
			color: tone === 'open' ? '#fff' : color.text,
			background: tone === 'open' ? color.pass : color.subtle,
			border: `1px solid ${tone === 'open' ? color.pass : color.border}`,
		}}
	>
		{text}
	</span>
);

// 6 · The pull request, with the proof in its description (3 bars).
export const PullRequest: React.FC = () => (
	<Page tone="subtle">
		<Kicker step="04" text="You review a pull request with the proof inside." />
		<GitHubPage>
			<Reveal at={4}>
				<div style={{fontSize: 34, fontWeight: 600}}>
					{data.goal} <span style={{color: color.faint, fontWeight: 400}}>#8</span>
				</div>
				<div style={{display: 'flex', gap: 16, alignItems: 'center', marginTop: 14, fontSize: 24, color: color.muted}}>
					<Pill text="Open" tone="open" />
					<span style={{fontFamily: mono}}>contexer/todo-basics → main</span>
				</div>
			</Reveal>
			<Reveal at={16} style={{marginTop: 22, display: 'flex', gap: 14, alignItems: 'center', fontSize: 28, fontWeight: 600}}>
				<Check ok size={34} /> All 7 checks proven in a real browser.
			</Reveal>
			<div style={{marginTop: 12}}>
				{data.prChecks.map((c, i) => (
					<Reveal key={i} at={26 + i * 6} distance={6} style={{display: 'flex', gap: 14, alignItems: 'center', padding: '4px 0', fontSize: 23, borderBottom: `1px solid ${color.border}`}}>
						<Check ok size={24} /> {c.text}
					</Reveal>
				))}
			</div>
			<Reveal at={80} style={{marginTop: 12, fontSize: 22, color: color.muted}}>
				Agent: {data.prAgent} · Closes #7
			</Reveal>
		</GitHubPage>
		<Reveal at={120} style={{position: 'absolute', left: 121, right: 121, bottom: 151, display: 'flex', gap: 14, alignItems: 'center', padding: '16px 44px', background: color.page, borderTop: `1px solid ${color.border}`, borderRadius: '0 0 18px 18px', fontSize: 26}}>
			<Check ok size={30} /> <b>contexer/acceptance</b> <span style={{color: color.muted}}>All checks proven in a browser · required</span>
		</Reveal>
		<Cue at={120} name="tick" />
		<Caption text={captions.PullRequest} at={20} />
	</Page>
);

const Comment: React.FC<{at: number; who: string; children: React.ReactNode}> = ({at, who, children}) => (
	<Reveal at={at} distance={10} style={{marginTop: 18, border: `1px solid ${color.border}`, borderRadius: 12, overflow: 'hidden'}}>
		<div style={{padding: '10px 22px', background: color.subtle, borderBottom: `1px solid ${color.border}`, fontSize: 22, color: color.muted}}>
			<b style={{color: color.text}}>{who}</b> commented
		</div>
		<div style={{padding: '14px 22px', fontSize: 24}}>{children}</div>
	</Reveal>
);

// 7 · From a labelled issue to a proven pull request (3 bars).
export const Issues: React.FC = () => {
	const frame = useCurrentFrame();
	const label = useReveal(14, 8);
	return (
		<Page tone="subtle">
			<Kicker text="Or hand it a GitHub issue." />
			<GitHubPage top={220} scroll={interpolate(frame, [120, 160], [0, -150], clamp)}>
				<div style={{fontSize: 38, fontWeight: 600}}>
					Remaining count ignores done tasks <span style={{color: color.faint, fontWeight: 400}}>#7</span>
				</div>
				<div style={{display: 'flex', gap: 12, marginTop: 12}}>
					<Pill text="Open" tone="open" />
					<span style={{opacity: label}}>
						<Pill text="contexer" tone="label" />
					</span>
				</div>
				<Comment at={30} who="github-actions">
					<div style={{fontWeight: 600, marginBottom: 6}}>Contexer: what “done” means for this issue</div>
					{data.issueChecks.map((c, i) => (
						<div key={i} style={{display: 'flex', gap: 12, alignItems: 'center', padding: '3px 0', fontSize: 22}}>
							<Check ok={c.today === 'verified'} size={24} />
							<span style={{flex: 1}}>{c.text}</span>
							<span style={{color: c.today === 'verified' ? color.muted : color.fail}}>{c.today === 'verified' ? 'already passes' : 'not yet'}</span>
						</div>
					))}
				</Comment>
				<Comment at={100} who="you">
					<span style={{fontFamily: mono}}>/contexer approve</span>
				</Comment>
				<Comment at={150} who="github-actions">
					<div style={{color: color.pass, fontWeight: 600}}>Done: all 7 checks proven in a real browser</div>
					<div style={{marginTop: 6}}>Pull request #8 · closes this issue</div>
				</Comment>
			</GitHubPage>
			<Cue at={14} name="tick" />
			<Cue at={100} name="tick" />
			<Cue at={150} name="pass" volume={0.3} />
			<Caption text={captions.Issues} at={20} />
		</Page>
	);
};

// 8 · The benchmark (2 bars).
export const Numbers: React.FC = () => {
	const rows = [
		['40 of 40', 'seeded bugs caught by hand-written contracts'],
		['0 of 278', 'checks failed on correct code'],
		['33 of 40', 'bugs caught from one-line goals, drafted by a free model'],
	];
	return (
		<Page>
			<Kicker text="Measured, not claimed." />
			<div style={{position: 'absolute', left: 120, right: 120, top: 300}}>
				{rows.map(([value, label], i) => (
					<Reveal key={value} at={8 + i * 10} style={{display: 'flex', alignItems: 'baseline', gap: 48, padding: '28px 0', borderTop: `1px solid ${color.border}`}}>
						<div style={{width: 420, fontSize: 96, fontWeight: 600, fontVariantNumeric: 'tabular-nums'}}>{value}</div>
						<div style={{fontSize: 40, color: color.muted}}>{label}</div>
					</Reveal>
				))}
			</div>
			<Caption text={captions.Numbers} at={20} />
		</Page>
	);
};

// 9 · How to start (3 bars and a hold).
export const Cta: React.FC = () => (
	<Page>
		<Kicker text="Try it on your app." />
		<div style={{position: 'absolute', left: 120, right: 120, top: 300}}>
			{[INSTALL, 'contexer setup', 'contexer demo --fix', 'contexer run "<what must be true>" --pr'].map((cmd, i) => (
				<Reveal key={cmd} at={10 + i * 12} style={{marginBottom: 18, padding: '18px 26px', borderRadius: 12, border: `1px solid ${color.border}`, background: color.subtle, fontFamily: mono, fontSize: i === 0 ? 24 : 30}}>
					<span style={{color: color.faint}}>$ </span>
					{cmd}
				</Reveal>
			))}
			<Reveal at={70} style={{marginTop: 40, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
				<Wordmark size={64} />
				<div style={{fontSize: 36, fontWeight: 500}}>{REPO}</div>
			</Reveal>
		</div>
		<Caption text={captions.Cta} at={30} />
	</Page>
);
