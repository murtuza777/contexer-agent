import React from 'react';
import {AbsoluteFill, Composition, Folder, Still} from 'remotion';
import {Wordmark} from './components';
import {LAUNCH_FRAMES, Launch} from './Launch';
import {Approve, Hook, Issues, Numbers, Prove, PullRequest} from './scenes';
import {REPO, color, sans} from './theme';

const GALLERY = {Hook, Approve, Prove, PullRequest, Issues, Numbers};

type GalleryProps = {scene: keyof typeof GALLERY};

/** A scene scaled to fill a Product Hunt gallery image (1270 × 760; the sides of 1920 × 1080 are trimmed). */
const GalleryImage: React.FC<GalleryProps> = ({scene}) => {
	const Scene = GALLERY[scene];
	return (
		<AbsoluteFill style={{background: color.subtle, alignItems: 'center', justifyContent: 'center'}}>
			<div style={{width: 1920, height: 1080, scale: String(760 / 1080), flexShrink: 0, position: 'relative'}}>
				<Scene />
			</div>
		</AbsoluteFill>
	);
};

/** The website's social card. */
const OgImage: React.FC = () => (
	<AbsoluteFill style={{background: color.page, color: color.text, fontFamily: sans, padding: 80, justifyContent: 'space-between'}}>
		<Wordmark size={56} />
		<div style={{fontSize: 68, fontWeight: 600, lineHeight: 1.1, textWrap: 'balance'}}>Proof that your coding agent is actually done.</div>
		<div style={{fontSize: 28, color: color.muted}}>Open source · {REPO}</div>
	</AbsoluteFill>
);

const Thumbnail: React.FC = () => (
	<AbsoluteFill style={{background: color.page, alignItems: 'center', justifyContent: 'center'}}>
		<svg width={176} height={176} viewBox="0 0 32 32" aria-hidden="true">
			<rect width="32" height="32" rx="7" fill={color.text} />
			<path d="M9 16.5l4.5 4.5L23 11.5" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
		</svg>
	</AbsoluteFill>
);

export const RemotionRoot: React.FC = () => (
	<>
		<Composition id="Launch" component={Launch} durationInFrames={LAUNCH_FRAMES} fps={30} width={1920} height={1080} />
		<Folder name="ProductHunt">
			<Composition id="Gallery1Hook" component={GalleryImage} durationInFrames={400} fps={30} width={1270} height={760} defaultProps={{scene: 'Hook'}} />
			<Composition id="Gallery2Approve" component={GalleryImage} durationInFrames={400} fps={30} width={1270} height={760} defaultProps={{scene: 'Approve'}} />
			<Composition id="Gallery3Prove" component={GalleryImage} durationInFrames={400} fps={30} width={1270} height={760} defaultProps={{scene: 'Prove'}} />
			<Composition id="Gallery4PullRequest" component={GalleryImage} durationInFrames={400} fps={30} width={1270} height={760} defaultProps={{scene: 'PullRequest'}} />
			<Composition id="Gallery5Issues" component={GalleryImage} durationInFrames={400} fps={30} width={1270} height={760} defaultProps={{scene: 'Issues'}} />
			<Composition id="Gallery6Numbers" component={GalleryImage} durationInFrames={400} fps={30} width={1270} height={760} defaultProps={{scene: 'Numbers'}} />
			<Still id="Thumbnail" component={Thumbnail} width={240} height={240} />
			<Still id="OgImage" component={OgImage} width={1200} height={630} />
		</Folder>
	</>
);
