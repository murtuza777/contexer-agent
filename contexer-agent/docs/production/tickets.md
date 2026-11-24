# Tickets, 2026-11-24

The backlog behind [roadmap.md](roadmap.md), from the findings in
[audit.md](audit.md). Paths are under `src/contexer/` unless they start
with `tests/`, `bench/` or `docs/`.

These are proposals. GitHub issues are opened after the owner has read
this file, as for the earlier phases.

Priority: **P0** blocks the closed beta. **P1** is needed for the claims
the product makes or for the issue flow. **P2** is wanted before a public
launch. **P3** is later. Effort: S up to two days, M up to a week, L more.

Every ticket is done when: its tests were written first and failed, they
pass, the full suite, lint and type checks pass, the documents that
describe the behaviour say what the code now does, and the change is in
the changelog.

Not listed: what was fixed on 2026-11-24 ([audit.md](audit.md) §4).

| Milestone | Tickets |
| --- | --- |
| A | SEC-1, SEC-2, SEC-3, SEC-4, REL-1 |
| B | REL-2, REL-3, REL-4, REL-5, REL-6, REL-7 |
| C | SEC-5, SEC-6, SEC-7, SEC-8, SEC-9, SEC-10, REL-8 |
| D | MOD-1, MOD-2, MOD-3, MOD-4, MOD-5, EVAL-1, EVAL-2, EVAL-3 |
| E | COST-1, COST-2, COST-3, COST-4, OBS-1, OBS-2, OBS-3, OBS-4, CTX-1, CTX-2, CTX-3, CTX-4 |
| F | INT-1, INT-2, BRIEF-1, BRIEF-2, CTX-5, DX-1, DX-2, DX-3, DX-4, DX-5, DOC-1 |
| G | AGT-1, AGT-2, AGT-3, AGT-4 |
| H | REL-9, REL-10, REL-11, DOC-2, CLN-1 |

Critical path: SEC-1 → SEC-2 → SEC-4 → REL-1 → REL-3 → REL-5 → INT-1 →
INT-2 → DX-1 → DX-3 → DOC-1 → REL-11. BRIEF-1 runs beside INT-1.

---

## Security

### SEC-1 The hand-off does not run the project's hooks or settings with a token
- **Type.** Security. **Priority.** P0. **Effort.** M. **Depends on.** Nothing.
- **Problem.** `github/handoff.py` runs `git add`, `commit` and `push` with
  the whole environment and the project's own `.git/hooks` and
  `.git/config`. The coding agent can write both. For a push the
  environment also carries the auth header.
- **User impact.** In the issue flow, text in an issue can steer the agent
  to plant a hook that reads the repository token.
- **Do.** One helper for every git call Contexer makes on the project's
  repository: hooks path set to an empty place, no file-system monitor, no
  credential helper, an environment without repository tokens for
  everything except the push. Record a hash of `.git/config` and
  `.git/hooks` before the first agent turn and refuse to hand off when
  they changed, naming the files.
- **Decide first.** A person's own pre-commit hook then does not run on
  Contexer's commit. Proposed: hooks never run in Actions; on a person's
  machine `[handoff] run_hooks = true` turns them back on.
- **Files.** `github/handoff.py`, `checkpoint/shadow.py` (reuse
  `_NO_PROGRAMS`), `graph/context.py`.
- **Accept.** A scripted agent plants `pre-commit` and `pre-push` hooks
  that write `$GITHUB_TOKEN` to a file; after a hand-off to a local remote
  the file does not exist, and the hand-off says the hooks changed.
- **Tests.** `test_handoff_does_not_run_project_hooks`,
  `test_handoff_refuses_when_git_config_changed_during_the_run`.

### SEC-2 One filtered loader for `.env`
- **Type.** Security. **Priority.** P0. **Effort.** S. **Depends on.** Nothing.
- **Problem.** `cli/__init__.py` and `config/settings.py` call
  `load_dotenv` on the nearest `.env` with no filter, before the filtered
  loader in `config/project.py`. Names that steer git, GitHub, the
  interpreters and the model endpoint are all taken.
- **User impact.** A committed `.env`, or one the coding agent wrote, runs
  a program at the next snapshot or sends the person's key to another host.
- **Do.** Remove the two generic loads; route both through the filtering
  function. Refuse also `*_BASE_URL`, `*_PROXY`, `SSL_CERT_*`,
  `REQUESTS_CA_BUNDLE`, `NODE_EXTRA_CA_CERTS`, `GH_HOST`, `GITHUB_*`,
  `OPENCODE_SERVER_URL`, unless the key for that provider comes from the
  same file.
- **Files.** `cli/__init__.py`, `config/settings.py`, `config/project.py`.
- **Accept.** With a `.env` that sets `GIT_SSH_COMMAND`, `GIT_CONFIG_COUNT`
  and `GITHUB_API_URL`, none is in the environment after any command
  starts. A `.env` with a model key and that provider's base URL still
  works.
- **Tests.** `test_cli_startup_does_not_take_steering_names_from_dotenv`.

### SEC-3 The contract that is committed is the one that was approved
- **Type.** Security. **Priority.** P1 (P0 for the issue flow). **Effort.** S.
- **Problem.** The tamper guard runs once, after the agent's turn. Code
  that runs later can rewrite the contract file; `cli/run_cli.py` reloads
  it from disk and the hand-off commits it.
- **User impact.** A pull request whose body lists the real checks and
  whose committed contract, replayed by every later gate run, asserts
  nothing.
- **Do.** Run the guard again in `finalize` and immediately before
  `git add`. Write the contract file from the approved object in memory
  before committing. Never rebuild the hand-off's contract with
  `store.load`.
- **Files.** `graph/nodes.py`, `cli/run_cli.py`, `github/handoff.py`.
- **Accept.** A scripted dev server rewrites the contract after start; the
  committed file equals the approved contract and the run reports
  tampering.
- **Tests.** `test_contract_changed_after_the_guard_is_not_committed`.

### SEC-4 The secret scan covers every changed file
- **Type.** Security. **Priority.** P0. **Effort.** S.
- **Problem.** `prescan` reads `outcome.diff`, cut at 200,000 characters.
- **User impact.** A key added after a large lockfile change is pushed.
- **Do.** Scan per changed file from the snapshot repository, streamed and
  uncapped. A file that cannot be scanned (binary, too large) is named,
  and the change is not pushed unless the file is one git would ignore.
  The Reviewer's scan uses the same path.
- **Files.** `checkpoint/shadow.py`, `github/handoff.py`, `graph/nodes.py`,
  `crew/reviewer.py`.
- **Accept.** A 300 KB lockfile change plus a key in `src/z.js`: not pushed.
- **Tests.** `test_secret_after_a_large_lockfile_is_not_pushed`.

### SEC-5 The search tool cannot hang the process
- **Type.** Security, reliability. **Priority.** P1. **Effort.** S.
- **Problem.** `(a|a)*$` and relatives pass the nested-quantifier guard;
  `re` holds the interpreter lock, so no timeout or budget check runs.
- **Do.** Search for the literal text by default; a regular expression
  only when the model asks, run in a subprocess with a two-second limit
  per call.
- **Files.** `crew/diagnoser.py`.
- **Accept.** `(a|a)*$` against a 60-character line returns within two
  seconds with an error the model can read.
- **Tests.** `test_grep_alternation_backtracking_is_bounded`.

### SEC-6 Issue text: what the agents read is what a person sees
- **Type.** Security. **Priority.** P1. **Effort.** S.
- **Problem.** Unicode tag characters (U+E0000 to U+E007F), bidi isolates
  and the soft hyphen pass `visible_text`. `/contexer draft` checks no
  role in code.
- **Do.** Remove every character of category Cf, Co and Cn. Require write
  access for a draft started by a comment, as `build` does.
- **Files.** `github/issues.py`, `cli/issue_cli.py`.
- **Accept.** A goal with tag characters reaches the agents without them;
  a draft by a commenter with read access is refused with a sentence.
- **Tests.** `test_tag_characters_are_removed_from_an_issue_goal`,
  `test_a_draft_by_comment_needs_write_access`.

### SEC-7 The app's processes get only the keys the project gave them
- **Type.** Security. **Priority.** P2. **Effort.** S.
- **Problem.** `child_env` strips repository tokens only. Keys saved by
  `contexer setup` reach every install script.
- **Do.** Drop from `child_env` what `apply_user_settings` added, and
  `LANGFUSE_*`. Keep what the project's `.env` or `[app] env` sets.
- **Files.** `procutil.py`, `config/user.py`.
- **Accept.** A dev server started by Contexer does not see a key that
  exists only in `~/.contexer/credentials.toml`.
- **Tests.** `test_dev_server_env_has_no_setup_credentials`.

### SEC-8 Pull request text is inert everywhere
- **Type.** Security. **Priority.** P2. **Effort.** S.
- **Problem.** The commit subject and the title use the raw goal; bare
  URLs and reference-style links stay live.
- **Do.** Pass the subject and title through `_inert`; break `://` and
  `www.`; escape `[` in quoted text.
- **Files.** `github/handoff.py`.
- **Accept.** A goal ending "closes #12" cannot close issue 12.
- **Tests.** `test_commit_message_cannot_close_other_issues`,
  `test_bare_urls_in_a_pull_request_body_are_inert`.

### SEC-9 Small hardening
- **Type.** Security. **Priority.** P2. **Effort.** M.
- **Do, one commit each.** Create the credentials file with mode 600 and
  its folder with 700. Cap skills on load and add `.contexer/skills` to the
  guard. Require the draft marker at the start of a comment and never in a
  status comment. Reference a release tag, not `@main`, in the workflow
  templates. Pin third-party Actions by commit. Pass Action inputs through
  `env:`. Add upper bounds to `openai`, `pydantic`, `python-dotenv`,
  `httpx` and `playwright`.
- **Files.** `config/user.py`, `skills/store.py`, `github/issues.py`,
  `cli/init_cli.py`, `.github/workflows/`, `action.yml`, `pyproject.toml`.
- **Tests.** One per item, named for what it refuses.

### SEC-10 Build with no write token, push from a second job
- **Type.** Security, architecture. **Priority.** P1. **Effort.** L.
  **Depends on.** SEC-1, SEC-3.
- **Problem.** In Actions the coding agent runs in a job that holds a
  write token. Every fix so far removes a way to read it; this removes the
  token.
- **Do.** The issue workflow becomes two jobs. The first has
  `contents: read`, runs the build and the proof, and uploads the change
  as a patch with the run folder. The second has the write token, runs no
  project code, checks the patch touches nothing under `.github/` or
  `.contexer/contracts` other than the approved contract, applies it and
  opens the pull request.
- **Files.** `issue/action.yml`, `cli/init_cli.py`, `cli/issue_cli.py`,
  `github/handoff.py`.
- **Accept.** The hostile-repository suite passes with the token absent
  from the first job's environment, checked by the job itself.
- **Tests.** The workflow run on a sandbox repository (REL-8).

---

## Reliability

### REL-1 Release 0.5.1
- **Type.** Release. **Priority.** P0. **Effort.** S. **Depends on.**
  SEC-1, SEC-2, SEC-4. **Needs the owner.**
- **Do.** Register the trusted publisher for `contexer-agent` on PyPI.
  Decide the licence ([roadmap.md](roadmap.md) §7). Bump to 0.5.1, tag,
  let the workflow publish. Install from PyPI on a clean machine.
- **Accept.** `uv tool install contexer-agent` then `contexer demo` works
  on a machine that never had the repository.

### REL-2 A malformed or cut-off tool call is answered, not ignored
- **Type.** Bug. **Priority.** P1. **Effort.** S.
- **Problem.** `crew/base.py` reads `reply.tool_calls` only. A reply with
  `invalid_tool_calls` gets a human-message correction, and the next
  request carries a tool call with no result.
- **Do.** Answer each invalid call with an error tool message under its
  id. Record the finish reason; when it is "length", say the output was
  cut off and by how much the limit can be raised.
- **Files.** `crew/base.py`, `crew/transcript.py`.
- **Accept.** A scripted reply with one valid and one invalid call: the
  valid one runs, the invalid one gets an error result, the agent goes on.
- **Tests.** `test_an_invalid_tool_call_gets_a_tool_result`.

### REL-3 Text is an answer only when it is the answer
- **Type.** Bug. **Priority.** P0. **Effort.** S.
- **Problem.** `_from_text` accepts any JSON object when every field of
  the answer has a default. A model that prints a tool call as text ends
  the Reviewer as "no notes" and the Diagnoser with no lead, status `ok`.
- **User impact.** With a weak model, a review that silently reviewed
  nothing.
- **Do.** Accept a text answer only when it has at least one field of the
  expected answer. An object shaped like a tool call goes to MOD-3 when
  that exists, and until then is an invalid answer with a correction.
- **Files.** `crew/base.py`, `llm/structured.py`.
- **Accept.** The Reviewer given `{"name":"read_file","arguments":{}}` as
  text does not return `ok`.
- **Tests.** `test_a_printed_tool_call_is_not_a_final_answer`, for each of
  the five answer types.

### REL-4 Corrections are counted per mistake
- **Type.** Reliability. **Priority.** P1. **Effort.** S.
- **Problem.** Two corrections for an agent's whole run.
- **Do.** Reset the count after a valid step; keep a cap on corrections in
  a row. Say in the transcript how many were used.
- **Files.** `crew/base.py`.
- **Accept.** Three narrated steps spread over a 40-step run do not end it;
  three in a row do.
- **Tests.** `test_corrections_reset_after_a_valid_step`.

### REL-5 A run that crashes still ends as a run
- **Type.** Reliability. **Priority.** P0. **Effort.** M.
- **Problem.** An unexpected exception in a node is re-raised: a
  traceback, no `run.json`, the files left mid-attempt.
- **Do.** Catch at the engine: restore the best attempt or the baseline,
  write `run.json` with a new end state `internal_error` and the
  exception's one line, keep the traceback in the run folder, exit 3, and
  say how to report it. `session.py` catches more than `SignInError`.
- **Files.** `graph/engine.py`, `cli/run_cli.py`, `controller/models.py`,
  `gate/session.py`, `evidence/report.py`.
- **Accept.** A node made to raise: the files are as before the run, the
  report exists, the exit code is 3.
- **Tests.** `test_an_exception_in_a_node_restores_and_reports`.

### REL-6 A check that fails is replayed once more
- **Type.** Reliability. **Priority.** P1. **Effort.** M.
- **Problem.** One replay decides. A flaky check costs a coding turn.
- **Do.** A failed check is run again after its reset. Passing the second
  time marks it `flaky`: shown, counted, and not sent to the coding agent
  as a failure.
- **Decide first.** Whether a flaky pass counts as proven. Proposed: it
  does for the run and holds the pull request as a draft with the check
  named, because a real intermittent bug looks the same.
- **Files.** `verification/runner.py`, `verification/checks.py`,
  `gate/decision.py`, `controller/shared.py`, `evidence/report.py`.
- **Accept.** A fixture app that fails a check on the first load only: no
  repair turn; the report says flaky. The gate benchmark's catch rate is
  unchanged and its time is measured.
- **Tests.** `test_a_check_that_passes_on_the_second_replay_is_flaky`.

### REL-7 Files a resume depends on are written whole; one lock for both commands
- **Type.** Reliability. **Priority.** P2. **Effort.** S.
- **Do.** Write `run.json`, the per-attempt result and `stopped.ref` to a
  temporary name and rename. A file that cannot be read on resume is a
  `ResumeError` with a sentence. Create the lock with exclusive open.
  `contexer test` takes the lock.
- **Files.** `controller/shared.py`, `graph/context.py`, `graph/engine.py`,
  `checkpoint/lock.py`, `cli/test_cli.py`.
- **Tests.** `test_a_truncated_run_file_is_a_resume_error`,
  `test_two_starts_at_once_take_one_lock`.

### REL-8 The issue flow, run on a real repository
- **Type.** Reliability. **Priority.** P1. **Effort.** M. **Depends on.**
  SEC-10. **Needs the owner** to create a private sandbox repository.
- **Do.** Open an issue, comment `/contexer draft`, approve, and follow it
  to a proven pull request on GitHub Actions. Then repeat with each case
  of the hostile-repository suite.
- **Accept.** The outcomes, with links, are in the changelog.

### REL-9 Three more real projects
- **Type.** Evaluation. **Priority.** P1. **Effort.** L.
- **Do.** Three apps on different stacks (one not React, one with a
  server-rendered framework, one with a real database). For each: `test`,
  then a `run` whose checks a person reads before approving. Record
  outcome, attempts, cost, time and what had to be configured.
- **Accept.** The results are in `bench/RESULTS.md`, failures included.

### REL-10 Codex, live
- **Type.** Reliability. **Priority.** P2. **Effort.** S.
- **Do.** Install the Codex CLI; run the demo repair and one HealthCare.Ai
  change. Record cost reporting (it is 0 today) and whether a write to
  `.contexer/` is stopped by anything but the guard.
- **Accept.** The result is in the changelog; `COST-1` covers what it shows.

### REL-11 Release checklist and gates in CI
- **Type.** Release engineering. **Priority.** P1. **Effort.** M.
  **Depends on.** DX-3, EVAL-3.
- **Do.** A release workflow that refuses to publish unless the gates in
  [roadmap.md](roadmap.md) §8 hold on the tagged commit, and attaches the
  benchmark results to the release.
- **Files.** `.github/workflows/release.yml`, `bench/`.
- **Accept.** A tag on a commit that fails the gate benchmark does not
  publish.

---

## Models

### MOD-1 A capability record per model
- **Type.** Architecture. **Priority.** P1. **Effort.** M.
- **Problem.** The catalog knows providers, not models. Every agent
  assumes native tool calling, parallel calls and a large window.
- **Do.** `ModelCapabilities`: context window, native tools, parallel
  calls, strict schemas, vision, cached-input pricing, input and output
  price, and where each fact came from (provider catalogue, measured,
  assumed). Filled from OpenRouter's catalogue where it is the provider,
  from a small table Contexer ships for models it has measured, and from
  `check_tool_calling` (which exists and is unused) otherwise. `contexer
  setup` and `contexer doctor` show it; an agent is built from it.
- **Files.** `llm/catalog.py`, `llm/discovery.py`, `llm/chat.py`,
  `cli/setup_cli.py`, `cli/doctor_cli.py`, `crew/base.py`.
- **Accept.** `contexer doctor` prints, for the configured model, each
  capability and its source. A model with no tool calling is refused
  before a run with the reason.
- **Tests.** Recorded catalogue replies; a model with each capability absent.

### MOD-2 Validate a tool call and send the error back once
- **Type.** Model compatibility. **Priority.** P1. **Effort.** S.
  **Depends on.** REL-2.
- **Do.** Check arguments against the tool's schema before running it.
  On failure return the validation error as the tool's result, with the
  schema's required fields named. Count repaired calls per agent in the
  transcript and in `run.json`.
- **Files.** `crew/base.py`, `crew/transcript.py`.
- **Accept.** A scripted model that sends a wrong argument type gets the
  error and succeeds on its second call; the count is 1.
- **Tests.** `test_a_tool_call_with_bad_arguments_is_repaired_once`.

### MOD-3 Tool calls a server returned as text
- **Type.** Model compatibility. **Priority.** P1. **Effort.** M.
  **Depends on.** REL-3, MOD-1.
- **Problem.** Local servers often return call-shaped JSON or XML in the
  message text with no tool call.
- **Do.** When a reply has no tool call and its text holds exactly one
  object or tag block that names a tool the agent has, treat it as that
  call, mark it `text-fallback` in the transcript, and count it. Off for
  models whose record says native tools are reliable.
- **Files.** `crew/base.py`, `llm/structured.py`.
- **Accept.** Recorded replies in the shapes Ollama, llama.cpp and vLLM
  produce for Qwen, Gemma and gpt-oss each run the right tool.
- **Tests.** One per recorded shape; one that a quoted example in prose is
  not run.

### MOD-4 Strict, flat schemas and strict provider routing
- **Type.** Model compatibility. **Priority.** P2. **Effort.** S.
- **Do.** Every tool schema: no extra properties, every field required,
  optional ones nullable. Send `require_parameters: true` on OpenRouter so
  a provider without tools is never chosen. Do not depend on parallel
  calls.
- **Files.** `browser/tools.py`, `crew/diagnoser.py`, `crew/*.py`,
  `llm/chat.py`.
- **Accept.** A test walks every tool schema and fails on an optional
  field without a null type.

### MOD-5 `[agents]` settings reach every agent
- **Type.** Bug. **Priority.** P1. **Effort.** S.
- **Problem.** `[agents.tester]` and `[agents.challenger]` are never used;
  `max_steps` reaches two agents; `provider` without `model` is silently
  ignored.
- **Do.** `contexer test` reads `[agents]`. `max_steps` applies to every
  agent. A setting that cannot be applied is an error at start.
- **Files.** `cli/test_cli.py`, `cli/run_cli.py`, `config/project.py`,
  `crew/triage.py`, `crew/intent.py`, `graph/context.py`.
- **Accept.** `test_each_agent_runs_on_the_model_it_was_given` extended to
  the Tester and the Challenger.

---

## Evaluations

### EVAL-1 The model matrix
- **Type.** Evaluation. **Priority.** P1. **Effort.** L. **Depends on.**
  MOD-1, MOD-2, EVAL-3.
- **Do.** Run the tester suite on the held-out app and two others, and the
  reviewer suite, on six models: the current baseline, Claude Haiku 5.5,
  DeepSeek V4.1 Flash, GLM-5.3-Flash, Qwen3.6-35B on a local server, and
  gpt-oss-20b on Ollama. Five repeats each. Record found, false alarms,
  repaired and text-fallback tool calls, tokens, cost, time.
- **Files.** `bench/tester.py`, `bench/reviewer.py`, `cli/bench_cli.py`,
  `bench/RESULTS.md`.
- **Accept.** The table is published with intervals and its total cost,
  and `llm/catalog.py` ships the measured rows.
- **Needs.** Keys for the hosted models and a machine for the local ones.

### EVAL-2 A weak coding model, with and without Contexer
- **Type.** Evaluation. **Priority.** P1. **Effort.** M. **Depends on.**
  EVAL-3.
- **Problem.** The repair suite is too easy for a strong model to show
  whether Triage and the Diagnoser earn their cost, and nothing measures
  the claim that Contexer makes a cheap model usable.
- **Do.** On the repair suite's 46 bugs, with OpenCode on two cheap
  models: (1) one turn with the goal and no Contexer; (2) Contexer's loop
  with rules only; (3) the loop with Triage and the Diagnoser. The outcome
  is the same in all three: the contract replayed at the end.
- **Accept.** Proven rate, attempts, cost per proven fix and cost of
  failed runs for each arm, over five repeats, in `bench/RESULTS.md`.
  This decides the positioning in [roadmap.md](roadmap.md) §1.

### EVAL-3 Repeats and intervals
- **Type.** Evaluation. **Priority.** P1. **Effort.** S.
- **Do.** `--repeats N` on every suite; results report a rate with a
  Wilson interval and say when two results cannot be told apart.
- **Files.** `bench/*.py`, `cli/bench_cli.py`.
- **Accept.** Two runs of the same configuration are reported as not
  different.

---

## Cost

### COST-1 Unknown cost is said, and a budget that cannot be enforced is refused
- **Type.** Cost, bug. **Priority.** P1. **Effort.** S.
- **Problem.** Codex and OpenCode report no cost, and a provider may
  report no price: both count as 0 against `[agents] max_usd`.
- **Do.** When a run has a money budget and a part of its spend cannot be
  known, say so before the run and ask for rates or a token budget. In the
  summary, "unknown" is a word, never `$0.00`. A reached token or cost
  limit stops coding turns too.
- **Files.** `crew/budget.py`, `graph/context.py`, `cli/run_cli.py`,
  `agents/opencode_agent.py`, `agents/codex_agent.py`.
- **Accept.** `--max-usd 2` with Codex and no rates stops at start with a
  sentence that says what to set.

### COST-2 Cached input is used and counted
- **Type.** Cost. **Priority.** P2. **Effort.** S.
- **Do.** Set cache markers on the system prompt and tools for Anthropic;
  send a session id on OpenRouter; read cached tokens from usage into the
  transcript and the budget at the cached price.
- **Files.** `llm/chat.py`, `crew/base.py`, `crew/budget.py`.
- **Accept.** A 20-step Tester run on a provider with caching shows cached
  tokens above zero from the second call.

### COST-3 A price per model
- **Type.** Cost. **Priority.** P2. **Effort.** S. **Depends on.** MOD-1.
- **Do.** Price each agent's calls from its own model's record. One rate
  pair in `[agents]` stays as an override.
- **Accept.** A run with two models bills each at its own price.

### COST-4 One budget for `contexer test` too
- **Type.** Cost. **Priority.** P2. **Effort.** S.
- **Do.** `contexer test` reads `[agents] max_usd` and the rates.
- **Files.** `cli/test_cli.py`.

---

## Observability

### OBS-1 One trace file per run
- **Type.** Monitoring. **Priority.** P1. **Effort.** M.
- **Do.** `trace.jsonl` in the run folder: one line per run event, model
  call and tool call, named after OpenTelemetry's generative-AI
  conventions with the version in the first line. Per model call: agent,
  provider, requested and answering model, tokens in, out and cached,
  finish reason, retries, seconds, cost and whether it is estimated. Per
  tool call: name, `ok`, `repaired`, `text-fallback` or `failed`, seconds.
  No prompt or page content unless `--trace-content`.
- **Files.** `crew/transcript.py`, `crew/base.py`, `graph/engine.py`,
  `evidence/rundir.py`.
- **Accept.** The events printed by `--json` are the same lines as in the
  file. A run with no flag stores no prompt text in the trace.

### OBS-2 What the coding agent was asked, kept
- **Type.** Monitoring. **Priority.** P1. **Effort.** S.
- **Do.** Save each attempt's prompt and the Diagnoser's lead in the
  attempt folder, masked as prompts already are. A Diagnoser that fails
  emits an event.
- **Files.** `graph/nodes.py`, `evidence/rundir.py`, `evidence/report.py`.
- **Accept.** `report.html` shows, per attempt, what was sent.

### OBS-3 `runs --stats` by model, and as JSON
- **Type.** Monitoring. **Priority.** P2. **Effort.** S. **Depends on.** OBS-1.
- **Do.** The model id in `run.json`. `contexer runs --stats --by model`
  and `--json`: proven rate, attempts, cost per proven run, tool error and
  repair rates.
- **Files.** `cli/runs_cli.py`, `evidence/test_report.py`.

### OBS-4 Optional OpenTelemetry export
- **Type.** Monitoring. **Priority.** P3. **Effort.** S. **Depends on.** OBS-1.
- **Do.** When `OTEL_EXPORTER_OTLP_ENDPOINT` is set, send the trace's
  spans there. An optional extra; nothing is sent otherwise.
- **Accept.** A local Phoenix or Langfuse shows a run.

---

## Context

### CTX-1 The Diagnoser sees what was already tried
- **Type.** Agent architecture. **Priority.** P1. **Effort.** S.
- **Do.** Give the Diagnoser each earlier attempt's lead, the files it
  changed and which checks moved. Tell it to say when its lead repeats an
  earlier one.
- **Files.** `graph/nodes.py`, `crew/diagnoser.py`.
- **Accept.** In a three-round scripted run the third task contains the
  first two leads.

### CTX-2 The diff is ordered by what failed
- **Type.** Context. **Priority.** P2. **Effort.** S.
- **Do.** Before cutting a diff to size, put first the files whose names
  appear in page errors, the server log and the failed steps; then the
  rest, smallest first. Say which files were left out.
- **Files.** `crew/diagnoser.py`, `crew/reviewer.py`, `checkpoint/shadow.py`.

### CTX-3 Long conversations drop old page snapshots
- **Type.** Context. **Priority.** P2. **Effort.** M. **Depends on.** MOD-1.
- **Do.** When a conversation passes a share of the model's window, replace
  the content of tool results older than the last few with a one-line
  note. Findings already recorded are never dropped.
- **Files.** `crew/base.py`.
- **Accept.** A Tester run on a model with a 32,000-token window finishes
  its steps.

### CTX-4 A cached project summary
- **Type.** Context. **Priority.** P3. **Effort.** S.
- **Do.** Store the inspector's summary keyed by the snapshot's tree hash
  and reuse it while the tree is unchanged.

---

## Connecting to coding agents, and instructing them

Added on 2026-11-24 after the owner set the direction
([roadmap.md](roadmap.md) §1). There are two ways round, and both are
wanted: Contexer starts the agent (built: the adapters in `agents/`), and
an agent a person is already using calls Contexer (not built).

### INT-1 An MCP server
- **Type.** New capability. **Priority.** P0. **Effort.** M. **Depends on.**
  SEC-2.
- **Problem.** An agent a person is already working in cannot ask
  Contexer anything. MCP is the one protocol Claude Code, Codex, OpenCode,
  Cursor and the rest all speak.
- **Do.** `contexer mcp`: a server over stdio with a small, flat set of
  tools. `contexer_checks` returns the approved contract as the agent
  should read it. `contexer_verify` replays it and returns, per check,
  passed or what the browser saw, with the Diagnoser's lead when a model
  is configured. `contexer_brief` returns the brief of BRIEF-1 for a goal.
  `contexer_status` returns the run's attempts and budget. No tool
  approves a contract, edits one, or changes a setting: approval stays
  with a person, in the terminal or on the pull request.
- **Files.** New `mcp/server.py`, `cli/__init__.py`, `gate/session.py`.
- **Accept.** In Claude Code with the server configured, "make the count
  right" ends with the agent having called `contexer_verify` and fixed
  what it returned, on the demo app. The tool audit test covers the
  server: no tool writes.
- **Tests.** The server driven by a scripted MCP client; a call that tries
  to approve is refused.

### INT-2 "Done" is refused while a check fails
- **Type.** New capability. **Priority.** P1. **Effort.** S. **Depends on.**
  INT-1.
- **Problem.** An agent that may call a verifier may also not call it. A
  rule in a prompt is advice; a hook is code.
- **Do.** `contexer init --agent claude-code` writes a Stop hook that runs
  `contexer verify --json` and, while an approved contract fails, blocks
  the stop and hands the agent what failed. A cap on how many times in a
  row, so a check that cannot pass does not loop for ever; then it stops
  and says so. The same for Codex and OpenCode where their hooks allow it,
  and a statement of where they do not.
- **Files.** `cli/init_cli.py`, new `integrations/`.
- **Accept.** In Claude Code on the demo app with the bug in place, the
  agent cannot end its turn until the contract passes or the cap is
  reached.
- **Tests.** The hook script run against a failing and a passing project.

### BRIEF-1 The first instruction is a brief, not a template
- **Type.** Agent architecture. **Priority.** P1. **Effort.** M.
  **Depends on.** REL-3, CTX-5.
- **Problem.** `controller/prompts.py: implement_prompt` sends the goal,
  the checks, fifty file names and the rules. Everything a senior engineer
  would add is missing, so the first attempt is the coding agent's guess
  and the repair rounds pay for it.
- **Do.** A Planner step before the first turn, read-only, with the
  Diagnoser's tools. It returns a `TaskBrief`: the files to change and to
  read first (checked to exist, as `RepairBrief` is), what already exists
  that the change should reuse, the order of work, the edge cases the
  checks imply, and what must not change. The checks and the rules are
  still inserted by code, word for word. With no model, or over budget,
  the template is sent as now.
- **Files.** New `crew/planner.py`, `crew/prompts/planner.md`,
  `graph/nodes.py`, `controller/prompts.py`, `crew/estimate.py`.
- **Accept.** The brief names only files inside the project; a steered
  Planner cannot point at `.env` or `.contexer/`; the tool audit lists it.
- **Tests.** As for the Diagnoser, with a scripted model.

### BRIEF-2 Does the brief pay for itself
- **Type.** Evaluation. **Priority.** P1. **Effort.** M. **Depends on.**
  BRIEF-1, EVAL-3.
- **Do.** A feature suite, not a bug suite: ten small features across the
  benchmark apps, each with an approved contract. Two arms per coding
  model (one strong, one cheap): the template and the brief. Five repeats.
- **Accept.** First-attempt pass rate, attempts to proven, and cost per
  proven feature for each arm, in `bench/RESULTS.md`. If the brief does
  not raise the first-attempt rate on the cheap model, it is off by
  default.

### CTX-5 Context from where the task came from
- **Type.** Context. **Priority.** P1. **Effort.** M.
- **Problem.** Contexer reads the goal sentence. The rest of what a person
  would tell a colleague is elsewhere: the ticket's discussion, the
  project's own instruction files, earlier decisions.
- **Do.** Three sources, each quoted as data and capped. The issue or
  ticket with its comments, when the run starts from one. The project's
  instruction files (`AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`), for the
  Planner and the Reviewer: a change that breaks a stated convention is a
  note. The intent store, which exists. Say in the run view which sources
  were read.
- **Files.** `graph/context.py`, `github/issues.py`, `crew/intent.py`,
  `crew/reviewer.py`.
- **Accept.** A convention stated in `AGENTS.md` appears in the brief, and
  a change that breaks it gets a Reviewer note that quotes the line.
- **Tests.** The injection suite of `tests/test_security.py` extended to
  the three new channels.

---

## Developer experience

### DX-1 Contexer from inside the coding agent
- **Type.** New capability. **Priority.** P0. **Effort.** S. **Depends on.** INT-1, INT-2.
- **Problem.** People live in their coding agent; Contexer is a second
  terminal.
- **Do.** `contexer init --agent NAME` for Claude Code, Codex and
  OpenCode: registers the MCP server (INT-1), writes the hook (INT-2) and
  a short skill that tells the agent when to call them and that it may
  not edit `.contexer/`.
- **Files.** `cli/init_cli.py`, new `integrations/`.
- **Accept.** In Claude Code on the demo app, "fix the count" ends with
  the agent having run `contexer verify` and reporting its result.

### DX-2 Evidence in the pull request
- **Type.** New capability. **Priority.** P1. **Effort.** M.
- **Do.** One screenshot per check, and a failed check's last screen,
  committed to an orphan branch or uploaded as a workflow artifact and
  linked from the pull request body.
- **Files.** `github/handoff.py`, `evidence/report.py`.

### DX-3 Three operating systems
- **Type.** Release engineering. **Priority.** P0. **Effort.** M.
- **Do.** CI on Ubuntu, macOS and Windows for the tests that need no
  browser, and the gate benchmark on each weekly. Follow `docs/try-it.md`
  from a clean install on macOS and Linux and fix what it shows.
- **Files.** `.github/workflows/ci.yml`, `docs/try-it.md`.
- **Accept.** Green on three systems; the guide's commands run as written.

### DX-4 The run view
- **Type.** Terminal UX. **Priority.** P2. **Effort.** M. **Depends on.** OBS-1.
- **Do.** [roadmap.md](roadmap.md) §6, items 1 to 6.
- **Files.** `cli/runview.py`, `cli/term.py`, `cli/runs_cli.py`.
- **Accept.** Snapshot tests of the view at 80 and 120 columns, with and
  without colour.

### DX-5 Prune old runs
- **Type.** DX. **Priority.** P2. **Effort.** S.
- **Do.** `contexer runs prune --keep N` removes run folders and collects
  the snapshot repository when no run holds the lock.
- **Files.** `cli/runs_cli.py`, `checkpoint/shadow.py`.

---

## New capabilities

### AGT-1 A broken earlier behaviour is its own finding
- **Type.** New capability. **Priority.** P1. **Effort.** M.
- **Pain.** Fixing one thing breaks another. **Why agents miss it.** They
  test what they just built.
- **Do.** A check from an earlier contract that passed at the baseline and
  fails now is reported as a regression with the attempt that broke it,
  and repaired before the new work. A check that already failed at the
  baseline is reported as stale and does not block.
- **Tools, model.** None new; no model.
- **Files.** `graph/nodes.py`, `controller/shared.py`, `gate/decision.py`.
- **Evaluate.** A seeded suite: each bug of the gate benchmark introduced
  by a change that satisfies a new contract.

### AGT-2 Dependency checker
- **Type.** New capability. **Priority.** P2. **Effort.** S.
- **Pain.** Invented and typo-squatted packages.
- **Do.** For every package a change adds to a manifest: does it exist in
  its registry, when was it first published, how many releases. A package
  that does not exist is a high note; one published in the last 30 days is
  a medium one. Network access to the registries only.
- **Model.** None. **Files.** `crew/reviewer.py`, new `crew/dependencies.py`.
- **Evaluate.** Twenty manifests: ten with a planted name, ten clean.

### AGT-3 Scope guard
- **Type.** New capability. **Priority.** P2. **Effort.** M.
- **Pain.** Tests bent to pass; safeguards removed; unrelated changes.
- **Do.** Extend the scan: assertions removed, a `confirm` or a
  validation removed, files changed that the goal and the Diagnoser's lead
  never named, each as a counted note with the lines.
- **Model.** None. **Files.** `crew/reviewer.py`.
- **Evaluate.** "Passed for the wrong reason" cases added to the reviewer
  suite.

### AGT-4 Access prober, and an HTTP check
- **Type.** New capability. **Priority.** P2. **Effort.** L. **Depends on.**
  SEC-3.
- **Pain.** Missing access control in AI-built apps; a browser check on
  one account cannot see it.
- **Do.** A check kind that makes one HTTP request with a named session
  and asserts on status and body. With two accounts in `[auth]`, after the
  checks pass: replay the first account's recorded API reads with the
  second account's session. A read that succeeds is a finding with the
  request that proves it.
- **Tools.** The app's own API, on its own origin. **Model.** None for the
  probe.
- **Files.** `verification/checks.py`, `verification/runner.py`, new
  `crew/access.py`.
- **Evaluate.** A fixture app with one endpoint that checks ownership and
  one that does not.

---

## Documents and clean-up

### DOC-1 What Contexer sends, and what it does not do
- **Type.** Documentation. **Priority.** P0. **Effort.** S.
- **Do.** One page: which text goes to which provider for each command;
  that nothing else leaves the machine; web apps only; never writes code;
  what the coding agent can still do that Contexer does not control.
- **Files.** `docs/`, `README.md`, `SECURITY.md`.

### DOC-2 Troubleshooting from real failures
- **Type.** Documentation. **Priority.** P2. **Effort.** S. **Depends on.**
  the beta.

### CLN-1 One model client, and what is left of 0.4
- **Type.** Architecture. **Priority.** P3. **Effort.** M.
- **Do.** Move check drafting without tools onto the LangChain client and
  remove `llm/openrouter.py`, `llm/anthropic.py` and the duplicated
  precedence in `llm/factory.py`. Remove the `classic` engine name and the
  `app_error` end state. Share `_run_blocking` between the Claude Code and
  Codex adapters.
- **Accept.** No behaviour change; the suite passes.
