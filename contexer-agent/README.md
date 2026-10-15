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

**Optional, for compiling goals into checks:** set `OPENROUTER_API_KEY` in
`.env` (see `.env.example`). Replaying approved contracts never calls a model.

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
| `contexer verify "GOAL"` | Compile a goal into a draft contract grounded in the running UI, then prove it |
| `contexer verify --contract ID` / `--all` | Prove saved contracts; no LLM calls |
| `contexer replay [--github]` | `verify --all` for CI. `--github` posts a `contexer/acceptance` commit status |
| `contexer contract draft "GOAL"` | Create a draft contract |
| `contexer contract list` / `show ID` | Review contracts |
| `contexer contract approve ID` | Lock a contract at its current content (sha256). Any later edit needs re-approval |
| `contexer run "GOAL"` / `--contract ID` | Approve the checklist, drive the coding agent, prove, repair, and keep the best attempt |
| `contexer bench [--live]` | Seeded-bug benchmark: catch rate and false-failure rate |
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
install = true                           # install dependencies when node_modules is missing

[gate]
judged = "advisory"                      # or "block"

[agent]
name = "claude-code"                     # or "opencode"
max_repair_rounds = 2
budget_usd = 3.0
```

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
no model. Live-service tests skip themselves when their prerequisites are
missing. CI runs both commands on Linux; see
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml).
