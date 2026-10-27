// Writes out/captions.en.srt from the same timeline and captions the video uses.
// Uploaded to YouTube with the video, it can be auto-translated for viewers in other languages.
import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';

const timeline = JSON.parse(readFileSync('src/timeline.json', 'utf-8'));
const captions = JSON.parse(readFileSync('src/captions.json', 'utf-8'));
const FPS = 30, BAR = 72;
const stamp = (frame) => {
	const ms = Math.round((frame / FPS) * 1000);
	const pad = (n, w = 2) => String(n).padStart(w, '0');
	return `${pad(Math.floor(ms / 3600000))}:${pad(Math.floor(ms / 60000) % 60)}:${pad(Math.floor(ms / 1000) % 60)},${pad(ms % 1000, 3)}`;
};
let at = 0, n = 0;
const blocks = [];
for (const scene of timeline) {
	const text = captions[scene.name];
	if (text) blocks.push(`${++n}\n${stamp(at + scene.captionAt)} --> ${stamp(at + scene.bars * BAR)}\n${text}\n`);
	at += scene.bars * BAR;
}
mkdirSync('out', {recursive: true});
writeFileSync('out/captions.en.srt', blocks.join('\n'));
console.log(`out/captions.en.srt: ${n} captions`);
