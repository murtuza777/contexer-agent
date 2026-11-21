# Contexer

**Proof that your coding agent is actually done.**

Contexer sits on top of the coding agents you already use: Claude Code, Codex
and OpenCode. It turns a goal (or a GitHub issue) into checks you approve, has
your agent build it, runs every check in a real browser, repairs failures in
a bounded loop, reads the diff, and hands you a pull request with the
evidence. Every check you approve then replays on later changes, with no
model involved.

It also tests what an agent already built: `contexer test "what the app
should do"` uses your running app like a person, reports only what a replay
by code confirms, and writes the fix prompt to paste into any coding tool.

## Install

```bash
uv tool install contexer-agent      # or: pipx install contexer-agent
```

`pip install contexer-agent` works too. The command is `contexer`; the
package name differs because `contexer` on PyPI is a different project.
Python 3.11 or newer.

## Start

```bash
contexer demo         # no key needed: a todo app with a bug, caught in ten seconds
contexer setup        # a provider, your key and models, tested live
contexer test "Users can add tasks and complete them, and the count stays correct"   # in contexer-demo/
contexer run "Users can export their data as CSV" --pr    # in your app's folder
```

A new install has no browser yet: the demo offers to download Chromium, and
`contexer setup --browser` does it on its own. With an OpenRouter key,
drafting and building run on free models. `contexer
setup` also supports Anthropic, OpenAI, Gemini, Groq, DeepSeek, Mistral,
Together AI, xAI, Fireworks, Cerebras, NVIDIA, a local Ollama and any
OpenAI-compatible endpoint.

## What a run does

1. Starts your app (static, Vite, Next.js, or a start command in
   `contexer.toml`), writes down what it understood, drafts checks from the
   goal, and tries them on the app as it is.
2. You approve the checks. They are hashed; an agent that edits them has its
   run refuted.
3. Your coding agent builds the change. Its own report never counts.
4. Contexer runs every check in Chromium, sends failures back with expected
   vs actual, rolls back attempts that made things worse, and stops at a
   fixed number of rounds or a budget. A passing change is read once for
   what a check cannot see: a secret, a deleted test, a removed confirmation.
5. With `--pr`, it ends in a pull request whose description lists every check
   and its verdict.

On GitHub, `contexer init --ci` replays approved checks on every pull request
as a required status, and `contexer init --issues` turns a labelled issue
into a proven pull request after you approve its checks in one comment.

## Links

- Source and full README: https://github.com/murtuza777/contexer-agent
- Step-by-step guide: https://github.com/murtuza777/contexer-agent/blob/main/contexer-agent/docs/try-it.md
- Architecture: https://github.com/murtuza777/contexer-agent/blob/main/contexer-agent/docs/architecture.md
- Changelog: https://github.com/murtuza777/contexer-agent/blob/main/contexer-agent/CHANGELOG.md

MIT licensed.
