# Contexer launch video

A 60-second Product Hunt video and its gallery images, made with
[Remotion](https://www.remotion.dev) following Remotion's own agent skill
([remotion-dev/skills](https://github.com/remotion-dev/skills)).

Everything on screen comes from real output:

- the refuted check, its expected vs actual and the report are from
  `contexer demo`;
- the checklist, the agent's tool calls, the 6-of-8 first attempt and the
  8-of-8 repair (111 s) are from a live run on 2026-10-26 with OpenCode and a
  free OpenRouter model;
- the pull request and the issue comments render what `--pr` and the issue
  workflow write, for those runs;
- the numbers are from `contexer bench`.

```bash
npm ci
npm run studio                 # preview and edit in Remotion Studio
npm run render                 # out/contexer-launch.mp4 (1920 × 1080, 30 fps)
npm run gallery                # out/gallery-*.png (1270 × 760) and out/thumbnail.png
```

The product name is one constant, `PRODUCT` in `src/theme.ts`. Scene lengths
are in `src/Launch.tsx`, and the scenes in `src/scenes.tsx`.
