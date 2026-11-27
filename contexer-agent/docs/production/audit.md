# System audit, 2026-11-24

What Contexer 0.5.0 is in code, what Phase 5 left unfinished, what three
independent reads of the source found, what was fixed that day, and what is
still open. The market and model research is in [research.md](research.md);
the plan that follows from both is in [roadmap.md](roadmap.md) and
[tickets.md](tickets.md).

How it was done: the source and the tests were read, not the documents
about them. Two readers with no part in writing the code audited security
and the run loop. Each of their findings was checked against the code before
anything was changed, and the ones fixed here were first reproduced by a
failing test. A finding marked *read, not run* was traced through the code
and not executed.

---

## 1. What the brief assumed, and what the code is

The request for this audit describes Contexer as a coding harness: its own
tool runtime, file edits and terminal, making small models write code.

The code is something else, on purpose
([architecture.md](../agentic/architecture.md) §1): **Contexer never writes
code.** It sits above Claude Code, Codex and OpenCode. A person approves
browser checks before the build; the external agent builds; code replays
the checks and decides; Contexer's own agents test, diagnose and review.
There is no file-edit tool, no shell tool for a model and no repository
index, and none was ever planned.

So several things the brief asks to "inspect" do not exist and are not
gaps: a tool-execution runtime for code edits, a symbol index for a coding
model, an autofix that patches files itself. Where the brief's words map
onto something real, this audit uses the real thing:

| The brief says | In Contexer that is |
| --- | --- |
| Autofix | The repair loop: failed checks, Triage, the Diagnoser's lead, a fix prompt to the coding agent, replay |
| Tool execution runtime | The read-only tools of Contexer's agents: a browser for the Tester, `read_file` and `grep` for the Diagnoser and Reviewer |
| Sign-in workflow | `[auth]` in `contexer.toml`: Contexer signs in to the app under test before it replays checks |
| Model compatibility | Which models can drive Contexer's own agents, and which coding agents it can drive |
| Context engineering | What each of Contexer's agents is shown, and what the fix prompt carries |

Whether Contexer should become the coding harness is a product decision.
The evidence against it is in [research.md](research.md) §8, and the
roadmap proposes a way to serve the same goal, cheaper models doing real
work, from where Contexer stands.

---

## 2. Implementation map

About 22,000 lines of Python in `src/contexer/`, 74 test files. Every
package below is imported by a live command; none is dead.

| Package | What it does | State |
| --- | --- | --- |
| `cli/` | 13 commands: `setup`, `demo`, `doctor`, `init`, `test`, `run`, `verify`, `runs`, `restore`, `contract`, `replay`, `issue`, `bench` | Working |
| `graph/` | The run loop on LangGraph: intent, approve, coder turn, snapshot guard, app, test, score, review, triage, ask, diagnose, finalize. SQLite checkpoint, resume | Working; two bugs fixed here (§4) |
| `crew/` | Contexer's agents: Intent, Tester, Reviewer, Diagnoser, Triage, Challenger. One loop (`run_agent`), one budget, transcripts | Working with a strong model; brittle with a weak one (§5.3) |
| `verification/` | The check language, the replay runner, sign-in | Working; hardened here |
| `gate/` | The pass or fail decision from replayed checks | Working |
| `browser/` | The Tester's browser tools; recording actions into checks | Working |
| `checkpoint/` | Snapshots and restore in a second git repository; the run lock | Working; hardened here |
| `agents/`, `opencode/` | Adapters for Claude Code, Codex, OpenCode, and a scripted agent for tests | Claude Code and OpenCode run live; Codex never has |
| `llm/` | Provider catalog (15 providers), LangChain chat models, an older drafting client | Working; two clients where one would do |
| `appserver/` | Detects and runs the app's dev server, installs dependencies, resets data | Working; blocks the event loop |
| `github/` | Pull request hand-off, the issue flow, commit status | Tested against a fake GitHub and a real local remote; never against a real issue |
| `evidence/` | `run.json`, `report.html`, the run folder | Working |
| `bench/` | Four suites: gate, tester, repair, reviewer | Working |
| `intent/`, `skills/`, `contract/`, `config/` | Stores and settings | Working |
| `controller/`, `workflow/` | What is left of the 0.4 loop: prompts, scoring, the no-model drafting path | Live, used by the graph |

Not in the code, though a document or setting suggests it:

- `[agents.tester]` and `[agents.challenger]` in `contexer.toml` are read
  and never used: `contexer test` runs every agent on one model. **Fixed
  2026-11-26** (`MOD-5`).
- `max_steps` under `[agents]` reaches the Diagnoser and the Reviewer only.
  **Partly fixed 2026-11-26** (`MOD-5`): it reaches every agent of
  `contexer test`. **Fixed 2026-11-27**: inside `contexer run` it reaches
  Intent and Triage too.
- `workflow/criteria.py` was to "fold into the Intent agent"; it is still
  the drafting path when no tool-calling model is configured.
- The `classic` engine name and the `app_error` end state remain in types
  and tables; nothing produces them.

CI runs lint, type checks, the tests and the gate benchmark on Ubuntu with
Python 3.12 only.

---

## 3. Phase 5

Scope is [phase-5.md](../agentic/phase-5.md): a security pass (T5.1), cost
controls (T5.2), live runs, documents and a release (T5.3). The three
GitHub tickets are closed. Read against the code:

| Requirement | State | Evidence |
| --- | --- | --- |
| T5.1 Untrusted text quoted in every prompt | Done | `tests/test_security.py`, 12 strings through every channel |
| T5.1 Tool audit enforced by a test | Done | `test_each_agent_has_exactly_the_tools_in_the_audit_table` |
| T5.1 Tamper guard covers `contexer.toml` and the intent | Done, with a gap | The guard runs once per turn; see §5.2 item 5 |
| T5.1 Deny rule for `.contexer/` in OpenCode and Codex | OpenCode done; Codex has no such rule | Stated in phase-5.md |
| T5.1 Risk scan before a run | Done | `riskscan.py`, `tests/test_riskscan.py` |
| T5.1 A security review of Phases 0 to 4 | **Was not done. Done here** | §5.2: twelve findings |
| T5.2 One budget, per-agent models, estimate, bill | Done, with holes | `tests/test_budget.py`; holes in §5.4 |
| T5.2 Free-tier check uses the estimated request count | **Was not done. Done here** | §4, `tests/test_free_quota.py` |
| T5.3 Three live runs recorded | Done on HealthCare.Ai, the failed one included | CHANGELOG 0.5.0 |
| T5.3 Documents rewritten, old plans archived | Done | `docs/try-it.md` followed from a clean install on Windows |
| T5.3 Classic engine removed | Done | `controller/run.py` deleted |
| T5.3 Release | **Not done; the owner's step** | No `v0.5.0` tag; PyPI publisher not registered |

Never run, as phase-5.md says itself: macOS, Linux outside CI, Codex live,
the issue flow against a real GitHub issue, a cheaper model for any agent.

**Phase 5 is complete in code after this audit, and not released.** What
is left is not Phase 5 work: it is the launch blockers in
[roadmap.md](roadmap.md).

---

## 4. Fixed on 2026-11-24

Each has a test that failed first, except where noted.

| # | What was wrong | What could happen | Fix | Test |
| --- | --- | --- | --- | --- |
| 1 | A pass under old checks survived a correction. Attempt 1 passes, the review asks for one repair, the person corrects the checks, a later attempt fails the new ones: the run was undone back to attempt 1 and ended **succeeded** | Exit 0 and a pull request for work that fails the checks the person approved last. The one outcome Contexer exists to prevent | Approving changed checks drops the review's set-aside pass (`graph/nodes.py`, `approve`) | `test_a_pass_under_the_old_checks_does_not_end_a_run_whose_checks_were_corrected` |
| 2 | A run stopped while checks were replaying, then resumed, had no app | An attempt recorded as "App did not start: None", and a paid coding turn spent on repairing nothing | The test step starts the app when the process has none (`graph/nodes.py`, `test`) | `test_a_run_stopped_while_proving_resumes_with_the_app_running` |
| 3 | `goto` compared hosts as Python parses them. A browser reads `http://other\@app/` as `other` | A check written by a steered model opens another site, with a secret in the address if it wrote one | An address with a backslash, a control character, a user name or `${...}` is refused (`verification/runner.py`) | `test_an_address_a_browser_reads_differently_from_python_is_refused`, `test_a_goto_address_never_carries_a_secret` |
| 4 | Replay never looked at where the page was after a step | A link or redirect takes the page to another site and the next step types `${CONTEXER_TEST_PASSWORD}` there | A check stops at the first step after the page leaves the app. The sign-in from `contexer.toml` may still pass through another site | `test_a_check_stops_when_a_step_takes_the_page_off_the_app` |
| 5 | `[auth]` could name any environment variable | A pull request's `contexer.toml` has the gate type `GITHUB_TOKEN` into the app that pull request serves | Repository tokens, model keys and tracing keys are never typed (`verification/checks.py`) | `test_the_sign_in_cannot_name_a_repository_token_or_a_model_key` |
| 6 | The model's `grep` followed links and junctions | A planted link to `.git`, `~/.aws` or `.env` is read and sent to the model provider, and from there can reach the fix prompt and a pull request | Each file is resolved and must be inside the project and not closed (`crew/diagnoser.py`) | `test_a_search_does_not_follow_a_link_out_of_the_project_or_into_a_closed_folder` |
| 7 | Only `.env` and `.env.*` were closed to the read tools | `.npmrc`, `prod.env`, `id_rsa`, `.aws/credentials` were readable | Credential files and folders by name, case-insensitive | `test_files_that_hold_credentials_are_closed_whatever_they_are_called` |
| 8 | Contexer's snapshot git ran hooks and settings from `.contexer/shadow.git`, which the coding agent can write to | A planted hook runs in Contexer's process environment, which in Actions holds the repository token. Reproduced: the planted program ran | Every snapshot git call disables hooks, the file-system monitor, external diff and signing on the command line (`checkpoint/shadow.py`) | `test_a_hook_or_a_setting_planted_in_the_snapshot_repository_does_not_run` |
| 9 | The project file list walked `node_modules` and listed `.contexer/runs` first | After a few runs the Intent agent and the coding agent were shown Contexer's run files as "the project's files" | Closed folders are never entered; `.contexer` is one (`workflow/inspector.py`) | `test_the_file_list_is_the_projects_own_files_not_contexers_or_its_dependencies` |
| 10 | The free-request check covered only the old drafting path | A run whose own agents use a free OpenRouter model started with no warning and stopped midway | The check counts Contexer's agents and compares what is left with the estimate's ceiling of model calls (`cli/run_cli.py`) | `tests/test_free_quota.py`, three new tests |

Items 3, 4, 5 and 10 went straight to green: the tests were written first
and the failing state was not run separately. For item 3 the auditor had
executed the parsing difference; the browser side follows from the URL
standard.

**One change can break an existing project.** A hand-written contract whose
`goto` value contains `${NAME}` now fails with a message that says why.

---

## 5. What is still open

### 5.1 The run loop

| # | Finding | State | Severity |
| --- | --- | --- | --- |
| L1 | A tool call the model sends malformed, or cut off at the output limit, is treated as "no answer". On OpenAI-style providers the next request then carries a tool call with no result | **Fixed 2026-11-25** (`REL-2`) | Medium |
| L2 | Any JSON object in a model's text is accepted as its final answer when every field of the expected answer has a default. A model that prints a tool call as text ends the Reviewer with "no notes" and the Diagnoser with no lead, both marked `ok` | **Fixed 2026-11-25** (`REL-3`); reproduced first | Medium |
| L3 | A model gets two corrections for the whole run of an agent, not per mistake. Three narrated steps in a 40-step Tester run end it | **Fixed 2026-11-25** (`REL-4`) | Medium for weak models |
| L4 | Provider errors: two retries inside the SDK, then the agent ends. No backoff of Contexer's own, no second provider | Partial; every agent degrades safely to rules | Low |
| L5 | An unexpected exception in a node ends in a traceback with no `run.json` and the files left mid-attempt | **Fixed 2026-11-25** (`REL-5`). A snapshot store that cannot be written still ends the command with its own message and no `run.json` | Medium |
| L6 | A failed check is replayed once. A flaky check sends the coding agent to repair nothing | **Fixed 2026-11-25** (`REL-6`) | Medium |
| L7 | One failed coding-agent turn with no changes ends the run as `agent_error`; a transient failure is not tried again | Missing | Low |
| L8 | The review's commands have no baseline: an `npm test` that failed before the change triggers a paid repair turn | Partial | Low |
| L9 | Dependency install, app start, the review's commands and git run on the event loop; Ctrl+C waits for them. Since 2026-11-27 the review's registry lookups do too (`AGT-2`): at worst 5 seconds per registry that is down, and 20 lookups | Open (in readiness.md) | Medium |
| L10 | `run.json` and the per-attempt result are written in place; a kill mid-write leaves a file a resume cannot read | **Fixed 2026-11-25** (`REL-7`) | Low |
| L11 | The run lock is check-then-write, and `contexer test` takes no lock | **Fixed 2026-11-25** (`REL-7`) | Low |

What holds, and was read to hold: a run ends `succeeded` only on a gate
pass recomputed in `finalize` (with the hole closed in §4 item 1); every
attempt replays every approved contract, so a repair that breaks an older
behaviour is seen; step caps, 25 tool calls per reply, a refusal of the
same call three times running, a round limit, one review repair, one
question to the person. Since 2026-11-27 (`AGT-1`) a run also replays the
other approved contracts once before the first turn: a check that already
failed then is left out of the gate and listed as not proven, and one the
change broke is named as a regression.

### 5.2 Security

Threat model, from [hardening.md](../agentic/hardening.md): assume the
model is compromised; page text, repository files, issue text and tool
results are data. Ordered by severity and by how easily it is used.

| # | Finding | Who can use it | Severity | State |
| --- | --- | --- | --- | --- |
| S1 | ~~The hand-off's `git add`, `commit` and `push` ran the project's hooks and git settings with the whole environment~~ | The coding agent, steered by an issue | High in the issue flow | **Fixed 2026-11-24** (`test_a_hook_planted_during_the_run_is_not_run_by_the_hand_off` and three more). Left: a hook that was there before the run still runs locally and may call project scripts the agent changed, without a token; the two-job design (`SEC-10`) is the full answer in Actions. **Built 2026-11-27** (`SEC-10`): the job in which the agent runs has a token that can only read, and a second job pushes. Not yet run on GitHub |
| S2 | ~~The CLI loaded the nearest `.env` unfiltered at start~~ | Repository content; the coding agent | Medium | **Fixed 2026-11-24** (`test_no_command_takes_a_steering_name_from_the_nearest_env_file`) |
| S3 | ~~The tamper guard ran once per turn and the hand-off committed the contract from disk~~ | The coding agent | Medium | **Fixed 2026-11-24** (`test_a_contract_rewritten_after_the_run_is_not_what_gets_committed`) |
| S4 | ~~The secret scan read the first 200,000 characters of the diff~~ | An accident | Medium | **Fixed 2026-11-24**; reproduced first: a key after a 300 KB lockfile change was pushed (`test_a_secret_after_a_large_lockfile_change_is_still_seen_and_not_pushed`) |
| S5 | The `grep` pattern guard misses `(a\|a)*$` and relatives. One pattern holds the interpreter lock: no timeout, no budget check, until the process is killed | A steered Diagnoser or Reviewer | Low to medium | **Fixed 2026-11-26** (`SEC-5`): literal search by default, a regular expression in a process stopped at the two-second limit |
| S6 | Issue text keeps Unicode tag characters and bidi isolates, which GitHub renders as nothing. `/contexer draft` checks nobody's role in code | An issue author; any commenter | Low to medium | **Fixed 2026-11-26** (`SEC-6`): characters of category Cf, Co and Cn and variation selectors are removed; a draft asked for in a comment needs write access. `contexer issue draft N` typed at a terminal is not checked |
| S7 | The dev server, the install and the reset get every model key, including keys `contexer setup` saved | A dependency's install script | Low to medium | **Partly fixed 2026-11-26** (`SEC-7`): they no longer get what `contexer setup` saved, or `LANGFUSE_*`. Left, by the ticket's rule: a key that is exported or set in the project's `.env` still reaches them |
| S8 | Pull request text still live: the commit subject can say "closes #12"; bare URLs autolink | An issue author, app text | Low | **Fixed 2026-11-26** (`SEC-8`); not checked against GitHub's own renderer |
| S9 | The draft marker is accepted anywhere in any comment by Contexer's account | Whoever can get text into a status comment | Low | **Fixed 2026-11-26** (`SEC-9`): a comment is a draft only when it begins with the marker |
| S10 | Smaller: the credentials file is written before its mode is set; skills are capped on save and not on load; `.contexer/runs` and snapshot objects are never pruned; workflow templates reference `@main`; third-party Actions pinned by tag; no upper bound on five dependencies | Various | Low | **Partly fixed 2026-11-26.** `SEC-9`: the credentials file is created with mode 600 (its folder with 700 when saving the key or the settings creates it; `llm/capabilities.py: save_measurement` can create it first with the default mode), and skills are capped on load and covered by the tamper guard. `DX-5`: `contexer runs prune` removes old runs and their snapshots when asked. **Fixed 2026-11-27**: third-party Actions are pinned by commit in the action files, the dogfood gate and the workflow templates, the five dependencies have an upper bound, and `~/.contexer` is created with mode 700 whichever file is saved first (`config/user.py: home_dir`; a folder that already exists is not tightened). Open: the workflow templates reference this repository's own actions at `@main`; `ci.yml` and `release.yml` are still pinned by tag |

Controls read and found to hold: `read_file` confinement on Windows
(alternate data streams, 8.3 names, UNC paths, junctions, executed by the
auditor); no `shell=True` or `os.system` anywhere; the Reviewer's commands
come from a fixed list; verification uses the approved contract in memory,
not the file; approval is bound to the comment's time and to write access;
reports escape every value; the untrusted-text marker cannot be closed from
inside; no `pull_request_target`; the release builds and publishes in
separate jobs.

### 5.3 Model compatibility

- The catalog knows, per provider, an endpoint, a key variable and a
  default model. It knows nothing per model: not the context window, not
  whether tools work, not a price. **Fixed 2026-11-26** (`MOD-1`): a
  record per model with the source of each fact, shown by `doctor` and
  `setup`. Only OpenRouter's catalogue fills the window and the prices.
  Since 2026-11-27 the agent loop reads it for whether a tool call
  printed as text is run (`MOD-3`) and for the context window (`CTX-3`),
  and the budget reads it for the price of a call (`COST-3`).
- Every agent assumes native tool calling. Whether a model has it is known
  from OpenRouter's metadata or assumed; elsewhere the first call finds
  out by matching error text.
- There is no fallback when a model prints a tool call as text, the most
  reported failure of local models ([research.md](research.md) §4), and
  findings L1 to L3 make that failure silent. **Fixed 2026-11-27**
  (`MOD-3`): a tool call printed as text is run as a call on a model not
  known to call tools natively; the shapes read are from documentation
  and have not been recorded from live servers.
- Local servers work through `ollama` or `custom` with a base URL. Never
  tried against a real one.
- Only one model, Azure `gpt-5.4`, has ever driven the agents in a measured
  run.

### 5.4 Cost

- The coding agent's cost is known only for Claude Code. For Codex and
  OpenCode it is recorded as 0, and the one budget for the run then
  silently leaves it out. **Fixed 2026-11-27** (`COST-1`): for Codex and
  OpenCode it is recorded as unknown, and a run with `max_usd` is refused
  at the start.
- A provider that reports no price and a project that sets no rates: the
  agents' cost is unknown and counts as 0 against the budget, with no
  warning. One rate pair is applied to every agent whatever model it runs.
  **Fixed 2026-11-27** (`COST-1`, `COST-3`): a model with no known price
  and a project that sets no rates: a dollar limit is refused at the
  start. Without rates, each call is priced from its own model's record.
- A token or cost limit that is reached silences Contexer's agents; the
  coding agent's turns go on under rules. **Fixed 2026-11-27** (`COST-1`):
  a token or cost limit that is reached ends the run before the next
  coding turn.
- `contexer test` ignores `[agents] max_usd`. **Fixed 2026-11-27**
  (`COST-4`): `contexer test` reads `[agents] max_usd` and the rates.
- A budget cannot stop a coding agent in the middle of a turn (known).
- No prompt-cache markers are set and cached tokens are not read from
  usage, so the largest saving on offer is neither taken nor measured.
  **Partly fixed 2026-11-27** (`COST-2`): cache markers are set on the
  tools and the system prompt for Anthropic and cached tokens are read
  from usage; the saving is not measured live yet.

### 5.5 Context

What each agent is shown is cut by fixed sizes from the top: a diff at
12,000 characters for the Diagnoser and 30,000 for the Reviewer, a tool
result at 20,000, a page snapshot at 4,000. Nothing orders a diff by the
files a failure points at (**fixed 2026-11-27**, `CTX-2`: a diff over its
limit is cut by file, the files the failures and the server log name
first, then the smallest, and the files left out are named). A
conversation only grows: a long Tester run that passes the model's window
ends as a provider error (**fixed 2026-11-27**, `CTX-3`: past 60% of the
model's window, old tool results are replaced by a note; a model whose
window is not known is taken to have 128,000 tokens). The Diagnoser is
not shown earlier attempts or its own earlier leads, so round three can
repeat round one (**fixed 2026-11-26**, `CTX-1`: it is shown its earlier
leads and what each following attempt changed; no code detects a repeat).
The project summary is rebuilt on every run.

### 5.6 Observability

Recorded today: `run.json` (outcome, attempts, triage decisions, per-agent
tokens and cost, review notes), a result and screenshots per attempt, a
JSONL transcript per agent with seconds and tokens per model call,
`runs --stats`, optional Langfuse.

Missing to answer "why did it fail, where did the tokens go, which model
was better":

- the model id is not in `run.json`, so runs cannot be compared by model
  (**partly fixed 2026-11-27**, `OBS-3`: `runs --stats --by model` counts
  from each run's `trace.jsonl`; the id is still not in `run.json`, and
  the coding agent's model is recorded nowhere);
- the events of a run exist only on stdout with `--json` (**fixed
  2026-11-26**, `OBS-1`: `trace.jsonl` in the run folder);
- the prompt sent to the coding agent on each attempt, and the Diagnoser's
  lead, are not in the run folder (**fixed 2026-11-27**, `OBS-2`: each
  prompt is kept, masked, as `attempt-<n>/prompt.md`, and is sent to the
  coding agent masked the same way; the lead is part of the repair prompt,
  not a file of its own);
- no finish reason, retry count, cached tokens or context size per call
  (**partly fixed 2026-11-26**, `OBS-1`: the trace has the finish reason
  and the cached tokens of each model call; not the retry count or the
  context size);
- no count of tool errors or of repaired tool calls per model (**partly
  fixed 2026-11-26**, `MOD-2` and `OBS-1`: repaired and failed tool calls
  are recorded per agent; **fixed 2026-11-27**, `OBS-3`: `runs --stats
  --by model` gives the tool error and repair rates per model);
- a Diagnoser that fails says nothing (**fixed 2026-11-27**: the run
  prints one event when the Diagnoser did not finish).

### 5.7 Evaluations

What exists is in [readiness.md](../agentic/readiness.md) §3 and stands.
What is missing for the claims the product wants to make:

- no run of any suite on a second model, so nothing is known about weaker
  models;
- no baseline of the coding agent alone against the coding agent with
  Contexer on the same tasks;
- every suite is one run per case, and the research says that is noise
  ([research.md](research.md) §3). **Partly fixed 2026-11-26** (`EVAL-3`):
  every suite takes `--repeats` and reports intervals; no suite has been
  re-run with repeats, so the published numbers are still one run;
- one real project.

---

## 6. Test results

Before the changes: the suite was started on the untouched tree and was
still running when the first fixes were made, so it is not a clean
baseline and is not quoted.

After the first ten fixes: 1003 passed, 4 skipped, with lint and type checks
clean; after the four security fixes of milestone A, 1014 passed, 4 skipped; after the four run-loop fixes of milestone B on 2026-11-25, 1028 passed, 4 skipped ([roadmap.md](roadmap.md) §12). The benchmarks were not re-run and no
live run with a model was made that day.
