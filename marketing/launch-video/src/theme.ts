import {loadFont as loadInter} from '@remotion/google-fonts/Inter';
import {loadFont as loadMono} from '@remotion/google-fonts/JetBrainsMono';

// One place for the name: if the product is renamed, change it here and re-render.
export const PRODUCT = 'Contexer';
export const REPO = 'github.com/murtuza777/contexer-agent';
export const INSTALL = 'pip install "git+https://github.com/murtuza777/contexer-agent.git#subdirectory=contexer-agent"';

export const sans = loadInter('normal', {weights: ['400', '500', '600', '700', '800'], subsets: ['latin']}).fontFamily;
export const mono = loadMono('normal', {weights: ['400', '500', '700'], subsets: ['latin']}).fontFamily;

export const color = {
	bg: '#0A0E14',
	bgSoft: '#111722',
	panel: '#0F141C',
	border: '#243042',
	text: '#E6EDF3',
	muted: '#8B98A8',
	dim: '#5C6B7E',
	cyan: '#22D3EE',
	green: '#3FB950',
	red: '#F85149',
	amber: '#E3B341',
	magenta: '#D2A8FF',
	white: '#FFFFFF',
	github: '#0D1117',
	githubPanel: '#161B22',
	githubBorder: '#30363D',
};

// Facts from real runs, shown as they happened.
export const LIVE_RUN = {
	goal: 'Users can see how many notes are pinned',
	contract: 'users-can-see-how-many-notes',
	agent: 'opencode (openrouter/nvidia/nemotron-3-ultra-550b-a55b:free)',
	checks: [
		'Pinned count shows zero when no notes are pinned',
		'Pinning one note updates pinned count to 1',
		'Unpinning a note decrements pinned count back to zero',
		'Pinning multiple notes shows correct total pinned count',
		'Deleting a pinned note decrements pinned count',
		'Toggling pin on same note twice returns pinned count to original value',
		'Searching notes does not affect pinned count',
		'Pinned count updates immediately without page reload',
	],
	tools: [
		'glob **/*',
		'read index.html',
		'read app.js',
		'read style.css',
		'read .contexer/contracts/users-can-see-how-many-notes.json',
		'edit index.html',
		'edit app.js',
		'edit app.js',
		'read index.html',
		'read app.js',
	],
};

export const TODO_CHECKS = [
	'Adding a task shows it in the list',
	'The input is cleared after adding a task',
	'Submitting an empty task adds nothing',
	'The remaining count goes up with each task added',
	'Completing a task lowers the remaining count and raises no errors',
	'Deleting a task removes that task and keeps the others',
	'The app loads without uncaught exceptions or console errors',
];
