# Changelog

## Unreleased

### Added

- **Bring your own key.** `contexer setup` picks a provider, takes your key
  without echoing it, lets you choose a drafting model from the provider's
  own list, and tests that model with one real request before saving
  anything. Supported: OpenRouter (free models included), Anthropic, OpenAI,
  Google Gemini, Groq, DeepSeek, Mistral, Together AI, xAI, Fireworks,
  Cerebras, NVIDIA, a local Ollama, and any OpenAI-compatible endpoint.
  Settings and keys live in `~/.contexer/`, never in a project, and the coding
  agent inherits the key: Claude Code for Anthropic, Codex for OpenAI,
  OpenCode for the rest. `contexer setup --show` prints them with keys masked.
- **`contexer models`** lists a provider's models with context size, free
  models and tool support, plus `--free` and `--search` filters.
  `--providers` lists every provider and the keys you already have.
- Every draft names the model that wrote it, and warns when a router or
  fallback answered instead of the model that was asked for.

- **Codex.** `contexer run --agent codex` (or `[agent] name = "codex"`) drives
  `codex exec --json` in the `workspace-write` sandbox, resumes the same
  thread for repair turns, and reports progress and edited files. Codex
  reports no cost, so `--budget` does not apply to it.
- **`[app] reset`**, a command run before every check that puts server-side
  data back, because checks share the app's database. A failing reset blocks
  its check instead of refuting it. The drafting guide also asks for unique
  names for created items.
- **Benchmark:** `guestbook-next`, a Next.js 16 app whose entries live on the
  server, started through `npm ci` and `next dev`.
- **Free end-to-end runs.** With only `OPENROUTER_API_KEY`,
  `contexer run "GOAL" --agent opencode` uses
  `openrouter/nvidia/nemotron-3-ultra-550b-a55b:free`. The first live run
  (2026-10-26) built a feature in a signed-in app that passed all 5 new
  checks and the 6 existing ones. Tested with OpenCode 1.4.3 and 1.19.4.
- **OpenCode progress.** Each tool call (`read app.js`, `edit app.js`,
  `bash npm test`) is shown while the turn runs, instead of only "working".

### Changed

- **Drafting default.** With an OpenRouter key, drafts now come from
  `nvidia/nemotron-3-ultra-550b-a55b:free` instead of `openrouter/free`. That
  model caught 33/40 seeded bugs with 0/164 false failures across 7 apps,
  where the router varied between 25% and 83% per run. It falls back to the
  router when unavailable. `OPENROUTER_MODEL` still overrides it.
- For apps started with their dev server, the first load waits up to 60 s and
  checks wait 2.5× longer, because pages and API routes compile on first use.
- The coding agent is told not to install browsers or run its own end-to-end
  tests; Contexer runs the checks.

### Fixed

- On Windows, a configured command with a quoted path (for example
  `"C:\Program Files\nodejs\node.exe" app.js`) failed with "is not
  recognized", because `cmd.exe` cannot read `\"`-escaped quotes.
- `--agent opencode` without `--model` used OpenCode's own free model,
  which refuses headless use.
- The project's `.env` is loaded before drafting and before the coding agent
  starts, so a model key kept there reaches both, also with `--dir`.

## 0.2.0 — 2026-10-25

Real projects: apps behind a login, React and Vite through their own dev
server, a choice of drafting model, and a setup check.

### Added

- **Apps behind a login.** `[auth]` in `contexer.toml` describes the sign-in
  flow in the check DSL. Contexer signs in once per run and starts every check
  signed in; `"login": false` runs a check as a signed-out visitor. `${NAME}`
  values come from the environment or the project's `.env`.
- **Draft preview.** `contract draft` and `run "GOAL"` try the drafted checks
  on the app as it is and show, before approval, which already pass, which
  fail (expected vs actual) and which cannot run yet.
- **Drafting model choice.** Anthropic, OpenAI or OpenRouter, chosen by
  `[compiler]` in `contexer.toml`, `CONTEXER_LLM_PROVIDER`, or the first key
  set.
- **`contexer doctor`.** Checks Python, Chromium, git, Node, the drafting
  model, coding agents, the project's start command, its contracts and its
  sign-in secrets, and prints the fix for each problem.
- **Benchmark:** a signed-in `members` app and a React 19 + Vite 8
  `budget-react` app started through `npm ci` and its dev server. 35/35
  seeded bugs caught across six apps, 0/248 false-failing checks.

### Changed

- Dependencies install from the lockfile exactly (`npm ci`,
  `pnpm install --frozen-lockfile`), so a gate run never rewrites it, and are
  reinstalled when an agent changes `package.json` or a lockfile.
- A missing Chromium is reported as the install command instead of "app
  unreachable".
- The benchmark starts every fixture the way `contexer verify` starts a
  project. A clean run whose app does not start now counts as a false
  failure, and a bug that stops the app counts as flagged, not missed.

### Security

- Password fields and typed `${NAME}` values are masked in `result.json`,
  `report.html` and the repair prompts sent to the coding agent's model.
  Playwright's ARIA snapshot used to include them.
- Signed-in checks keep no Playwright trace unless `--trace on` is passed,
  because a trace records the session cookie and CI uploads traces.

### Fixed

- When an agent's change broke the app without stopping it (for example the
  sign-in flow), the repair prompt said nothing about why no check ran.
- A failed dev-server restart after a revert aborted the whole run.

## 0.1.0 — 2026-10-16

The acceptance gate: contracts compiled from a goal and approved by a person
(sha256), proven in Chromium, a bounded repair loop over Claude Code or
OpenCode with snapshots, keep-best and a tamper guard, regression replay, a
`contexer/acceptance` commit status and a reusable GitHub Action, the
self-contained HTML report, and the seeded-bug benchmark.
