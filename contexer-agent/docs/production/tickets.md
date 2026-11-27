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
- **Done 2026-11-24.** See [audit.md](audit.md) §5.2 and the changelog.
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
- **As built.** No setting was needed. A hook that was there before the
  run still runs on a person's machine, without the repository token; a
  hook that is new or changed since the run began is not run and the pull
  request says so; in Actions no hook runs.
- **Files.** `github/handoff.py`, `checkpoint/shadow.py` (reuse
  `_NO_PROGRAMS`), `graph/context.py`.
- **Accept.** A scripted agent plants `pre-commit` and `pre-push` hooks
  that write `$GITHUB_TOKEN` to a file; after a hand-off to a local remote
  the file does not exist, and the hand-off says the hooks changed.
- **Tests.** `test_handoff_does_not_run_project_hooks`,
  `test_handoff_refuses_when_git_config_changed_during_the_run`.

### SEC-2 One filtered loader for `.env`
- **Done 2026-11-24.** See [audit.md](audit.md) §5.2 and the changelog.
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
- **Done 2026-11-24.** See [audit.md](audit.md) §5.2 and the changelog.
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
- **Done 2026-11-24.** See [audit.md](audit.md) §5.2 and the changelog.
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
- **Built 2026-11-26**, in `crew/diagnoser.py: project_tools`, so for the
  Diagnoser, the Planner and the Reviewer. Literal search by default;
  `regex=true` runs in a separate Python process that is killed at the
  limit; one search has 2 seconds for the walk and the matching, in both
  modes, and a search that runs out returns what it found and a line that
  says so. Tests: `test_grep_alternation_backtracking_is_bounded` and three
  more in `tests/test_diagnoser.py`. Open: nothing in the ticket. Not
  checked: a live model (whether it sets `regex` when it should); the
  2-second assertion is on wall-clock time and was run on Windows only
  before the pull request.

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
- **Built 2026-11-26.** `github/issues.py: visible_text` removes every
  character of category Cf, Co and Cn and the variation selectors; a draft
  asked for in a comment (`/contexer draft`, `/contexer answer`) needs
  write access (`cli/issue_cli.py: _writers_only`); the drafting prompt
  used when no tool-calling model is configured quotes a goal from an issue
  as data (`workflow/criteria.py`). Open: a character newer than the
  Unicode tables of the running Python counts as unassigned and is removed;
  emoji built from joiners or tags show as their parts; `contexer issue
  draft N` typed at a terminal has no commenter and is not checked. Not
  checked: the role check against the real GitHub (tested against the fake
  one).

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
- **Built 2026-11-26.** `procutil.py: child_env` (the dependency install,
  the dev server and the reset command) drops what `contexer setup` added
  and every `LANGFUSE_*` variable; a project `.env` that holds the same
  value as setup counts as the project's (`config/user.py:
  given_by_project`). Open: a key that is exported, or set in the project's
  `.env`, still reaches the app's processes (the ticket's rule); what the
  coding agent inherits (`agents/claude_code.py: agent_env`) is unchanged
  and waits on the owner; an app under test that needs a key only `contexer
  setup` saved no longer gets it.

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
- **Built 2026-11-26**, in `github/handoff.py` (`_plain`, `_inert`, `_code`,
  `_md`) with `tests/test_handoff_inert.py`. Covers the title, the commit
  subject and body, every field of the body, `Handoff.note` and
  `HandoffError`. Added beyond the ticket: `evidence/report.py: _data_uri`
  inlines only an image from the run's folder. Open: not checked against
  GitHub's own renderer; lists and rules inside the quoted goal still
  render; a URL in a note printed in the terminal or in `--json` has a
  zero-width space after `https:` and does not copy as a working link; the
  `contexer test` report calls `_data_uri` without the run folder.

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
- **Built 2026-11-26**, four of the seven items, in one commit:
  `credentials.toml` is created with mode 600 and `~/.contexer` with 700
  when `config/user.py` creates it; skills are capped on load (30 files,
  8,000 bytes each); `ContractGuard` puts back `.contexer/skills/*.md`,
  outside the digest a resume compares, and recreates a deleted contracts
  folder; the draft marker must start the comment. Open: a release tag in
  the workflow templates (`cli/init_cli.py` still says `@main`; the pull
  request says no tag exists, and `v0.6.0` was pushed the same day),
  Actions pinned by commit, Action inputs through `env:`, upper bounds on
  `openai`, `pydantic`, `python-dotenv`, `httpx`, `playwright`. Also open:
  `llm/capabilities.py: save_measurement` creates `~/.contexer` with the
  default mode when `contexer setup` measures a model before it saves the
  key, so the folder is not 700 then (the file is still 600); the
  "tampered" sentence in `graph/nodes.py` does not mention skills; a skill
  edited by hand while a run is in progress is undone and ends that run as
  tampered (the pull request also names `contexer test`, which cannot run
  then: it takes the run's lock); with more than 30 skill files the
  first 30 by name are read. Not checked: the two POSIX-only tests of the
  file mode had not run anywhere before the pull request.

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
- **Done 2026-11-26, as 0.6.0.** The work merged since 0.5.0 was more than a patch, so the
  first release is 0.6.0. The publisher was registered by the owner; the tag `v0.6.0`
  published through `release.yml`. Checked: `pip install contexer-agent==0.6.0` from PyPI in
  a new environment on Windows, then `contexer --version` and `contexer demo`. Open: the
  licence decision, and the same check on a machine that never had Contexer's browser.

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
- **Done 2026-11-25.** The message names the limit; no setting raises it yet (`MOD-1`). See [audit.md](audit.md) §5.1 and the changelog.

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
- **Done 2026-11-25.** See [audit.md](audit.md) §5.1 and the changelog.

### REL-4 Corrections are counted per mistake
- **Type.** Reliability. **Priority.** P1. **Effort.** S.
- **Problem.** Two corrections for an agent's whole run.
- **Do.** Reset the count after a valid step; keep a cap on corrections in
  a row. Say in the transcript how many were used.
- **Files.** `crew/base.py`.
- **Accept.** Three narrated steps spread over a 40-step run do not end it;
  three in a row do.
- **Tests.** `test_corrections_reset_after_a_valid_step`.
- **Done 2026-11-25.** See [audit.md](audit.md) §5.1 and the changelog.

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
- **Done 2026-11-25.** See [audit.md](audit.md) §5.1 and the changelog.

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
- **Done 2026-11-25**, with the proposed answer to *Decide first*: a flaky
  pass counts for the run and holds the pull request as a draft. The owner
  can still reverse that. Not done: the gate benchmark's time was not
  measured on this machine (CI runs the seeded-bug benchmark).

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
- **Done 2026-11-25.** See [audit.md](audit.md) §5.1 and the changelog.

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
- **Built 2026-11-26**, in `bench/gates.py` and the `gate` and `release`
  jobs of `release.yml`; the checklist is in `bench/README.md`. The gate
  job runs the gate benchmark on the tagged commit and requires the CI run
  on the same commit to have passed; `publish` needs it. Open: **the
  workflow has not been run** (no tag was made for it), so the accept line
  rests on the script's tests and on GitHub's rule for `needs`; the
  repair, reviewer and tester gates need a model key and are a person's
  step, not enforced; the release benchmark runs on Ubuntu only; PyPI
  trusted publishing is `REL-1`.

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
- **Built 2026-11-26**, in `llm/capabilities.py: ModelCapabilities`, with a
  source per fact: filled from OpenRouter's catalogue, from
  `catalog.MEASURED_MODELS` (one row: `gpt-5.4`, tool calling) and from one
  tool call by `contexer setup`, kept in `~/.contexer/models.json`. Shown
  by `doctor` and `setup`; a model known not to call tools is refused with
  the reason by `contexer test`, and `contexer run` says the reason and
  goes on under rules. Open: `crew/base.py` does not read the record, so no
  agent is built from it yet (`capabilities_of(model)` is there for it); no
  measured row has a window or a price until `EVAL-1`; `doctor` does not
  measure. Not checked: any live provider; the catalogue rows in the tests
  are written in the shape of OpenRouter's reply, not captured from it.

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
- **Built 2026-11-26.** Arguments are validated before the tool runs
  (`crew/base.py: _bad_arguments`), the error names the tool's required
  fields, and repaired calls are counted in `AgentResult`, the transcript
  and `run.json`. Open: `contexer test` does not put the count in its
  `result.json`; the count in `run.json` is read from the trace at the end
  of the run, not carried in the graph state, and a stopped and resumed run
  was not tested for it; a tool described by a plain JSON schema is not
  checked (no tool in the code base is one).

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
- **Built 2026-11-26.** `contexer test` reads `[agents]` (model and
  `max_steps` for intent, tester, challenger, diagnoser); Triage, Intent
  and the Challenger take `max_steps`; a model that cannot be built, a
  provider with no model and an unknown provider are errors at start.
  Open: `graph/nodes.py` does not pass `max_steps` to Intent and Triage in
  `contexer run`, so those two settings still do nothing there; the issue
  flow (`cli/issue_cli.py`) passes no per-agent models.

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
- **Built 2026-11-26**, in `bench/stats.py` (a Wilson interval per rate,
  Newcombe's interval for a difference): `--repeats` on all four suites,
  `--compare REPORT.json`, intervals in the terminal and on the results
  pages, and in `bench/RESULTS.md` for the published counts. Open: no suite
  has been re-run with repeats, so every published number is still one
  run; the gate suite repeats correct and benign code, not the bug
  variants; the intervals treat a repeat of a bug as independent of the
  first; only counts are compared, not cost, tokens or time.

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
- **Not built 2026-11-26.** It needs `crew/base.py` (`Budget.spend` is
  called with tokens only, without the model) and `graph/nodes.py: _cost`.
  The record of `MOD-1` has the prices: `capabilities_of(model)
  .input_usd_per_mtok` and `.output_usd_per_mtok`.

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
- **Built 2026-11-26**, in `crew/transcript.py: Trace`: `trace.jsonl` with
  the run's events, one line per model call and one per tool call, masked,
  with no prompt, reply, tool argument or tool result. The first line names
  the conventions version (`1.40.0`). Open: `--trace-content`; retries per
  model call (made inside the provider client and not reported, so the
  field is absent); the `text-fallback` status (`MOD-3`); `--json`'s own
  first and last line, which the CLI writes outside the engine, are not in
  the file. A run event is written as `--json` prints it, so a failed
  check's reason can quote text from a page. Not checked: the version
  `1.40.0` against OpenTelemetry's release notes.

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
- **Built 2026-11-26.** Leads are kept in the run state (`graph/state.py`,
  `graph/nodes.py: diagnose_node`) and shown to the next diagnosis with the
  files the following attempt changed and the checks that moved
  (`crew/diagnoser.py: tried_section`; the latest 5 leads); the prompt asks
  for a repeat to be named. Test:
  `test_the_diagnoser_is_shown_the_leads_that_were_already_tried` (a
  three-round scripted run). Open: no code detects a repeated lead; no live
  measurement of whether the model names one.

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
- **Built 2026-11-25**, in `integrations/mcp_server.py` (not `mcp/`, which
  would shadow the SDK's package name). Open: `contexer_verify` does not
  add the Diagnoser's lead yet; `contexer_brief` returns today's template
  until `BRIEF-1`; the acceptance run inside Claude Code has not been made.

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
- **Built 2026-11-26**, as a command (`contexer hook stop`) and not a
  shell script around `contexer verify --json`, so it is the same on
  Windows. Claude Code and Codex are written for; OpenCode has no hook
  that can refuse a stop (its issue asking for one was closed as not
  planned) and `init` says so. Added beyond the ticket: nothing is
  replayed when nothing changed since a pass. Acceptance run made on
  2026-11-26 in Claude Code 2.1.325 on the todo fixture with the count
  bug: told only to reply "done", the agent was refused once, fixed
  `app.js`, and the second replay passed (6 turns). Open: no run inside
  Codex; the hook command assumes `contexer` is on the agent's PATH.

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
- **Built 2026-11-26**, without `CTX-5`: the Planner reads the goal, the
  checks and the project, not tickets or `AGENTS.md`. It is its own node
  (`plan`, between `approve` and the first `coder_turn`), so `graph/routing.py`
  and `graph/state.py` changed too, and `RunSettings.plan` /
  `contexer run --no-plan` turn it off (`BRIEF-2` needs both arms). Open:
  no live run has been made, so the prompt, the step cap of 12 and the
  token figures in the estimate are untested against a real model; the
  brief is in the first instruction only, not in a fresh-session repair or
  a job restated after a correction; a file the change must create cannot
  be in the file lists (the check is "exists"); `contexer_brief` in
  `contexer mcp` still returns the instruction without a brief; the
  seeded-bug benchmark runs with the Planner off.

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
- **Built 2026-11-26.** Acceptance run made in Claude Code 2.1.325 on the
  todo fixture with the count bug, after `contexer init --agent
  claude-code`: the agent loaded the skill, called `contexer_checks`,
  edited `app.js`, called `contexer_verify` and reported "PASS: 7
  verified"; the stop hook then replayed and let it stop (10 turns). The
  same prompt with no Contexer set up ended with "I haven't run it in a
  browser or against the checks". The run was headless with the four
  tools allowed on the command line; an interactive session asks once.
  Open: no run in Codex or OpenCode (Codex's file shapes are from its
  documentation); OpenCode's server is not written, only pointed to;
  no further items.

### DX-2 Evidence in the pull request
- **Type.** New capability. **Priority.** P1. **Effort.** M.
- **Do.** One screenshot per check, and a failed check's last screen,
  committed to an orphan branch or uploaded as a workflow artifact and
  linked from the pull request body.
- **Files.** `github/handoff.py`, `evidence/report.py`.
- **Built 2026-11-26**, in `evidence/screenshots.py`, `github/handoff.py`
  (`_push_screenshots`, `_screenshot_lines`) and `cli/run_cli.py`
  (`--screenshots`), with `tests/test_handoff_evidence.py`. One commit with
  no parent on `contexer-evidence/<contract>-<commit8>`, off by default.
  The image links use the branch name, not the commit id, so deleting the
  branch removes them from the description. Open: no real pull request was
  opened, so image rendering (private repositories included) is
  unverified; the issue workflow (`contexer issue build`) has no switch
  for it; old evidence branches are not cleaned up; the push in Actions
  was not run.

### DX-3 Three operating systems
- **Type.** Release engineering. **Priority.** P0. **Effort.** M.
- **Do.** CI on Ubuntu, macOS and Windows for the tests that need no
  browser, and the gate benchmark on each weekly. Follow `docs/try-it.md`
  from a clean install on macOS and Linux and fix what it shows.
- **Files.** `.github/workflows/ci.yml`, `docs/try-it.md`.
- **Accept.** Green on three systems; the guide's commands run as written.
- **Built 2026-11-26**, in `ci.yml` and `tests/conftest.py`
  (`pytest --no-browser`). Green on all three: lint, types, the tests
  that start no browser (824 of 1,099 on Windows, 823 on macOS; 1,094 on
  Ubuntu, where 5 skip for other reasons), and a clean pipx install that runs steps 1 and 2 of the
  guide. The benchmark is 46 of 46 on Ubuntu and Windows. Open: **on macOS
  the benchmark missed `shop/load-crash`** in the one run it has had (all 8
  checks passed on the buggy app, a false pass), so the weekly macOS
  benchmark is expected to be red until that is understood; the likely
  place is the fixed 250 ms wait before `no_errors` is counted in
  `verification/runner.py`, not confirmed. Steps 3 to 5 of the guide need
  a model key and were not followed on macOS or Linux. The tests that use
  a browser run on Ubuntu only. The weekly schedule has not fired yet.
- **After it, 2026-11-26, three changes with no ticket.** (1) The macOS miss
  was the fixed 250 ms wait: `verification/runner.py` now counts the page's
  pending short timers (2 seconds or less) and asks `no_errors` once there
  are none, for at most 3 seconds. Gate benchmark on Windows with the
  change: 41 of 41 seeded bugs caught, 0 of 444 false failures. Open: not
  run on macOS, where the miss happened; an error from a timer longer than
  2 seconds, from `setInterval`, or from a network response that arrives
  after the timers are done is still outside the wait. (2) The three
  `Tests` legs run with `pytest -n auto` (pytest-xdist, in the `dev`
  extra); no test needed a change and there is no serial group. The Ubuntu
  job takes 11 to 12 minutes where it took 33 to 36. Open:
  `appserver/detect.py: free_port` closes the port before the dev server
  binds it, so another worker can take it in between (not seen in any
  run); seven tests wait 60 seconds each before `--no-browser` skips them.
  (3) A test failed on the Windows runner on `main`: two intent files saved
  in one tick of the file clock tied, and `intent/store.py:
  IntentStore.latest` named the wrong feature, so `contexer test --again`
  or `--correct` could act on the wrong one. A save now gives its file a
  time later than every other intent file. Test:
  `test_the_latest_is_the_one_saved_last_whatever_the_file_times_say`.

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
- **Built 2026-11-26** as a sub-command of `runs` (see
  [architecture §10](../architecture.md#10-snapshots)); `--keep` defaults to
  20 and may be 0; an unfinished run is kept unless `--include-unfinished`.
  Open: `verify` and `replay` do not take the run lock, so `--keep 0` during
  one of them removes the folder it is writing; snapshots whose run folder
  was deleted by hand are not found; snapshots taken without a name are
  collected only when a prune removes at least one run; there is no
  `--older-than` and no automatic pruning; tested on Windows only before the
  pull request (junctions; the symlink path runs in CI on Linux).

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
- **Not built 2026-11-26.** Today nothing is replayed before the first
  turn, so at attempt 1 a failing earlier check cannot be told apart:
  broken by this change, or already broken. It needs, in order: a baseline
  replay of the earlier contracts on the project as found, before the
  first coding turn, kept in the run state; stale checks left out of the
  score, the signatures, the repair prompt, the Diagnoser's failures and
  Triage's findings; a gate that does not fail on a stale check
  (`gate/decision.py: decide`), while `contexer verify` and the stop hook,
  which have no baseline, keep today's behaviour; the attempt that broke a
  check, walked back through `Attempt.reverted_to`; a repair prompt that
  puts regressions first; "stale" and "regression" in the gate's counts,
  the report, the terminal view and the pull request body; and the seeded
  suite. The full list is in the body of pull request 67. **Decision
  needed from the owner:** how a stale check is shown on a run that
  passes.

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
- **Built 2026-11-26.** [data-and-limits.md](../data-and-limits.md), linked
  from both READMEs, `SECURITY.md` and the docs index. Left open, all found
  while reading the code and none changed here: the drafting model's prompt
  carries page and source text unmasked and outside `<untrusted>`; masking
  covers tool results, not a diff or server log placed in a prompt; the
  coding agent inherits every model key in the environment, which
  `SECURITY.md` lists as a thing to report; what Chromium and the libraries
  send on their own was not examined.
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
