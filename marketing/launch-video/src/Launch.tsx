import React from 'react';
import {linearTiming, TransitionSeries} from '@remotion/transitions';
import {fade} from '@remotion/transitions/fade';
import {slide} from '@remotion/transitions/slide';
import {Approve, Build, Cta, Evidence, Hook, Issues, Numbers, Prove, PullRequest, Title} from './scenes';

const T = 12; // frames per transition

// Scene lengths in frames at 30 fps; transitions overlap neighbours by T frames.
export const SCENES = [
	{name: 'Hook', component: Hook, frames: 150},
	{name: 'Title', component: Title, frames: 96},
	{name: 'Approve', component: Approve, frames: 220},
	{name: 'Build', component: Build, frames: 175},
	{name: 'Prove', component: Prove, frames: 300},
	{name: 'Evidence', component: Evidence, frames: 150},
	{name: 'PullRequest', component: PullRequest, frames: 210},
	{name: 'Issues', component: Issues, frames: 240},
	{name: 'Numbers', component: Numbers, frames: 160},
	{name: 'Cta', component: Cta, frames: 220},
] as const;

export const LAUNCH_FRAMES = SCENES.reduce((sum, s) => sum + s.frames, 0) - T * (SCENES.length - 1);

export const Launch: React.FC = () => (
	<TransitionSeries>
		{SCENES.map((scene, i) => {
			const Scene = scene.component;
			return (
				<React.Fragment key={scene.name}>
					{i > 0 ? (
						<TransitionSeries.Transition
							presentation={i >= 2 && i <= 4 ? slide({direction: 'from-right'}) : fade()}
							timing={linearTiming({durationInFrames: T})}
						/>
					) : null}
					<TransitionSeries.Sequence name={scene.name} durationInFrames={scene.frames}>
						<Scene />
					</TransitionSeries.Sequence>
				</React.Fragment>
			);
		})}
	</TransitionSeries>
);
