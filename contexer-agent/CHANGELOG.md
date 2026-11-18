# Changelog

## Unreleased

Work on the [agentic harness](docs/agentic/architecture.md) starts here.
Phase 0 adds the foundations; no agent ships yet.

### Added

- **Guardrails**, built on one rule: assume the model is compromised. A
  page, a file or a saved skill can carry text written to steer it, so each
  guardrail is a property of the code, tested with a scripted model that
  does what an attacker wants (`tests/test_guardrails.py`,
  `docs/agentic/hardening.md`).
  - **A budget per run**, shared by every agent: `[limits] tokens` and
    `cost_usd` in `contexer.toml`, `contexer test --max-tokens N`, default
    1,500,000 tokens. A run that reaches it stops calling the model; what
    was found is still replayed and the fix prompt is written from the
    facts. `result.json` lists what each agent used.
  - At most 25 tool calls are run from one reply, and the same call four
    times in a row is refused.
  - **The browser stays on the app.** `goto` to another origin is refused;
    an action that leaves the app's origin is undone and not recorded;
    pop-ups are closed.
  - `contexer test --url` to a host that is not this machine or a private
    network needs `--allow-remote`: the Tester clicks and submits for real.
  - The Diagnoser's brief is validated before it reaches the fix prompt
    (files must exist inside the project; cause and instruction are
    capped), and the prompt tells the coding agent what a model-written
    section may not ask for.
  - Skills are capped in size and number, `--no-skills` ignores them, and
    whatever a run adds to the intent is printed.
  - Text from the app is marked as untrusted in every prompt.
  - The tamper guard covers `contexer.toml` as well: it names the command
    Contexer runs to start and reset the app.
- A tool audit in `docs/architecture.md`, enforced by a test: which agent
  has which tool, and that none of them can write to the project.
- A held-out benchmark app, `bookings`, that no prompt was tuned on. **It
  showed that the Tester's zero false alarms did not generalise: 3 of 6
  bugs found, and a bug reported on correct code in 2 of 4 runs.** Two
  guards were added because of it and it was measured again: 0 false
  alarms in 4 runs, still 3 of 6 found. `bench/RESULTS.md` has all three
  measurements and why the last two are not held-out evidence.
  - **The Challenger**: after replay, one model call reviews each
    confirmed bug and can set it aside as the tester's doing, with a
    reason that is shown. It can only remove.
  - **When the app said why**: a failed check records the messages the
    app is showing. A bug whose check failed while the app displayed a
    message is listed for you with that message and not reported as a
    bug. Decided by code, with no model.
- `ruff` and `pyright` run in CI before the tests. The package is type-clean on Windows, Linux and
  macOS, and modules no longer call each other's private functions.
- **The loop without a coding agent in the middle.** `contexer test` now
  understands the goal, tests against it, and writes the fix prompt; you
  paste the prompt into any coding tool and run `contexer test --again`.
  - **Intent** (`.contexer/intent/<feature>.md`): the goal, the behaviours
    derived from it, your corrections and the assumptions taken, as
    Markdown you can edit and commit. The Intent agent asks at most 3
    questions, each only where two readings of the goal would be tested
    differently; `--yes` takes the likeliest reading and records it.
    `--correct "deleting should ask first"` records a correction, updates
    only the checks it affects, and tests again. The tamper guard covers
    the intent like a contract.
  - **Fix prompt** (`fix-prompt.md`, printed, `--copy` for the clipboard):
    the Diagnoser reads the project (read-only) for the likely cause. The
    facts in the prompt (steps, expected, actual, exceptions) are inserted
    by code from the replay, word for word; the cause is labelled a
    hypothesis. With no cause found the prompt is still complete.
  - **`--again`**: replays the checks the last run confirmed, with no model.
    If any still fails it says which and stops; if all pass it explores.
  - **Project skills** (`.contexer/skills/<name>.md`): up to 3 things per
    run the Tester learned about operating the app, given to later runs as
    advice. A skill containing a secret is refused.
  Live on the demo app with Azure `gpt-5.4`: 3 bugs confirmed, a fix prompt
  naming the `refesh()` typo, a one-line fix by a coding agent from the
  pasted prompt, and `--again` green on all 6 saved checks. The skills
  measurement did not show fewer Tester steps on a second run (28 and 28);
  see `docs/agentic/phase-2.md`.
- **`contexer test "what the app should do"`**: the Tester agent uses your
  running app in a real browser against the intent you state, then every
  finding is replayed by code in a fresh browser. Only findings that
  reproduce are shown: confirmed bugs, confirmed working behaviours, and a
  count of the ones that did not reproduce. No coding agent is involved and
  nothing in the project is changed. Options: `--url`, `--steps`, `--model`,
  `--provider`, `--save` (keep the confirmed checks as a draft contract),
  `--json`, `--open`. Exit codes: 0 no confirmed bugs, 1 confirmed bugs,
  2 could not test, 3 error, 130 stopped with Ctrl+C.
- **Azure AI Foundry** as a provider (`azure`): set `AZURE_OPENAI_API_KEY`,
  `AZURE_OPENAI_ENDPOINT` and use your deployment name as the model. The
  endpoint is accepted however the portal showed it. Azure and OpenAI are
  sent `max_completion_tokens`; Azure's current models refuse `max_tokens`.
- The Tester reports behaviour the intent does not mention (does data
  survive a reload?) as **questions**, shown apart from the bugs. A live run
  had reported one as a bug; only a broken stated behaviour or an outright
  failure is a bug.
- `reset` returns the fresh page, so the Tester does not spend a step asking
  for it, and the Tester tests a behaviour that acts on one item of a list
  with at least two items. With one task in the list, a delete that removes
  the wrong task looked correct.
- **Browser tools** (`browser/tools.py`, `browser/recorder.py`): `snapshot`,
  `click`, `fill`, `press`, `select`, `check`, `uncheck`, `hover`, `goto`,
  `read_errors`, `screenshot`, `expect` and `reset`, on one page that reuses
  the project's sign-in. They are the verbs of the check language and act
  through the code that replays checks, so every action is recorded as a
  `Step` and every `expect` as a replayable observation. A target that
  matches nothing comes back as an error with the page's snapshot; typed
  passwords are masked in what the model reads and in the transcript.
- **The Tester** (`crew/tester.py`, `crew/prompts/tester.md`): tests each
  stated behaviour and then the edge cases (empty input, twice, undo, reload,
  signed out). A finding points at one `expect` result; code copies the steps
  and the expectation from the recording and refuses a finding the
  observation does not support. Findings recorded before a step or time
  limit are kept.
- **Freeze and replay** (`browser/freeze.py`): a finding becomes a `Check`
  and is replayed twice with `CheckRunner`. A bug is confirmed when its check
  is refuted both times, a working behaviour when it passes both times;
  anything else goes to `unconfirmed.json` with the reason. Confirmed checks
  form a draft contract.
- `contexer bench --suite tester --agent tester` measures the Tester on the
  seeded bugs. **First numbers, Azure AI Foundry `gpt-5.4`, 2026-11-17: 25
  of 40 seeded bugs found, 0 false alarms in 22 runs on correct code**, 11
  findings rejected because the correct app fails their check too, 14.0M
  input tokens. One run per variant. Detail and the reasons for each miss
  are in `bench/RESULTS.md`.
- The tester benchmark counts a finding on a seeded bug that the correct app
  also fails as **rejected**, apart from a **false alarm** (a finding on
  correct code).
- **Chat models that can call tools** (`llm/chat.py`). `chat_model(provider,
  model)` builds a LangChain chat model for every provider in the catalog,
  with the same keys and precedence rules as the drafting model: one class
  for all OpenAI-compatible providers, Anthropic's own for Anthropic. New
  dependencies: `langchain-core`, `langchain-openai`, `langchain-anthropic`
  (and through them `anthropic` and `tiktoken`); `openai` is now 2.45 or
  newer. LangChain is imported only when an agent runs.
- **`run_agent`** (`crew/base.py`): the one loop every Contexer agent runs
  in. Model call, tool calls, results, repeat, until the model hands in an
  answer that fits the agent's schema or a limit set in code is reached
  (steps, time, output tokens, two corrections of an invalid answer). A tool
  that raises is an error result for the model, not the end of the run.
  `tests/fakes.py` has the scripted chat model the agent tests use.
- **Agent transcripts** (`crew/transcript.py`): `agents/<name>.jsonl` in the
  run folder, one line per model call and tool call with timing and token
  counts. Secrets are masked with the checks' redaction, in the transcript
  and in tool results before the model reads them.
- Optional Langfuse tracing: `pip install "contexer-agent[tracing]"` and set
  `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`. Without them the package
  is never imported and nothing leaves the machine.
- **The tester benchmark**: `contexer bench --suite tester --agent stub`. An
  agent gets each fixture app's goal (not its contract) and the running app;
  its findings are replayed by code. A bug counts as found only when the
  finding fails on the buggy app and passes on the correct one; a finding
  that fails on correct code is a false alarm; one that does not reproduce
  is dropped and counted. The stub agent reports nothing, so the suite runs
  with no model: 0 of 40 found, 0 false alarms. Results are written to
  `bench/tester-results/`. `contexer bench` without `--suite` is unchanged.
- `contexer doctor` says whether the model in use can call tools, from the
  provider's own model list. A model that cannot gets an error that names it.
- A link checker for the Markdown in this repository
  (`pytest tests/test_docs_links.py`): relative links and heading anchors,
  no network.

### Removed

- **The interactive shell.** `contexer` with no command now prints the help.
  The shell was an earlier, separate chat agent (adapted from AgentForge)
  that no command used; Contexer drives Claude Code, Codex and OpenCode
  instead. Removed with it: `runtime/`, `tools/`, `safety/`, `state/`,
  `context/`, `mcp/`, `project/`, the shell's settings
  (`CONTEXER_APPROVAL_POLICY`, `CONTEXER_REDACT_TOOL_OUTPUT`,
  `CONTEXER_PROTECT_TOOL_OBSERVATIONS`, `CONTEXER_MAX_TOOL_OUTPUT_CHARS`,
  `GITHUB_PERSONAL_ACCESS_TOKEN`, `GITHUB_TOOLSETS`, `GITHUB_READ_ONLY`,
  `LOG_LEVEL`, `VERBOSE`, `OPENCODE_TIMEOUT`), and the streaming and
  tool-calling code in the model providers, which only the shell used.

### Fixed

- **Security: Next.js 16.4.6** in the website and in the `guestbook-next` benchmark fixture. The website
  was on 16.3.5, inside the range of a critical advisory and several others; its production
  dependencies now audit clean. The fixture was on 16.4.2 (GHSA-mfr8-8qww-v76h, GHSA-vc7v-qv4w-wrv8).
  Dependabot now watches npm in the website and both JavaScript fixtures; before, nothing did.
- The Tester sees the email or user name of the test account again. Every
  value the sign-in typed was masked, which turned "Welcome,
  demo@example.com" into dots and hid a page that greets the member by email
  instead of by name. Only passwords, tokens and one-time codes are masked.
- A bug must say which words of the intent it breaks (`violates`), and code
  checks that the quote is in the intent; the one exception is a failed
  `no_errors`. This closes the gap that let "I would have built it
  differently" through as a bug.
- `expect` accepts `count` with `equals`, which is how models write it.
- A console line about a request the server refused (HTTP 400 on empty
  input) is no longer a crash. On the guestbook fixture it was reported as a
  bug on the correct app; only an uncaught exception counts.
- The tester benchmark survives an agent that fails on one variant; that run
  is reported and not scored.
- An app started by Contexer no longer inherits the markers of an agent
  session (`AI_AGENT`, `CLAUDECODE`, `CLAUDE_CODE_*`). Started from a coding
  agent's terminal, Next.js stopped `next dev` to show an upgrade notice and
  the app "did not start".

### Changed

- Docs: product research is in `docs/product/`, and the LangGraph study sits
  with the multi-agent plans as `docs/multi-agent/langgraph-port.md`. The raw
  research notes are gone; the market research report keeps their findings.
- Docs: `docs/roadmap.md` and the product plan no longer describe the removed
  interactive shell or `workflow/loop.py` as existing.

## 0.4.0 — 2026-10-28

From a goal or a GitHub issue to a pull request that carries its proof, a
terminal and a website that show only what is real, and the problems the
first live runs exposed, fixed.

### Packaging

- **Packaged for PyPI as `contexer-agent`** (`uv tool install contexer-agent`,
  `pipx install contexer-agent` or `pip install contexer-agent`); the command
  is still `contexer`. `contexer` on PyPI is a different project. The package
  is published when the `v0.4.0` tag is pushed; until then, install from
  GitHub.
- An MIT `LICENSE`, shipped in the wheel with the third-party notices, and a
  PyPI page (`PYPI.md`).
- `release.yml` builds and checks the package on every push and publishes it
  on a version tag through PyPI trusted publishing.
- `docs/architecture.md`: every module, data format, algorithm, constant and
  security measure in one technical reference.
- The guide covers Windows install failures: a `pip` launcher left by an
  uninstalled Python, and `contexer` "not recognized".

### Live run (OpenCode + `nvidia/nemotron-3-ultra-550b-a55b:free`, 2026-10-27)

- **The todo app's counting bug, with `--pr`:** the agent read four files and
  fixed the count in `app.js` in 81 s; Contexer proved 7/7 checks, committed
  only `app.js` to `contexer/todo-basics` and pushed it, in 91 s. The remote
  was local, so no pull request was opened on GitHub yet.

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
- **Docs:** `docs/try-it.md` walks a user through install, setup, the demo and
  a first run on their own app, saying what each step should show, and a
  developer through the tests, the benchmark and the scripted agent.
- **Website:** `website/`, rewritten to show real output only (the old page
  promised installers that do not exist and called working agents
  "upcoming").

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
- With `--dir` pointing at another project, keys saved by `contexer setup`
  beat that project's `.env`; the project's `.env` now wins, and an exported
  variable still wins over both.
- The website's `src/lib/site.ts` was hidden by the root `.gitignore`, so a
  fresh clone of the website did not build.

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
