# Changelog

## Unreleased

From a goal or a GitHub issue to a pull request that carries its proof.

### Added

- **`contexer run --pr`** ends in a pull request: a branch
  `contexer/<contract>`, one commit with only the files the run changed and
  the approved contract, and a description that lists every check with its
  verdict, the regression replay, the attempts and the cost. Proven runs are
  ready for review; unfinished ones open as drafts that say what still
  fails. The checkout is checked before anything is spent.
- **`contexer run --issue N`** takes the goal from a GitHub issue; the pull
  request closes it.
- **Issues to pull requests on GitHub.** `contexer init --issues` adds a
  workflow: label an issue `contexer` and the checks are posted on it; a reply
  of `/contexer approve` from someone with write access builds, proves and
  opens the pull request, while one comment follows the run live. Also
  `contexer issue draft|build|event`, and the `murtuza777/contexer-agent/issue`
  action.
- **`contexer restore RUN --attempt N | --stopped | --undo`** brings back any
  snapshot a run took.
- `--agent scripted --model turns.json` replays file edits, to try a setup
  end to end without a model.
- `contexer setup` checks that Chromium starts and offers to install it, so
  a first run does not fail at its first check.

### Changed

- **One terminal design for every command.** No boxes, so output reads the
  same in a terminal, a CI log and an issue. Colour only means something:
  green proven, red refuted, yellow needs a person. Summaries are aligned
  key–value blocks with short paths. While the agent works, or the checks
  run, a live line shows the elapsed time and the tool calls so far.
  `contexer --help` groups commands by task and starts new users at
  `contexer setup`.

### Fixed

- **Ctrl+C** stops the coding agent at once. Before, Claude Code and Codex kept
  editing files after Contexer exited on Linux and macOS, and an OpenCode
  server kept working on the session. A stopped run puts back the best attempt
  or the project as it was, keeps the unfinished work, and exits 130.
- **OpenRouter's free limit.** `contexer run` reads how many free requests are
  left before it starts, stops when none are, and asks when fewer than 25
  are. When a limit stops a run anyway, the result says so and names the
  command that continues.
- `contexer run` in a home folder or a drive root is refused instead of
  snapshotting everything in it.
- A folder without an `index.html` (a bare `main.py`, say) is no longer taken
  for a static site; `contexer init` asks for its start command instead.
- `contexer init` printed "set .start there", dropping `[app]`.
- Long goals no longer cut a commit subject mid-word.

### Security

- Coding agents get no GitHub token in their environment, and the issue
  workflow checks out without stored credentials: issue text reaches the
  agent's prompt, and only Contexer pushes.
- Only the workflow's own comment counts as the drafted checklist; a comment
  that imitates it is ignored.

## 0.3.0 — 2026-10-26

Bring your own key, any of 14 providers, and the first live end-to-end runs:
a free model built features through OpenCode, and Contexer proved them,
including one that needed a repair round.

### Live runs (OpenCode + `nvidia/nemotron-3-ultra-550b-a55b:free`)

- **Signed-in members app, "delete a project":** built in 101 s, then 5/5 new
  checks and 6/6 existing ones passed with no repair.
- **React + Vite, "edit an expense":** the agent hung on its own
  `npm run dev &` until the 15-minute turn limit. Contexer proved its change
  anyway: 9/9, including the 6 existing checks.
- **Clean `pip install` from GitHub, then `contexer setup`, then `contexer run`:**
  2 of 8 checks failed on the first attempt. Contexer sent the evidence back,
  the agent repaired it, and the result was 8/8 in 111 s.

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
- On Windows, a launcher that starts its program at once (npm's
  `opencode.cmd`) escaped the kill-on-close job, so `opencode serve` kept
  running after Contexer stopped. Processes now start suspended until they
  are inside the job.
- A timed-out OpenCode turn is aborted, so the agent cannot keep editing
  files while Contexer checks them.
- A repair turn no longer re-lists the previous turn's OpenCode tool calls.

### Performance

- The GitHub Action caches Chromium and skips `apt` when the browser already
  starts (it does on GitHub's Ubuntu images). The gate went from about 10
  minutes to 37 s on this repository.

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
