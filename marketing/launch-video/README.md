# Contexer launch video

A 69-second launch video, its Product Hunt gallery images and the website's
social card, made with [Remotion](https://www.remotion.dev) following
Remotion's own agent skill ([remotion-dev/skills](https://github.com/remotion-dev/skills)).
Second cut; not final.

Everything on screen comes from real material:

- `public/check-bug.mp4` and `public/check-fixed.mp4`: Playwright recordings of
  Contexer's own check run on the todo app, buggy ("2 left") and fixed
  ("1 left"), slowed down so a viewer can follow them;
- `src/data.json`: the approval screen printed by Contexer's terminal renderer,
  and a live run (OpenCode with a free model, 2026-10-27) with each line's real
  time, plus the pull request and issue content that run produces;
- the numbers, from `contexer bench`.

The soundtrack is original, composed in code: `music/compose.mjs` writes
`public/music.wav` and the sound cues (100 BPM, so a bar is 72 frames and cuts
land on bar lines).

```bash
npm ci
npm run music                  # public/music.wav and public/sfx-*.wav
npm run studio                 # preview and edit in Remotion Studio
npm run render                 # out/contexer-launch.mp4 (1920 × 1080, 30 fps, AAC audio)
npm run captions               # out/captions.en.srt, for YouTube (it can translate them)
npm run gallery                # out/gallery-*.png (1270 × 760), out/thumbnail.png, out/og.png
```

## Licence

Remotion is not MIT. Its free licence covers individuals, non-profits and
for-profit companies with up to 3 employees; a larger company needs a
Remotion company licence (`node_modules/remotion/LICENSE.md`,
https://www.remotion.dev/license). The soundtrack and sound cues are
original, made by `music/compose.mjs`, so they need no licence.

## Editing

The product name is one constant, `PRODUCT` in `src/theme.ts`. Scene lengths
(in bars) and caption timings are in `src/timeline.json`, the captions in
`src/captions.json`, and the scenes in `src/scenes.tsx`.
