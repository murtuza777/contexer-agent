# Contexer

**Proof that your coding agent is actually done.**

Contexer sits on top of the coding agents you already use: Claude Code, Codex
and OpenCode. It turns a goal (or a GitHub issue) into checks you approve, has
your agent build it, runs every check in a real browser, repairs failures in
a bounded loop, and hands you a pull request with the evidence. Every check
you approve then replays on later changes, with no model involved.

## Install

```bash
uv tool install contexer-agent      # or: pipx install contexer-agent
```

`pip install contexer-agent` works too. The command is `contexer`; the
package name differs because `contexer` on PyPI is a different project.
Python 3.11 or newer.

## Start

```bash
contexer setup        # a provider, your key and models, tested live; installs Chromium
contexer demo --fix   # see it catch a bug and repair it, with no key needed
contexer run "Users can export their data as CSV" --pr    # in your app's folder
```

With an OpenRouter key, drafting and building run on free models. `contexer
setup` also supports Anthropic, OpenAI, Gemini, Groq, DeepSeek, Mistral,
Together AI, xAI, Fireworks, Cerebras, NVIDIA, a local Ollama and any
OpenAI-compatible endpoint.

## What a run does

1. Starts your app (static, Vite, Next.js, or a start command in
   `contexer.toml`), drafts checks from the goal, and tries them on the app as
   it is.
2. You approve the checks. They are hashed; an agent that edits them has its
   run refuted.
3. Your coding agent builds the change. Its own report never counts.
4. Contexer runs every check in Chromium, sends failures back with expected
   vs actual, rolls back attempts that made things worse, and stops at a
   fixed number of rounds or a budget.
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
