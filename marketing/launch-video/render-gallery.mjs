// Renders the Product Hunt gallery images, the thumbnail and the website's social card into out/.
import {execFileSync} from 'node:child_process';

// Composition id → [file name, the frame that tells the story].
const stills = {
	Gallery1Hook: ['gallery-1-hook', 200],
	Gallery2Approve: ['gallery-2-approve', 275],
	Gallery3Prove: ['gallery-3-prove', 350],
	Gallery4PullRequest: ['gallery-4-pull-request', 200],
	Gallery5Issues: ['gallery-5-issues', 200],
	Gallery6Numbers: ['gallery-6-numbers', 120],
	Thumbnail: ['thumbnail', 0],
	OgImage: ['og', 0],
};

for (const [id, [file, frame]] of Object.entries(stills)) {
	execFileSync('npx', ['remotion', 'still', id, `out/${file}.png`, `--frame=${frame}`, '--log=error'], {stdio: 'inherit', shell: true});
	console.log(`out/${file}.png`);
}
