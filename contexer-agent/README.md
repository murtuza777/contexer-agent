# Contexer (Python package)

This is the developer guide. The product overview is in the
[repository README](../README.md); [Try it yourself](docs/try-it.md) is the
step-by-step guide for users.

## Setup

```bash
cd contexer-agent
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
contexer setup        # a provider, your key and models, tested live; offers to install Chromium
```

Then run `contexer doctor`. It checks Python, Chromium, git, Node, the
drafting model, coding agents, OpenRouter's free requests left today and the
project in `--dir`, and prints the fix for anything missing.

**Models:** `contexer setup` saves a provider, key and models for every
project in `~/.contexer/` (any of 14 providers: `contexer models --providers`).
Exported variables, a project's `.env` and its `contexer.toml` take precedence.
Without setup, set one of `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY` or `OPENROUTER_API_KEY` in the environment or `.env` (see
`.env.example`). With several keys set, the first in that order is used;
`CONTEXER_LLM_PROVIDER` or `[compiler]` in `contexer.toml` picks one
explicitly. Draft quality depends on the model, so prefer a strong one (the
Anthropic default is `claude-opus-5-5`). With only an OpenRouter key, drafts
come from the free `nvidia/nemotron-3-ultra-550b-a55b:free` (33/40 seeded bugs
caught in `bench --live`), falling back to `openrouter/free` when it is
unavailable; `OPENROUTER_MODEL` overrides it. Replaying approved contracts
never calls a model.

**Optional, for `contexer run`:** a coding agent on `PATH`:

| Agent | Requirement |
| --- | --- |
| [Claude Code](https://code.claude.com) (`claude`) | Logged in, or `ANTHROPIC_API_KEY` set |
| [Codex](https://github.com/openai/codex) (`codex`) | `codex login`, or `CODEX_API_KEY` set. Runs in the `workspace-write` sandbox with network on. Codex reports no cost, so `--budget` doesn't apply; rounds and the time limit still do |
| [OpenCode](https://opencode.ai) (`opencode`, `npm i -g opencode-ai`) | With `OPENROUTER_API_KEY` set and no model chosen, it uses the free `openrouter/nvidia/nemotron-3-ultra-550b-a55b:free`; otherwise `--model provider/model` or `OPENCODE_MODEL_PROVIDER`/`OPENCODE_MODEL_ID`. OpenCode's own free models refuse headless use. Tested with 1.4.3 and 1.19.4 |

## Commands

Every command takes `--dir PATH` (default: the current directory) and
`--url URL`. Use `--url` when you already run the app; otherwise Contexer
serves static sites itself and starts the project's dev server.

The same groups as `contexer --help`:

| Command | What it does |
| --- | --- |
| **Get started** | |
| `contexer setup [--show]` | Bring your own key: a provider, models and a coding agent, tested live and saved for every project |
| `contexer demo [--fix]` | Create a todo app with a seeded bug and prove its contract; no key or agent needed |
| `contexer doctor` | Check everything Contexer needs, with the fix for each problem |
| `contexer init [--ci] [--issues]` | Detect how the app starts and prepare `.contexer/`; `--ci` writes the gate workflow, `--issues` the issue workflow |
| **Build and prove** | |
| `contexer run "GOAL"` / `--contract ID` | Approve the checklist, drive the coding agent, prove, repair, and keep the best attempt |
| `contexer run ... --pr` / `--issue N` | End in a pull request with the evidence; with `--issue` the goal comes from the issue and the PR closes it |
| `contexer verify "GOAL"` | Compile a goal into a draft contract grounded in the running UI, then prove it |
| `contexer verify --contract ID` / `--all` | Prove saved contracts; no LLM calls |
| `contexer contract draft "GOAL"` / `list` / `show ID` | Create and review contracts |
| `contexer contract approve ID` | Lock a contract at its current content (sha256). Any later edit needs re-approval |
| `contexer runs` | Recent runs with outcome, check counts and report paths |
| `contexer restore RUN --attempt N` / `--stopped` / `--undo` | Put the files back to a snapshot a run took |
| **CI and GitHub** | |
| `contexer replay [--github]` | `verify --all` for CI. `--github` posts a `contexer/acceptance` commit status |
| `contexer issue draft N` / `build N --by LOGIN` / `event` | Post an issue's checks for approval; build them once approved; in Actions, act on the triggering event |
| **More** | |
| `contexer models [--provider P] [--free] [--search S]` | A provider's models; `--providers` lists every provider and the keys you have |
| `contexer bench [--live]` | Seeded-bug benchmark: catch rate and false-failure rate |
| `contexer` | The interactive shell (`/loop`, `/verify`, `/project`, ...) |

Useful options:

- `--trace on-failure` keeps Playwright traces for failing checks.
- `--json` prints `result.json`.
- `--open` opens the HTML report.
- `run` also takes `--agent`, `--model`, `--rounds`, `--budget` and `--yes`.
  `--agent scripted --model turns.json` replays file edits from a JSON list,
  to try a setup end to end without a model.

**Exit codes:** `0` pass · `1` fail (a check was refuted) · `2` needs action
(unverified check, draft or modified contract, budget or time exhausted) ·
`3` error (app or agent could not run) · `130` stopped with Ctrl+C (the agent
is stopped and the project put back; `contexer restore RUN --stopped` brings
the unfinished work back).

## Project files

```text
<project>/
  contexer.toml                 optional settings (below)
  .contexer/
    contracts/<id>.json          approved contracts: commit these
    .gitignore                   written by Contexer; keeps everything else local
    runs/<run-id>/               report.html, result.json, run.json, screenshots,
                                 traces, server.log, attempt-N/
    shadow.git/                  private snapshot repository used by `run`
```

```toml
# contexer.toml
[app]
start = "npm run dev -- --port {port}"   # default: package.json dev/start script
port = 5173                              # default: a free port
ready_path = "/"
ready_timeout = 120
install = true                           # npm ci (lockfile) / npm install when node_modules is missing,
                                         # and again when an agent changes dependencies
reset = "npm run db:reset"               # before every check (see below); {url} and {port} are filled in

[auth]                                   # sign in before checks (see below)
url = "/login"
steps = [
  { action = "fill", target = { label = "Email" }, value = "${CONTEXER_TEST_EMAIL}" },
  { action = "fill", target = { label = "Password" }, value = "${CONTEXER_TEST_PASSWORD}" },
  { action = "click", target = { role = "button", name = "Sign in" } },
]
expect = [{ kind = "url", contains = "/dashboard" }]

[compiler]
provider = "anthropic"                   # any id from `contexer models --providers`; default: `contexer setup`, then the first key set
model = "claude-opus-5-5"

[gate]
judged = "advisory"                      # or "block"

[agent]
name = "claude-code"                     # or "codex", "opencode"
max_repair_rounds = 2
budget_usd = 3.0
```

### Apps behind a login

With `[auth]`, Contexer runs the sign-in steps once per verification and starts
every check from that signed-in browser state (cookies and local storage, kept
in memory only). Use a dedicated test account:

- `${NAME}` values are read from the environment (CI secrets) or the project's
  `.env` at run time. They are never written to contracts. Typed `${NAME}`
  values and password fields are masked in `result.json`, `report.html` and
  repair prompts.
- Signed-in checks keep no Playwright trace unless you pass `--trace on`: a
  trace records request headers, including the session cookie, and CI uploads
  traces as artifacts. The sign-in flow itself is never traced.
- A check with `"login": false` runs signed out, for rules like "visitors are
  sent to the sign-in page".
- If sign-in fails, the run is an error (exit 3) that says what did not hold,
  where the browser ended up and what the page said, with a `sign-in.jpg`
  screenshot. `contexer doctor` reports unset secrets before you run.
- Sessions kept only in `sessionStorage` are not carried over; cookie and
  local-storage sessions are.

### Apps that save data on a server

Every check gets a fresh browser, but all checks talk to the same running app,
so whatever one check saves on the server is still there for the next. Then a
correct app fails "shows 2 entries" because an earlier check added one.
`[app] reset` runs before each check to put the data back, for example
`npm run db:reset` or `curl -sf -X POST {url}/api/test/reset`:

- It must be fast, because it runs once per check, and it must keep the
  `[auth]` test account.
- If it fails, its check is blocked as unverified, with the command's output.
  It is never counted as refuted.
- The drafting model is told to give the items a check creates unique names
  and to assert on those names, so drafted checks tolerate leftover data. A
  reset is still the reliable fix.

## Architecture

| Package | Responsibility |
| --- | --- |
| `cli/` | The commands. `term.py` is the terminal design they all share: no boxes, colour only for outcomes, aligned summaries, a live line while work runs |
| `config/` | `contexer.toml`, and the user's settings and keys in `~/.contexer/` |
| `llm/` | The 14-provider catalog, model discovery, key checks and OpenRouter's free-request count, and the drafting model clients |
| `contract/` | Contract model, canonical sha256, approval, file store |
| `verification/` | The closed check DSL, the Playwright runner (screenshots, traces), and the verifier. Verdicts are `verified`, `refuted` or `unverified`, each labelled `proven`, `LLM-judged` or `heuristic` |
| `gate/` | Fail-safe gate decision and the `VerificationSession` |
| `appserver/` | Start-plan detection, the dev-server lifecycle, and Windows Job Objects |
| `agents/` | The `CodingAgentAdapter` interface: Claude Code, Codex, OpenCode and a scripted agent |
| `checkpoint/` | Shadow-git snapshots and exact restores |
| `controller/` | Implement → prove → repair: keep-best, revert, repeated-failure detection, tamper guard |
| `evidence/` | Run directories and the self-contained HTML report |
| `github/` | Commit status and job summary; the pull-request hand-off; the issue flow (draft comment, approval, live status) |
| `bench/` | Seeded-bug benchmark, including `--live` scoring of LLM-compiled contracts |
| `workflow/` | Goal-to-checks compiler (`criteria.py`) and the repository inspector |
| `runtime/`, `cli/repl.py` | The interactive shell and its earlier loop |

The full technical reference is [docs/architecture.md](docs/architecture.md).
The build plan and design decisions are in
[docs/roadmap.md](docs/roadmap.md). The research behind each library choice is
in [docs/technical-landscape.md](docs/technical-landscape.md).

## Tests

```bash
python -m pytest -q -p no:cacheprovider --deselect tests/test_opencode_integration.py::test_live_opencode_e2e
contexer bench --repeats 2
```

The suite (about 510 tests, 8 minutes) runs real Chromium against fixture apps, real Node process trees
for the dev-server tests, and real git for snapshots. It needs no network and
no model. The benchmark's React + Vite fixture runs `npm ci` once, so the
benchmark needs network the first time. Live-service tests skip themselves when their prerequisites are
missing. CI runs both commands on Linux; see
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml).
