import React from 'react';
import {AbsoluteFill, Composition, Folder, Still} from 'remotion';
import {Logo} from './components';
import {LAUNCH_FRAMES, Launch} from './Launch';
import {Approve, Hook, Issues, Numbers, Prove, PullRequest} from './scenes';
import {color} from './theme';

const GALLERY = {Hook, Approve, Prove, PullRequest, Issues, Numbers};

type GalleryProps = {scene: keyof typeof GALLERY};

/** A scene scaled to fill a Product Hunt gallery image (1270 × 760; the sides of 1920 × 1080 are trimmed); render one frame of it. */
const GalleryImage: React.FC<GalleryProps> = ({scene}) => {
	const Scene = GALLERY[scene];
	return (
		<AbsoluteFill style={{background: color.bg, alignItems: 'center', justifyContent: 'center'}}>
			<div style={{width: 1920, height: 1080, scale: String(760 / 1080), flexShrink: 0, position: 'relative'}}>
				<Scene />
			</div>
		</AbsoluteFill>
	);
};

const Thumbnail: React.FC = () => (
	<AbsoluteFill style={{background: color.bg, alignItems: 'center', justifyContent: 'center'}}>
		<Logo size={190} />
	</AbsoluteFill>
);

export const RemotionRoot: React.FC = () => (
	<>
		<Composition id="Launch" component={Launch} durationInFrames={LAUNCH_FRAMES} fps={30} width={1920} height={1080} />
		<Folder name="ProductHunt">
			<Composition id="Gallery1Hook" component={GalleryImage} durationInFrames={300} fps={30} width={1270} height={760} defaultProps={{scene: 'Hook'}} />
			<Composition id="Gallery2Approve" component={GalleryImage} durationInFrames={300} fps={30} width={1270} height={760} defaultProps={{scene: 'Approve'}} />
			<Composition id="Gallery3Prove" component={GalleryImage} durationInFrames={300} fps={30} width={1270} height={760} defaultProps={{scene: 'Prove'}} />
			<Composition id="Gallery4PullRequest" component={GalleryImage} durationInFrames={300} fps={30} width={1270} height={760} defaultProps={{scene: 'PullRequest'}} />
			<Composition id="Gallery5Issues" component={GalleryImage} durationInFrames={300} fps={30} width={1270} height={760} defaultProps={{scene: 'Issues'}} />
			<Composition id="Gallery6Numbers" component={GalleryImage} durationInFrames={300} fps={30} width={1270} height={760} defaultProps={{scene: 'Numbers'}} />
			<Still id="Thumbnail" component={Thumbnail} width={240} height={240} />
		</Folder>
	</>
);
