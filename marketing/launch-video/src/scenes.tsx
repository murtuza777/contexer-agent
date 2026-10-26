import React from 'react';
import {AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {
	Background,
	Caption,
	CheckRow,
	Line,
	Logo,
	MarkIcon,
	Pill,
	StepBadge,
	Window,
	useAppear,
	usePop,
} from './components';
import {INSTALL, LIVE_RUN, PRODUCT, REPO, TODO_CHECKS, color, mono} from './theme';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const center: React.CSSProperties = {alignItems: 'center', justifyContent: 'center'};

// 1 — The hook: the agent's claim, then the browser's verdict.
export const Hook: React.FC = () => {
	const claim = useAppear(0, 12);
	const verdict = useAppear(34, 16);
	const stamp = usePop(62, 9);
	return (
		<Background>
			<AbsoluteFill style={{...center, flexDirection: 'row', gap: 70, paddingBottom: 120}}>
				<div
					style={{
						width: 720,
						padding: 40,
						borderRadius: 28,
						background: color.bgSoft,
						border: `1px solid ${color.border}`,
						opacity: claim,
						translate: `0 ${(1 - claim) * 30}px`,
					}}
				>
					<div style={{fontSize: 26, color: color.muted, marginBottom: 18}}>Coding agent</div>
					<div style={{fontSize: 46, fontWeight: 600, lineHeight: 1.3}}>
						✅ Done! The remaining-count bug is fixed and everything works.
					</div>
				</div>
				<div
					style={{
						width: 820,
						position: 'relative',
						opacity: verdict,
						translate: `${(1 - verdict) * 60}px 0`,
					}}
				>
					<Window title={`${PRODUCT} · proven in Chromium`} width={820}>
						<div style={{padding: '26px 32px'}}>
							<div style={{display: 'flex', gap: 18, alignItems: 'center', marginBottom: 18}}>
								<MarkIcon mark="fail" size={40} />
								<div style={{fontSize: 32, fontWeight: 600}}>Completing a task lowers the remaining count</div>
							</div>
							<div style={{fontFamily: mono, fontSize: 28, lineHeight: 1.7, paddingLeft: 58, whiteSpace: 'pre'}}>
								<div>
									<span style={{color: color.muted}}>expected </span>
									<span style={{color: color.green}}>"1 left"</span>
								</div>
								<div>
									<span style={{color: color.muted}}>actual{'   '}</span>
									<span style={{color: color.red}}>"2 left"</span>
								</div>
								<div style={{color: color.red}}>uncaught: refesh is not defined</div>
							</div>
						</div>
					</Window>
					<div
						style={{
							position: 'absolute',
							right: -30,
							top: -40,
							rotate: '-8deg',
							scale: String(interpolate(stamp, [0, 1], [2.2, 1])),
							opacity: stamp,
							border: `5px solid ${color.red}`,
							color: color.red,
							borderRadius: 14,
							padding: '8px 26px',
							fontSize: 52,
							fontWeight: 800,
							letterSpacing: 4,
							background: 'rgba(10,14,20,0.85)',
						}}
					>
						REFUTED
					</div>
				</div>
			</AbsoluteFill>
			<Caption text="Your coding agent says it's done. A real browser says otherwise." start={40} />
		</Background>
	);
};

// 2 — Name and promise.
export const Title: React.FC = () => {
	const logo = usePop(0, 12);
	const name = useAppear(8, 16);
	const tag = useAppear(20, 16);
	const sub = useAppear(34, 16);
	return (
		<Background>
			<AbsoluteFill style={{...center, flexDirection: 'column', gap: 34}}>
				<div style={{scale: String(logo)}}>
					<Logo size={150} />
				</div>
				<div style={{fontSize: 150, fontWeight: 800, letterSpacing: -5, opacity: name}}>{PRODUCT}</div>
				<div style={{fontSize: 64, fontWeight: 600, opacity: tag, translate: `0 ${(1 - tag) * 20}px`}}>
					The AI engineer that owns <span style={{color: color.cyan}}>“done”</span>
				</div>
				<div style={{fontSize: 38, color: color.muted, opacity: sub}}>
					Open source · works on top of Claude Code, Codex and OpenCode
				</div>
			</AbsoluteFill>
		</Background>
	);
};

// 3 — Goal → checks a person approves (the real checklist of the live run).
export const Approve: React.FC = () => {
	const frame = useCurrentFrame();
	return (
		<Background>
			<StepBadge n={1} text="Describe the goal. Approve the checks." />
			<AbsoluteFill style={{...center, justifyContent: 'flex-start', paddingTop: 182}}>
				<Window title="~/notes-app" width={1620}>
					<div style={{padding: '18px 36px 20px'}}>
						<Line at={4} type tint={color.text} weight={500}>
							{`$ contexer run "${LIVE_RUN.goal}" --pr`}
						</Line>
						<div
							style={{
								marginTop: 12,
								padding: '10px 26px',
								border: `1px solid ${color.border}`,
								borderRadius: 14,
								opacity: interpolate(frame, [44, 54], [0, 1], clamp),
							}}
						>
							<div style={{fontFamily: mono, fontSize: 24, color: color.muted, marginBottom: 6}}>
								Definition of done · {LIVE_RUN.contract}
							</div>
							{LIVE_RUN.checks.map((text, i) => (
								<CheckRow key={text} at={52 + i * 8} text={text} mark="pending" tag="browser check" size={25} pad={7} icon={30} />
							))}
						</div>
						<Line at={150} tint={color.text} size={28}>
							Approve these checks as the definition of done? [y/N]: y
						</Line>
						<Line at={172} tint={color.green} weight={700} size={28}>
							{`✓ Approved ${LIVE_RUN.contract}`}
						</Line>
					</div>
				</Window>
			</AbsoluteFill>
			<Caption text="Your goal becomes browser checks. You approve what “done” means." start={20} />
		</Background>
	);
};

// 4 — The coding agent builds it (the live run's real tool calls).
export const Build: React.FC = () => (
	<Background>
		<StepBadge n={2} text="Your coding agent builds it." />
		<AbsoluteFill style={{...center, justifyContent: 'flex-start', paddingTop: 182}}>
			<Window title="contexer run" width={1620}>
				<div style={{padding: '24px 36px 30px'}}>
					<Line at={0} tint={color.cyan} weight={700}>{`Contexer run · ${LIVE_RUN.goal}`}</Line>
					<Line at={6} tint={color.muted} size={25}>{`${LIVE_RUN.agent} · up to 2 repair rounds`}</Line>
					<Line at={18} tint={color.amber} weight={700}>Attempt 1: implementing</Line>
					{LIVE_RUN.tools.map((tool, i) => (
						<Line key={i} at={30 + i * 9} tint={color.muted} indent={36} size={27}>
							{tool}
						</Line>
					))}
					<Line at={130} tint={color.cyan} weight={700}>Agent done — 2 file(s) changed (74s)</Line>
				</div>
			</Window>
		</AbsoluteFill>
		<Caption text="Claude Code, Codex or OpenCode writes the code. Its word never counts." start={24} />
	</Background>
);

const Counter: React.FC<{to: number; tint: string; label: string; start: number}> = ({to, tint, label, start}) => {
	const frame = useCurrentFrame();
	const n = Math.round(interpolate(frame, [start, start + 40], [0, to], clamp));
	return (
		<div style={{textAlign: 'center', minWidth: 220}}>
			<div style={{fontSize: 110, fontWeight: 800, color: tint, lineHeight: 1}}>{n}</div>
			<div style={{fontSize: 30, color: color.muted, marginTop: 8}}>{label}</div>
		</div>
	);
};

// 5 — Proof, then repair (attempt 1: 6 verified, 2 unverified; attempt 2: 8 of 8).
export const Prove: React.FC = () => {
	const frame = useCurrentFrame();
	const first = interpolate(frame, [0, 10, 120, 132], [0, 1, 1, 0], clamp);
	const second = useAppear(132, 14);
	const pass = usePop(240, 12);
	return (
		<Background>
			<StepBadge n={3} text="Every check is proven in a real browser." />
			<AbsoluteFill style={{...center, paddingTop: 60, paddingBottom: 140, opacity: first}}>
				<div style={{fontFamily: mono, fontSize: 32, color: color.amber, marginBottom: 40}}>
					Attempt 1: proving 8 checks in Chromium
				</div>
				<div style={{display: 'flex', gap: 80}}>
					<Counter to={6} tint={color.green} label="verified" start={12} />
					<Counter to={0} tint={color.red} label="refuted" start={12} />
					<Counter to={2} tint={color.amber} label="unverified" start={12} />
				</div>
				<div style={{marginTop: 46, opacity: interpolate(frame, [60, 72], [0, 1], clamp)}}>
					<Pill text="NEEDS ACTION — evidence goes back to the agent" tint={color.amber} size={32} />
				</div>
				<div style={{marginTop: 30, fontFamily: mono, fontSize: 28, color: color.magenta, opacity: interpolate(frame, [86, 96], [0, 1], clamp)}}>
					Attempt 2: repairing · edit app.js · Agent done — 1 file(s) changed (14s)
				</div>
			</AbsoluteFill>
			<AbsoluteFill style={{...center, paddingTop: 110, paddingBottom: 150, opacity: second}}>
				<div style={{width: 1560}}>
					<div style={{fontFamily: mono, fontSize: 30, color: color.amber, marginBottom: 10}}>
						Attempt 2: proving 8 checks in Chromium
					</div>
					{LIVE_RUN.checks.map((text, i) => (
						<CheckRow key={text} at={140 + i * 10} text={text} mark="pass" size={26} pad={9} />
					))}
				</div>
				<div
					style={{
						marginTop: 26,
						scale: String(interpolate(pass, [0, 1], [0.6, 1])),
						opacity: pass,
						fontSize: 46,
						fontWeight: 800,
						color: color.green,
					}}
				>
					SUCCEEDED — 8 of 8 proven · 111 s
				</div>
			</AbsoluteFill>
			<Caption
				text="Failures go back to the agent with the evidence. Worse attempts roll back."
				start={30}
			/>
		</Background>
	);
};

// 6 — The evidence report (a real report.html from `contexer demo`).
export const Evidence: React.FC = () => {
	const frame = useCurrentFrame();
	const t = useAppear(0, 16);
	return (
		<Background>
			<AbsoluteFill style={{...center, paddingBottom: 120}}>
				<Window title="report.html" width={1500} height={830} style={{opacity: t, translate: `0 ${(1 - t) * 40}px`}}>
					<div style={{height: 778, overflow: 'hidden'}}>
						<Img
							src={staticFile('report-fail.png')}
							style={{
								width: 1500,
								translate: `0 ${interpolate(frame, [20, 140], [0, -170], clamp)}px`,
							}}
						/>
					</div>
				</Window>
			</AbsoluteFill>
			<Caption text="Every run leaves a report: each check, expected vs actual, screenshots." start={14} />
		</Background>
	);
};

const GitHubFrame: React.FC<{children: React.ReactNode; width?: number}> = ({children, width = 1560}) => (
	<div
		style={{
			width,
			borderRadius: 18,
			background: color.github,
			border: `1px solid ${color.githubBorder}`,
			boxShadow: '0 40px 120px rgba(0,0,0,0.55)',
			overflow: 'hidden',
		}}
	>
		{children}
	</div>
);

// 7 — The pull request, with the proof in its description.
export const PullRequest: React.FC = () => {
	const head = useAppear(4, 14);
	const status = useAppear(150, 12);
	return (
		<Background>
			<StepBadge n={4} text="Review a pull request with the proof attached." />
			<AbsoluteFill style={{...center, justifyContent: 'flex-start', paddingTop: 182}}>
				<GitHubFrame>
					<div style={{padding: '18px 40px', borderBottom: `1px solid ${color.githubBorder}`, opacity: head}}>
						<div style={{fontSize: 38, fontWeight: 600}}>{LIVE_RUN.goal}</div>
						<div style={{display: 'flex', gap: 16, alignItems: 'center', marginTop: 14, fontSize: 26, color: color.muted}}>
							<Pill text="Open" tint={color.green} filled />
							<span>
								<span style={{fontFamily: mono, color: color.cyan}}>contexer/{LIVE_RUN.contract}</span> → main
							</span>
						</div>
					</div>
					<div style={{padding: '14px 40px 16px'}}>
						<div style={{fontSize: 30, fontWeight: 700, marginBottom: 6, opacity: useAppear(20, 10)}}>
							✅ All 8 checks proven in a real browser.
						</div>
						{LIVE_RUN.checks.map((text, i) => (
							<CheckRow key={text} at={30 + i * 8} text={text} mark="pass" tag="" size={24} pad={6} icon={30} />
						))}
						<div style={{fontSize: 24, color: color.muted, marginTop: 10, opacity: useAppear(104, 10)}}>
							Agent: {LIVE_RUN.agent} · 2 attempts, 1 repair round · 1m 51s
						</div>
					</div>
					<div
						style={{
							display: 'flex',
							alignItems: 'center',
							gap: 18,
							padding: '14px 40px',
							borderTop: `1px solid ${color.githubBorder}`,
							background: color.githubPanel,
							opacity: status,
						}}
					>
						<MarkIcon mark="pass" size={34} />
						<span style={{fontSize: 28, fontWeight: 600}}>contexer/acceptance</span>
						<span style={{fontSize: 26, color: color.muted}}>All checks proven in a browser · required</span>
					</div>
				</GitHubFrame>
			</AbsoluteFill>
			<Caption text="--pr ends the run in a pull request. Approved checks replay on every PR." start={40} />
		</Background>
	);
};

const Comment: React.FC<{at: number; who: string; bot?: boolean; children: React.ReactNode}> = ({at, who, bot, children}) => {
	const t = useAppear(at, 12);
	return (
		<div
			style={{
				border: `1px solid ${color.githubBorder}`,
				borderRadius: 14,
				overflow: 'hidden',
				marginTop: 18,
				opacity: t,
				translate: `0 ${(1 - t) * 24}px`,
			}}
		>
			<div style={{padding: '10px 24px', background: color.githubPanel, fontSize: 24, color: color.muted}}>
				<b style={{color: color.text}}>{who}</b> {bot ? <Pill text="bot" tint={color.muted} size={18} /> : null} commented
			</div>
			<div style={{padding: '14px 24px', fontSize: 26}}>{children}</div>
		</div>
	);
};

// 8 — From a labelled issue to a proven pull request (the real draft comment's content).
export const Issues: React.FC = () => {
	const frame = useCurrentFrame();
	const label = usePop(16, 12);
	const scroll = interpolate(frame, [140, 190], [0, -150], clamp);
	return (
		<Background>
			<AbsoluteFill style={{...center, paddingBottom: 120}}>
				<div style={{height: 840, overflow: 'hidden', borderRadius: 18}}>
					<div style={{translate: `0 ${scroll}px`}}>
						<GitHubFrame width={1500}>
							<div style={{padding: '24px 36px'}}>
								<div style={{fontSize: 42, fontWeight: 600}}>
									Remaining count ignores done tasks <span style={{color: color.muted}}>#7</span>
								</div>
								<div style={{display: 'flex', gap: 14, alignItems: 'center', marginTop: 12}}>
									<Pill text="Open" tint={color.green} filled />
									<span style={{scale: String(label), display: 'inline-block'}}>
										<Pill text="contexer" tint={color.cyan} filled />
									</span>
								</div>
								<Comment at={34} who="github-actions" bot>
									<div style={{fontSize: 30, fontWeight: 700, marginBottom: 6}}>
										{PRODUCT}: what “done” means for this issue
									</div>
									{TODO_CHECKS.map((text, i) => (
										<div key={text} style={{display: 'flex', gap: 14, alignItems: 'center', padding: '5px 0', fontSize: 24}}>
											<MarkIcon mark={i === 4 ? 'fail' : 'pass'} size={28} />
											<span style={{flex: 1}}>{text}</span>
											<span style={{color: i === 4 ? color.red : color.muted}}>
												{i === 4 ? 'not yet: got "2 left"' : 'already passes'}
											</span>
										</div>
									))}
									<div style={{color: color.muted, marginTop: 8, fontSize: 22}}>
										Someone with write access replies <span style={{fontFamily: mono}}>/contexer approve</span> to build it.
									</div>
								</Comment>
								<Comment at={120} who="you">
									<span style={{fontFamily: mono, fontSize: 30}}>/contexer approve</span>
								</Comment>
								<Comment at={168} who="github-actions" bot>
									<div style={{fontSize: 30, fontWeight: 700, color: color.green}}>
										✅ Done: all 7 checks proven in a real browser
									</div>
									<div style={{fontFamily: mono, fontSize: 22, color: color.muted, margin: '8px 0'}}>
										Attempt 1: implementing · Attempt 1: PASS: 7 verified, 0 refuted, 0 unverified
									</div>
									<div style={{fontSize: 26}}>
										Pull request: <span style={{color: color.cyan}}>Remaining count ignores done tasks #8</span> · closes #7
									</div>
								</Comment>
							</div>
						</GitHubFrame>
					</div>
				</div>
			</AbsoluteFill>
			<Caption text="Or label an issue, approve the checks in a comment, and get a proven PR." start={10} />
		</Background>
	);
};

const Stat: React.FC<{at: number; value: string; label: string; tint: string}> = ({at, value, label, tint}) => {
	const t = usePop(at, 13);
	return (
		<div
			style={{
				width: 760,
				padding: '34px 40px',
				borderRadius: 24,
				background: color.bgSoft,
				border: `1px solid ${color.border}`,
				opacity: t,
				scale: String(interpolate(t, [0, 1], [0.9, 1])),
			}}
		>
			<div style={{fontSize: 92, fontWeight: 800, color: tint, lineHeight: 1}}>{value}</div>
			<div style={{fontSize: 34, color: color.text, marginTop: 14, lineHeight: 1.3}}>{label}</div>
		</div>
	);
};

// 9 — Measured, not claimed (contexer bench).
export const Numbers: React.FC = () => (
	<Background>
		<AbsoluteFill style={{...center, flexDirection: 'column', gap: 34, paddingBottom: 110}}>
			<div style={{fontSize: 70, fontWeight: 800, letterSpacing: -2, opacity: useAppear(0, 12)}}>Measured, not claimed.</div>
			<div style={{display: 'grid', gridTemplateColumns: '760px 760px', gap: 32}}>
				<Stat at={10} value="40 / 40" label="seeded bugs caught by hand-written contracts" tint={color.green} />
				<Stat at={22} value="0 / 278" label="false failures on correct code" tint={color.cyan} />
				<Stat at={34} value="33 / 40" label="caught from one-line goals, drafted by a free model" tint={color.amber} />
				<Stat at={46} value="14" label="model providers — bring your own key, or run free" tint={color.magenta} />
			</div>
		</AbsoluteFill>
		<Caption text="contexer bench: 7 fixture apps, incl. React + Vite, Next.js and sign-in." start={30} />
	</Background>
);

// 10 — Try it.
export const Cta: React.FC = () => {
	const end = useAppear(120, 16);
	return (
		<Background>
			<AbsoluteFill style={{...center, flexDirection: 'column', gap: 40, paddingBottom: 120}}>
				<div style={{fontSize: 80, fontWeight: 800, letterSpacing: -2, opacity: useAppear(0, 12)}}>Try it on your app.</div>
				<Window title="terminal" width={1640}>
					<div style={{padding: '22px 34px 26px'}}>
						<Line at={10} type size={24}>{`$ ${INSTALL}`}</Line>
						<Line at={70} type size={30}>$ contexer setup</Line>
						<Line at={88} type size={30}>{'$ contexer run "users can export their data as CSV" --pr'}</Line>
					</div>
				</Window>
				<div style={{display: 'flex', alignItems: 'center', gap: 30, opacity: end}}>
					<Logo size={84} />
					<div>
						<div style={{fontSize: 46, fontWeight: 700}}>{REPO}</div>
						<div style={{fontSize: 30, color: color.muted, marginTop: 6}}>
							Open source (MIT) · free with an OpenRouter key · Claude Code, Codex, OpenCode
						</div>
					</div>
				</div>
			</AbsoluteFill>
			<Caption text="Point it at a real app and tell us what it caught." start={130} />
		</Background>
	);
};
