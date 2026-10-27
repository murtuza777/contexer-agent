import React from 'react';
import {Audio} from '@remotion/media';
import {interpolate, Series, staticFile} from 'remotion';
import {Approve, Build, Cta, Hook, Issues, Numbers, Prove, PullRequest, Title} from './scenes';
import {BAR} from './theme';
import timeline from './timeline.json';

const COMPONENTS: Record<string, React.FC> = {Hook, Title, Approve, Build, Prove, PullRequest, Issues, Numbers, Cta};

// Scene lengths in bars of the soundtrack (100 BPM, 72 frames a bar): every cut lands on a downbeat,
// and the title arrives with the music's first impact at bar 3. timeline.json also feeds the subtitles.
export const SCENES = timeline.map((s) => ({name: s.name, bars: s.bars, component: COMPONENTS[s.name]}));

const HOLD = 45; // the last frame stays up while the music rings out
export const LAUNCH_FRAMES = SCENES.reduce((sum, s) => sum + s.bars * BAR, 0) + HOLD;

/** Where each scene starts, in frames, for captions and gallery stills. */
export const sceneStart = (name: string) => {
	let at = 0;
	for (const s of SCENES) {
		if (s.name === name) return at;
		at += s.bars * BAR;
	}
	throw new Error(`no scene ${name}`);
};

export const Launch: React.FC = () => (
	<>
		<Series>
			{SCENES.map((scene, i) => {
				const Scene = scene.component;
				const last = i === SCENES.length - 1;
				return (
					<Series.Sequence key={scene.name} name={scene.name} durationInFrames={scene.bars * BAR + (last ? HOLD : 0)}>
						<Scene />
					</Series.Sequence>
				);
			})}
		</Series>
		<Audio
			src={staticFile('music.wav')}
			volume={(f) => 0.6 * interpolate(f, [0, 6, LAUNCH_FRAMES - 40, LAUNCH_FRAMES], [0, 1, 1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}
		/>
	</>
);
