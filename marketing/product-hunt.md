# Product Hunt launch kit

Everything here is drawn from what Contexer does today and from measured
numbers (`contexer bench`, the live runs of 2026-10-26 and 27). Edit freely,
but keep the numbers as they are; reviewers check.

## Before you schedule

1. **The name.** The package is published as `contexer-agent`, because
   `contexer` on PyPI belongs to an unrelated, active project in the same
   space (contexer.ai, "MCP server that preserves decisions and context across
   AI coding sessions"). People may still confuse the two on Product Hunt and
   in search; a different product name would avoid that. The video takes its
   name from one constant: `PRODUCT` in `launch-video/src/theme.ts`.
2. **Approve the video.** The second cut is 69 seconds, built from real
   footage and a live run, with an original soundtrack and burned-in captions
   (see `launch-video/README.md`; render with `npm run music && npm run
   render`). Upload it to YouTube as public or unlisted, since Product Hunt
   embeds YouTube links only, with `out/captions.en.srt` (`npm run captions`)
   so YouTube can translate the captions. Check Remotion's licence first: it
   is free for individuals and companies of up to 3 people, larger companies
   need a company licence.
3. **Gallery**: `npm run gallery` writes `launch-video/out/gallery-*.png`
   (1270 × 760) and `out/thumbnail.png` (240 × 240).
4. **Put the website up.** `website/` builds as static pages; deploy it and
   set `SITE_URL` to its address (`website/README.md`).
5. **Try the install line on a clean machine** the day before (it worked on
   2026-10-26 from GitHub), following `contexer-agent/docs/try-it.md`:
   `uv tool install contexer-agent`. Publish to PyPI first (push the `v0.4.0`
   tag after the one-time setup in `.github/workflows/release.yml`).
6. Launch at 12:01 a.m. Pacific. Never ask for upvotes; ask people to try it
   and say what it caught.

## Name and tagline

Tagline (60 characters at most), pick one:

- Checks your AI agent's work in a real browser before merge (58)
- Proof that your AI coding agent's work is actually done (55)
- The AI engineer that owns "done" (32)

## Description (260 characters at most)

> Contexer sits on top of Claude Code, Codex and OpenCode. It turns a goal or a
> GitHub issue into checks you approve, has your agent build it, proves every
> check in a real browser, repairs failures, and opens a PR with the evidence.

(230 characters.)

## Topics

Developer Tools · Artificial Intelligence · GitHub · Open Source

## First comment (from the maker)

> Hi Product Hunt! 👋
>
> Coding agents now write code faster than anyone can check it, and they grade
> their own homework: "Done! Everything works." Often it doesn't.
>
> Contexer is the independent half. You describe what must be true (or label
> a GitHub issue), and it:
>
> 1. turns that into checks a browser can execute, and shows you how each one
>    fares on your app today, so you approve what "done" means;
> 2. has your coding agent build it (Claude Code, Codex or OpenCode);
> 3. starts your app and proves every check in Chromium. The agent's own
>    report never counts;
> 4. sends failures back with expected vs actual, rolls back attempts that
>    made things worse, and stops at a budget;
> 5. opens a pull request with the proof in it, and replays every approved
>    check on later pull requests as a merge gate.
>
> Measured, not claimed: on 7 fixture apps with 40 seeded bugs, hand-written
> contracts caught 40/40 with 0 false failures in 278 checks on correct code;
> contracts drafted from one-line goals by a free model caught 33/40. Method and
> per-run tables are in the repo.
>
> It runs locally, it's MIT licensed, and with an OpenRouter key the whole loop
> runs on free models (bring your own key for 13 other providers).
>
> [A sentence on why you built it.]
>
> I'd love to hear what it catches in your app, and where it gets in your way.

## Gallery captions

| Image | Caption |
| --- | --- |
| gallery-1-hook | The agent says it's done. The browser says otherwise. |
| gallery-2-approve | Your goal becomes checks you approve. |
| gallery-3-prove | Every check proven in Chromium, with repair when one fails. |
| gallery-4-pull-request | A pull request with the proof attached. |
| gallery-5-issues | Label an issue, approve in a comment, get a proven PR. |
| gallery-6-numbers | Measured on 7 apps with 40 seeded bugs. |

## Answers to the questions you will get

- **How is this different from the agent's own tests?** The agent that wrote
  the code does not decide whether it passed. Checks are approved by a person
  before any code changes, hashed so the agent cannot edit them, and run by
  Contexer in its own browser.
- **Does it need a paid model?** No. With an OpenRouter key it drafts and
  builds on free models (50 requests a day; about 15 for a small change).
  Drafts from a stronger model are better.
- **Which apps?** Web apps it can start: static sites, Vite, Next.js, or any
  start command in `contexer.toml`, including apps behind a login and apps
  with server-side data.
- **Does it send my code anywhere?** Only to the model provider you choose,
  through the coding agent you already use. Contexer runs on your machine or
  in your CI.
- **What doesn't it do yet?** Visual design checks, a GitHub App with an
  approve button, and a published accuracy number for paid drafting models.
