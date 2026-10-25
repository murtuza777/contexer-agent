# Contexer (Python package)

This is the developer guide. The product overview is in the
[repository README](../README.md).

## Setup

```bash
cd contexer-agent
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

Then run `contexer doctor`. It checks Python, Chromium, git, Node, the
drafting model, coding agents and the project in `--dir`, and prints the fix
for anything missing.

**Optional, for compiling goals into checks:** set one of `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY` or `OPENROUTER_API_KEY` in the environment or `.env` (see
`.env.example`). With several keys set, the first in that order is used;
`CONTEXER_LLM_PROVIDER` or `[compiler]` in `contexer.toml` picks one
explicitly. Draft quality depends on the model, so prefer a strong one (the
Anthropic default is `claude-opus-5-5`). Replaying approved contracts never
calls a model.

**Optional, for `contexer run`:** a coding agent on `PATH`:

| Agent | Requirement |
| --- | --- |
| [Claude Code](https://code.claude.com) (`claude`) | Logged in, or `ANTHROPIC_API_KEY` set |
| [OpenCode](https://opencode.ai) (`opencode`) | Configured with a provider that allows programmatic use |

## Commands

Every command takes `--dir PATH` (default: the current directory) and
`--url URL`. Use `--url` when you already run the app; otherwise Contexer
serves static sites itself and starts the project's dev server.

| Command | What it does |
| --- | --- |
| `contexer doctor` | Check everything Contexer needs, with the fix for each problem |
| `contexer demo [--fix]` | Create a todo app with a seeded bug and prove its contract; no key or agent needed |
| `contexer init [--ci]` | Detect how the app starts and prepare `.contexer/`; `--ci` writes the gate workflow |
| `contexer verify "GOAL"` | Compile a goal into a draft contract grounded in the running UI, then prove it |
| `contexer verify --contract ID` / `--all` | Prove saved contracts; no LLM calls |
| `contexer replay [--github]` | `verify --all` for CI. `--github` posts a `contexer/acceptance` commit status |
| `contexer contract draft "GOAL"` | Create a draft contract |
| `contexer contract list` / `show ID` | Review contracts |
| `contexer contract approve ID` | Lock a contract at its current content (sha256). Any later edit needs re-approval |
| `contexer run "GOAL"` / `--contract ID` | Approve the checklist, drive the coding agent, prove, repair, and keep the best attempt |
| `contexer bench [--live]` | Seeded-bug benchmark: catch rate and false-failure rate |
| `contexer runs` | Recent runs with outcome, check counts and report paths |
| `contexer` | The interactive shell (`/loop`, `/verify`, `/project`, ...) |

Useful options:

- `--trace on-failure` keeps Playwright traces for failing checks.
- `--json` prints `result.json`.
- `--open` opens the HTML report.
- `run` also takes `--agent`, `--model`, `--rounds`, `--budget` and `--yes`.

**Exit codes:** `0` pass · `1` fail (a check was refuted) · `2` needs action
(unverified check, draft or modified contract, budget or time exhausted) ·
`3` error (app or agent could not run).

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

[auth]                                   # sign in before checks (see below)
url = "/login"
steps = [
  { action = "fill", target = { label = "Email" }, value = "${CONTEXER_TEST_EMAIL}" },
  { action = "fill", target = { label = "Password" }, value = "${CONTEXER_TEST_PASSWORD}" },
  { action = "click", target = { role = "button", name = "Sign in" } },
]
expect = [{ kind = "url", contains = "/dashboard" }]

[compiler]
provider = "anthropic"                   # or "openai", "openrouter"; default: the first key set
model = "claude-opus-5-5"

[gate]
judged = "advisory"                      # or "block"

[agent]
name = "claude-code"                     # or "opencode"
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

## Architecture

| Package | Responsibility |
| --- | --- |
| `contract/` | Contract model, canonical sha256, approval, file store |
| `verification/` | The closed check DSL, the Playwright runner (screenshots, traces), and the verifier. Verdicts are `verified`, `refuted` or `unverified`, each labelled `proven`, `LLM-judged` or `heuristic` |
| `gate/` | Fail-safe gate decision and the `VerificationSession` |
| `appserver/` | Start-plan detection, the dev-server lifecycle, and Windows Job Objects |
| `agents/` | The `CodingAgentAdapter` interface: Claude Code, OpenCode and a scripted agent |
| `checkpoint/` | Shadow-git snapshots and exact restores |
| `controller/` | Implement → prove → repair: keep-best, revert, repeated-failure detection, tamper guard |
| `evidence/` | Run directories and the self-contained HTML report |
| `github/` | Commit status and job summary |
| `bench/` | Seeded-bug benchmark, including `--live` scoring of LLM-compiled contracts |
| `workflow/`, `runtime/`, `cli/repl.py` | The interactive shell and its earlier loop |

The build plan and design decisions are in
[docs/roadmap.md](docs/roadmap.md). The research behind each library choice is
in [docs/technical-landscape.md](docs/technical-landscape.md).

## Tests

```bash
python -m pytest -q -p no:cacheprovider --deselect tests/test_opencode_integration.py::test_live_opencode_e2e
contexer bench --repeats 2
```

The suite runs real Chromium against fixture apps, real Node process trees
for the dev-server tests, and real git for snapshots. It needs no network and
no model. The benchmark's React + Vite fixture runs `npm ci` once, so the
benchmark needs network the first time. Live-service tests skip themselves when their prerequisites are
missing. CI runs both commands on Linux; see
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml).
