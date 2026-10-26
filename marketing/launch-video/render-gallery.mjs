// Renders the Product Hunt gallery images and thumbnail into out/.
import {execFileSync} from 'node:child_process';

// Composition id → [file name, the frame that tells the story].
const stills = {
	Gallery1Hook: ['gallery-1-hook', 110],
	Gallery2Approve: ['gallery-2-approve', 200],
	Gallery3Prove: ['gallery-3-prove', 295],
	Gallery4PullRequest: ['gallery-4-pull-request', 200],
	Gallery5Issues: ['gallery-5-issues', 235],
	Gallery6Numbers: ['gallery-6-numbers', 120],
	Thumbnail: ['thumbnail', 0],
};

for (const [id, [file, frame]] of Object.entries(stills)) {
	execFileSync('npx', ['remotion', 'still', id, `out/${file}.png`, `--frame=${frame}`, '--log=error'], {stdio: 'inherit', shell: true});
	console.log(`out/${file}.png`);
}
