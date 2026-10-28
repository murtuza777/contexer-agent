import {loadFont as loadGeist} from '@remotion/google-fonts/Geist';
import {loadFont as loadGeistMono} from '@remotion/google-fonts/GeistMono';

// One place for the name: if the product is renamed, change it here and re-render.
export const PRODUCT = 'Contexer';
export const REPO = 'github.com/murtuza777/contexer-agent';
export const INSTALL = 'pip install contexer-agent';

export const sans = loadGeist('normal', {weights: ['400', '500', '600'], subsets: ['latin']}).fontFamily;
export const mono = loadGeistMono('normal', {weights: ['400', '500'], subsets: ['latin']}).fontFamily;

// The website's palette (Tailwind zinc), with green as the only accent: it means "proven".
export const color = {
	page: '#ffffff',
	subtle: '#fafafa',
	border: '#e4e4e7',
	text: '#09090b',
	muted: '#52525b',
	faint: '#a1a1aa',
	term: '#09090b',
	termBorder: '#27272a',
	termText: '#e4e4e7',
	termDim: '#71717a',
	pass: '#047857',
	passOnDark: '#34d399',
	fail: '#b91c1c',
	failOnDark: '#f87171',
	warnOnDark: '#fbbf24',
};

// 100 BPM: a bar is 2.4 s, so every scene is a whole number of bars and cuts land on the beat.
export const FPS = 30;
export const BAR = 72;
