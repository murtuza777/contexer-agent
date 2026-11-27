# What Contexer sends, and what it does not do

Read against the source on 2026-11-27 (`main` after version 0.6.0, with the changes merged on 2026-11-26 and on 2026-11-27, pull requests 72 to 80).
Each statement names the code that makes it true as `path: function`, with
paths under `src/contexer/`. Where the code could not prove a statement it is
listed under [Not verified](#not-verified) and not claimed.

## Summary

1. Contexer calls a model only in the commands listed below as calling one. `replay`, `verify` without a goal, `demo`, `init`, `runs`, `restore`, `mcp`, `contract list/show/approve` and the default `bench` make no model call.
2. Model calls go to the provider you configured, with your own key. Contexer has no server of its own and contains no telemetry or update check.
3. A prompt can contain the goal, the checks, the page as an accessibility tree, file names, up to 8,000 characters of front-end source, diffs, the end of the dev server's log, the comments on the issue the goal came from (from people with write access), up to 6,000 characters each of `AGENTS.md`, `CLAUDE.md` and `CONTRIBUTING.md`, the stored intent, and any project file a read-only tool is allowed to open. Screenshots and the page's HTML are never sent to a model.
4. `.env` files and the usual credential files are closed to those tools and left out of snapshots and diffs. Other masking works on known values and three key patterns, so a secret of another shape that is hard-coded in a source file or printed to the server log can reach a prompt.
5. Contexer does not edit application code. The coding agent that `contexer run` starts does, with that agent's own permissions, network access and model provider, and Contexer does not sandbox it.
6. With `--pr`, `--issue`, `--github` or the `issue` commands, Contexer also talks to the GitHub API and pushes one branch. The review of a passing run sends the names of packages the change adds to `registry.npmjs.org` or `pypi.org`, unless `[review] dependency_lookup = false` is set or a registry of your own is. A run of a contract whose goal came from an issue also reads that issue's comments and the commenters' permission from the GitHub API, when a token is available. With `--screenshots` it pushes a second branch, `contexer-evidence/<contract>-<commit>`, that holds one JPEG screenshot per check.
7. Run evidence stays in `.contexer/` inside the project and can contain page content, source diffs and screenshots.
8. Contexer tests web apps in Chromium only.

## Two kinds of model call

| Called here | What it is | Where the request goes |
| --- | --- | --- |
| Drafting model | One request per draft, no tools. `workflow/criteria.py: GoalAnalyzer._analyze_with_llm` | The configured provider's HTTP API, through `llm/openrouter.py` (OpenAI-compatible) or `llm/anthropic.py`. Chosen by `llm/factory.py: compiler_provider` |
| Contexer's agents | Intent, Planner, Tester, Challenger, Triage, Diagnoser, Reviewer: a tool-calling loop. `crew/base.py: run_agent` | The same provider and key, through LangChain (`llm/chat.py: chat_model`). A project can name another model per agent in `contexer.toml`, for `run`, `test`, `issue build` and `issue draft` (`cli/run_cli.py: crew_models`, called by `cli/test_cli.py` and `cli/issue_cli.py`) |
| Coding agent | Claude Code, Codex or OpenCode, started as a separate program. `agents/__init__.py: create_agent` | Wherever that program sends it, with its own login. Contexer hands it a prompt on stdin, or over HTTP to the OpenCode server at `OPENCODE_SERVER_URL` (default `127.0.0.1:4096`), and does not see or route its requests. The prompt is masked first (see [What is kept out](#what-is-kept-out-and-where-that-stops)) |

The providers are the entries of `llm/catalog.py: PROVIDERS`, plus a base URL
you give. For OpenRouter each request carries the header `X-Title: Contexer`,
and `HTTP-Referer` only if you set a site URL (`llm/chat.py: chat_model_from`,
`llm/openrouter.py`).

Besides the prompt, a request of Contexer's agents carries
(`llm/chat.py: chat_model_from`, `_anthropic_class`; `crew/base.py: wire_schema`):

- On OpenRouter, two fields in the request body: `provider.require_parameters: true`,
  which asks OpenRouter for a provider that supports every parameter sent, and
  `session_id`, a random id made new for each model object (one agent's run), so
  the calls of that run can reach the same prompt cache. The id is not derived
  from you, the project or the machine. Whether OpenRouter uses the field has
  not been checked against OpenRouter.
- On Anthropic, a `cache_control` marker on the last tool and on the system
  prompt, which asks for both to be cached. Nothing more is sent because of it.
- On every provider, each tool and the agent's answer form as a function
  description with a strict argument schema (every field required, optional
  ones nullable, no extra properties). The `strict` flag is not sent, so no
  provider is asked to enforce the schema.

## Which command calls a model

| Command | Drafting model | Contexer's agents | Coding agent | Reference |
| --- | --- | --- | --- | --- |
| `setup` | One test request: "Reply with the single word: ok". When neither the provider's model list nor Contexer's own table says whether the model can call tools, one more exchange of two requests through the agents' client: "Use the add_numbers tool to add 19 and 23, then tell me the sum in one short sentence", then the tool's result. `--no-test` skips both | no | no | `llm/discovery.py: try_model`, `llm/chat.py: check_tool_calling`, `cli/setup_cli.py: _capabilities` |
| `models` | no (lists the provider's models) | no | no | `cli/setup_cli.py: models` |
| `doctor` | no (lists models, to show what is known about the configured one, and reads OpenRouter's free-request count) | no | no | `cli/doctor_cli.py: environment_findings`, `_model_findings` |
| `demo`, `demo --fix` | no | no | no (`--fix` replays a stored edit) | `cli/demo_cli.py: demo` |
| `init`, `runs`, `restore` | no | no | no | `cli/init_cli.py`, `cli/runs_cli.py` |
| `contract list`, `show`, `approve` | no | no | no | `cli/gate_cli.py` |
| `contract draft GOAL` | yes | no | no | `cli/gate_cli.py: contract_draft` |
| `verify GOAL` | yes | no | no | `cli/gate_cli.py: run_verification` |
| `verify --contract/--all`, `replay` | no | no | no | `cli/gate_cli.py: run_verification` builds `Verifier(llm_provider=None)` |
| `test GOAL` | no | Intent, Tester, Challenger, Diagnoser | no | `cli/test_cli.py: _Job.run` |
| `test --again` | no | none while a saved check fails (the fix prompt is then written by code alone); once they all pass: Tester, Challenger, Diagnoser | no | `cli/test_cli.py: _Job.run` (the `mode == "again"` branch) |
| `run` | only when no tool-calling model can be built: then the draft is made the older way | Intent (when drafting), Planner (unless `--no-plan`), Triage, Diagnoser, Reviewer | yes | `cli/run_cli.py: run`, `graph/nodes.py: make_nodes` |
| `issue draft` | fallback, as for `run` | Intent | no | `cli/issue_cli.py: draft` |
| `issue build`, `issue event` | no | Planner, Triage, Diagnoser, Reviewer | yes | `cli/issue_cli.py: build` |
| `issue publish` | no | no | no. It runs nothing from the project: it reads what a build or a draft left in a folder, asks GitHub again who approved which checks, and posts or pushes | `cli/issue_cli.py: publish` |
| `mcp` | no | no | no, but see below | `integrations/mcp_server.py: build_server` |
| `bench` | no | no | no | `cli/bench_cli.py: bench` |
| `bench --live` | yes | no | no | same |
| `bench --suite tester --agent` other than `stub`, `--suite reviewer --agent reviewer` | no | Tester, or Reviewer | no | `bench/tester.py: LiveTester`, `cli/bench_cli.py: _bench_reviewer` |
| `bench --suite repair` | no | as `run` | yes | `cli/bench_cli.py: _bench_repair` |

`verification/verifier.py: _judge_with_llm` can send a page's visible text and
3,500 characters of its HTML to a model. No command reaches it: every caller
in `cli/`, `graph/`, `integrations/` and `bench/` passes `llm_provider=None`.

`contexer mcp` makes no model call, but the agent that connects to it reads
what its tools return (the checks, the goal, and for `contexer_verify` what
the browser saw) and sends that to its own provider.

## What each prompt contains

| Prompt | Contents | Reference |
| --- | --- | --- |
| Drafting model | The goal (an issue's text is quoted as untrusted); project name, framework, entry points, up to 10 file names, up to 8 dependency names; the page's accessibility tree with test ids and placeholders (4,000 characters at most); up to 8,000 characters of front-end source (`.html .js .mjs .jsx .ts .tsx .vue .svelte`, entry points first); the check language guide. The page, the summary and the source are wrapped as untrusted, and the whole prompt is masked | `workflow/criteria.py: _analyze_with_llm`, `workflow/inspector.py: format_summary`, `_source_excerpt`, `observer/playwright.py: capture_ui_snapshot` |
| Intent | The goal (an issue's text is quoted as untrusted); what is already written about the feature and its corrections; ids and descriptions of existing checks; the same project summary (no source excerpt); the accessibility tree of the start page and of pages the goal names. In `run` and `issue draft`, when the goal came from a GitHub issue: that issue's comments from people with write access, quoted as untrusted | `crew/intent.py: _task`, `graph/nodes.py: _ui_snapshot`, `graph/context.py: RunContext.sources`, `cli/issue_cli.py: _discussion` |
| Tester | The written intent; the page's accessibility tree and URL; existing check descriptions; saved skills. Its tools return, on each call, the accessibility tree, the outcome of an action or expectation, and up to 15 console errors and failed requests with their URLs. `screenshot` writes a file and returns only its name | `crew/tester.py: _task`, `browser/tools.py: BrowserSession` |
| Challenger | The intent; per confirmed bug its title, the Tester's note, the steps, what the replay saw and the messages the app showed | `crew/challenger.py: _task` |
| Planner | The goal (an issue's text is quoted as untrusted); the approved checks, step by step; the goals of earlier contracts; the project summary; the issue's comments, the three instruction files and the stored intent, each quoted as untrusted (`crew/context_sources.py`). Through `read_file` and `grep` it can then read any text file in the project that is not closed (next section) | `crew/planner.py: plan_task`, `crew/context_sources.py: context_section` |
| Triage | Counts and names of failing checks per attempt, the limits left, and the first 6,000 characters of the latest failure report | `crew/triage.py: _task` |
| Diagnoser | The goal or intent; each failing check's steps and what the browser saw (expected and actual values, uncaught exceptions, console errors); a diff (12,000 characters at most, the files named by the failures and the server log first); the last 4,000 characters of the dev server's log. In `run`, from the second diagnosis on: its own earlier leads (cause and instruction, the latest 5), up to 12 names of the files each following attempt changed, and the names of the checks that then passed, broke or kept failing. Through `read_file` and `grep` it can then read any text file in the project that is not closed (next section) | `crew/diagnoser.py: diagnose`, `tried_section`, `project_tools`, `graph/nodes.py: _tried` |
| Reviewer | The goal; the passing checks' descriptions; notes a program already made (they include what the package registry answered about an added package and the list of changed files nothing named); the last 1,500 characters printed by a failed `npm run test`, `lint` or `typecheck`; the diff (30,000 characters at most, the smallest files first, with the files left out named); the issue's comments, the three instruction files and the stored intent, each quoted as untrusted (`crew/context_sources.py`); the same two read tools and a list of changed files | `crew/reviewer.py: _task`, `review`, `checkpoint/shadow.py: cut_diff` |
| Coding agent, first turn | The goal; the approved checks, step by step; the goals of other approved contracts; the project summary; fixed rules; then the Planner's brief when there is one (file names checked to exist in the project, its notes, and conventions quoted from an instruction file, kept only when code finds the quoted words in that file) | `controller/prompts.py: implement_prompt`, `with_brief`, `crew/planner.py: validated_task_brief` |
| Coding agent, repair turn | Failing checks with expected and actual values, the earlier checks this change broke first and named as regressions with the attempt that broke them; never an earlier check that was already failing before the run; up to 3 uncaught exceptions and 3 console errors each, dialogs, up to 25 lines of the page's accessibility tree when a step was blocked; the last 25 lines of the server log; the Diagnoser's cause, file names and instruction (capped at 800 and 1,500 characters); the Reviewer's notes; a correction or answer you typed | `controller/prompts.py: repair_prompt`, `crew/diagnoser.py: brief_section`, `crew/reviewer.py: review_repair_prompt` |

Where the diff comes from: in `run` it is the difference between Contexer's
own snapshots (`checkpoint/shadow.py: ShadowRepo.diff`). In `test` it is
`git diff` of your checkout's uncommitted changes to tracked files
(`cli/test_cli.py: _git_diff`).

Text that comes from the app is wrapped in `<untrusted source="...">` in the
agents' prompts and the repair prompt (`crew/untrusted.py: untrusted`). That
marks it for the model; it removes nothing.

The three context sources are read once per run (`graph/context.py:
RunContext.sources`, `crew/context_sources.py`):

- The issue's comments, when the contract's origin is a GitHub issue and a
  token is found: the newest 20 by people with write access, 1,500 characters
  each, 8,000 in all. Comments by others are counted and left out; a bot's
  comments, Contexer's own and `/contexer` commands are skipped
  (`github/issues.py: read_discussion`, `issue_discussion`).
- `AGENTS.md`, `CLAUDE.md` and `CONTRIBUTING.md` at the project's root, 6,000
  characters each, as they were in the snapshot taken before the coding
  agent's first turn (`checkpoint/shadow.py: ShadowRepo.read_file`). They are
  ordinary project files: a secret written in one of them is sent, apart from
  what the masker recognises.
- The stored intent, when it holds more than the goal, 4,000 characters.

HTML comments and invisible characters are removed from each
(`github/issues.py: visible_text`). The Planner and the Reviewer get all
three; the Intent agent gets the issue's comments; the Diagnoser, the Tester
and Triage get none.

Two things about the agents' conversations (`crew/base.py: _Run`):

- A tool call a model writes as text can be run as a call, on a model not
  known to call tools natively. It is limited to the agent's own tools and
  checked against the tool's schema, and a reply that carries the untrusted
  marker is never read for one (`crew/base.py: _text_call`,
  `llm/structured.py: parse_printed_call`).
- Past 60% of the model's context window, old tool results are replaced in
  what is sent by a one-line note (`crew/base.py: _drop_old_results`). The
  transcript on disk still holds every result in full.

## What is kept out, and where that stops

| Measure | What it does | What it does not do | Reference |
| --- | --- | --- | --- |
| Closed paths for `read_file` and `grep` | Refuses anything outside the project, and inside it `.contexer/`, `.git/`, `node_modules`, `.venv`, `venv`, `dist`, `build`, `.next`, `.aws`, `.ssh`, `.gnupg`; files named `.env`, `.env.*`, `*.env`, `.envrc`, `.npmrc`, `.netrc`, `.pypirc`, `.git-credentials`, `.dev.vars`, `credentials.toml`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*` and the other `id_*` key names. Links are resolved first | A secret in a file with any other name (`config.js`, `settings.py`, `secrets.json`) can be read and sent | `crew/diagnoser.py: _closed`, `project_tools` |
| Snapshot exclude list | `.env`, `.env.local`, `.env.*.local`, `.dev.vars`, `*.db`, `*.sqlite`, `*.sqlite3`, `*.log`, and whatever your `.gitignore` ignored when the run began, never enter a snapshot, so never a `run` diff | `.env.production` and similar are left out only if your `.gitignore` ignores them. The `test` diff comes from your own git and follows only its rules | `checkpoint/shadow.py: DEFAULT_EXCLUDES`, `_freeze_ignored` |
| Masking of prompts, tool results and transcripts | The task each of Contexer's agents is given, the drafting prompt, what a tool returns to an agent, and every line of a transcript and of `trace.jsonl`, have these replaced: the value of each provider key variable and of `GITHUB_TOKEN`, `GH_TOKEN`, `CONTEXER_GITHUB_TOKEN`, `CODEX_API_KEY`, `LANGFUSE_*` (6 characters or longer); the password, token or one-time code your `[auth]` sign-in types, and passwords the Tester typed; and text matching `sk-or-v1-...`, `sk-...` (20 or more characters) or `AIza...` where a word starts | Every prompt sent to the coding agent is passed through it too (`graph/nodes.py: coder_turn`, `controller/prompts.py: masked_for_agent`), and the kept `attempt-N/prompt.md` is the text that was sent. A password that is also an ordinary word is replaced wherever the word stands in the prompt. A key of any other shape (AWS, Stripe, a JWT, a session cookie, a database URL), or a transformed copy of a secret, is not recognised and is sent as it is | `crew/base.py: _Run.loop`, `graph/context.py: RunContext.secrets`, `crew/transcript.py: Masker`, `Trace.write`, `llm/base.py: sanitize_sensitive_text` |
| `${NAME}` values in checks | A check may read only `CONTEXER_TEST_*` and the names your `[auth]` section uses, never a repository token, model key or `LANGFUSE_*`. The expanded values are masked in check results, so in `result.json`, the report and repair prompts | Exact-match replacement of values of 3 characters or more; a transformed copy (encoded, split) is not matched | `verification/checks.py: secret_allowed`, `redact`, `CheckResult.redacted` |
| Password fields | The value shown for `input[type=password]` is masked in the accessibility tree | Only that input type | `observer/playwright.py: _mask_password_values` |
| Secret scan | Before a run, warns about an env file git does not ignore and about secrets in committed files. Before a push, scans the staged change and does not push on a hit | Pattern based; it reports and, apart from the push, does not block | `riskscan.py: scan_project`, `crew/reviewer.py: secret_kind`, `github/handoff.py: hand_off` |
| `.env` loading | Contexer reads the nearest `.env` and the project's `.env` into its own environment so it can find keys and `[auth]` credentials. It refuses names that steer git, proxies, certificates and interpreters | The values are not put in a prompt by Contexer, but its child processes inherit them (see Limits) | `config/project.py: load_env_file` |

The server log is masked the same way as each line is recorded
(`appserver/devserver.py: DevServer._record`), so `server.log`, the tail in
`result.json`, the Diagnoser's prompt and the repair prompt hold the masked
text. What the masker does not recognise passes through there too.

## Other network destinations

| Destination | When | What is sent | Reference |
| --- | --- | --- | --- |
| The model provider's `/models` | `setup`, `models`, `doctor`, and before agents start (to refuse a model without tool calling) | The key, as the auth header | `llm/discovery.py: list_models`, `llm/capabilities.py: model_capabilities` (called by `llm/chat.py: require_tools`) |
| OpenRouter `/key` | `setup`, `doctor`, and `run` when a free OpenRouter model is in use | The key | `llm/discovery.py: check_key`, `openrouter_free_quota` |
| GitHub REST API (`GITHUB_API_URL`, default `api.github.com`) | `run --issue`, `run --pr`, the `issue` commands, `verify/replay --github`; and any `run` of a contract whose goal came from a GitHub issue, when the project's remote is a GitHub repository and a token is found | Reads an issue, its comments, a user's permission and, in a build with `--hand-over`, the repository's record to see whether the token can push. A run of a contract from an issue reads that issue's comments (up to 1,000) and asks once per commenter for the permission. Writes issue comments (the drafted checks, run progress; with the two-job workflow the progress is one comment when the build has ended), a commit status (`contexer/acceptance`), and a pull request whose body holds the goal, the intent, each check with up to 200 characters of evidence, attempts and review notes, and with `run --screenshots` links to the pushed screenshots | `github/api.py: GitHubClient`, `GitHubClient.can_push`, `github/issues.py: read_discussion`, `github/status.py: post_status`, `github/handoff.py: pull_request_body` |
| Your git remote | `run --pr`, `run --issue`, `issue build`, `issue publish` | One new branch with one commit: the files the run changed and the contract file. With `run --screenshots`, when the remote is a GitHub repository and a token is found, a second branch `contexer-evidence/<contract>-<commit>` with one commit that has no parent and holds one JPEG per check (the app as the checks saw it, signed in when `[auth]` is set). Neither is pushed if the secret scan hits; the scan reads the staged change, not the screenshots. With `--hand-over`, `issue build` pushes nothing: it leaves the change as a patch in a folder, and `issue publish`, in a job of its own, pushes it as one commit after checking it | `github/handoff.py: hand_off`, `publish_patch`, `_push_screenshots`, `evidence/screenshots.py: check_screenshots` |
| The local `gh` program | When no token variable is set | `gh auth token` is run to read your token; Contexer makes no other `gh` call | `github/api.py: github_token` |
| Playwright's browser download | `setup` and `demo` when Chromium is missing, after you confirm; `setup --browser` without asking | Runs `python -m playwright install chromium` | `cli/setup_cli.py: ensure_browser` |
| The package registry | When the app's dependencies are missing | Runs the project's package manager install before starting the dev server | `appserver/devserver.py`, `appserver/detect.py: _install_argv` |
| Whatever the app loads | Every check and every Tester step | Chromium loads the app's own scripts, fonts, analytics and API calls. Navigation to another origin is refused; sub-requests are not filtered | `verification/runner.py`, `browser/tools.py` |
| `registry.npmjs.org` and `pypi.org` | In the review of a passing run, when the change adds a package to `package.json`, a requirements file or `pyproject.toml`. Turn it off with `[review] dependency_lookup = false` in `contexer.toml`, or `--no-review` for one run. Not made when a registry of your own is set in the project (`.npmrc`, `pip.conf`, an index option in the requirements file, a uv or Poetry source), in `~/.npmrc`, in pip's configuration or in `npm_config_registry`, `PIP_INDEX_URL` or `PIP_EXTRA_INDEX_URL`. Not seen as a registry of your own: npm's global config, a `pip.conf` inside a virtual environment, `C:\ProgramData\pip\pip.ini`, Yarn and pnpm settings, a registry given only on a command line | One GET per added package with the package's name in the address and the headers `Accept: application/json` and `User-Agent: contexer`, and nothing else: no key, no file content. 5 seconds at most, no redirect followed, at most 20 in a review. About sixty much used names are not looked up, and a name the registry's naming rules would refuse is never sent | `crew/dependencies.py: registry_lookup`, `dependency_findings`, `config/project.py: ReviewSettings`, `dependency_lookup` |
| Langfuse | Only if `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set and the `tracing` extra is installed | Every agent's prompts and replies as the model received them, through a LangChain callback | `crew/transcript.py: tracing_callbacks` |

There is no telemetry, crash reporting or update check in the package.
Checked by searching `src/contexer` for every HTTP client import and URL
literal: the only modules that open a connection are `llm/`,
`github/api.py`, `github/status.py`, `agents/opencode_agent.py` and
`opencode/client.py` (the local OpenCode server), `appserver/devserver.py`
(polling the app on localhost) and `crew/dependencies.py` (the package
registries, above).

To decide whether you use a registry of your own, the review reads the lines
that set a registry in `~/.npmrc` (or the file `NPM_CONFIG_USERCONFIG` names)
and in pip's configuration files, and the environment variables
`npm_config_registry`, `PIP_INDEX_URL` and `PIP_EXTRA_INDEX_URL`. It keeps
only yes or no: no address, token or password from those files is stored,
logged, sent or written into a note (`crew/dependencies.py: _sets_registry`,
`_user_registry`). A crash writes `crash.txt` in the run folder
and prints a link for you to report it (`graph/nodes.py: crashed_outcome`).

## What stays on disk

| Where | What | Can contain | Reference |
| --- | --- | --- | --- |
| `<project>/.contexer/contracts/`, `intent/`, `skills/` | Contracts, the written intent, advice saved by the Tester. Meant to be committed | The goal, check steps, short notes about the app | `contract/store.py`, `intent/store.py`, `skills/store.py` |
| `<project>/.contexer/runs/<id>/` | `result.json`, `report.html`, `run.json`, `server.log`, per-check screenshots, `observation_*.png`, `sign-in.jpg`, `screens/`, Playwright traces (`*.trace.zip`), `agents/*.jsonl` transcripts, `trace.jsonl`, `fix-prompt.md`, `checkpoint.sqlite`, `attempt-N/` with `prompt.md`, and `baseline/` when other approved contracts were replayed before the first turn | Page content, screenshots of the app (signed in when `[auth]` is set), the full source diff of the run (`run.json`), the server log (masked as each line is recorded, as above), every agent prompt and reply (masked as above; a transcript holds every tool result in full, also one that was later dropped from the conversation). `attempt-N/prompt.md` is what the coding agent was sent for that attempt, secrets masked; it can quote text and page content from the app. `trace.jsonl` holds the run's events and, per model call, the agent, provider and model names, tokens in, out and read from a cache, the finish reason, seconds, the cost and whether it is an estimate, and per tool call its name, seconds and one of `ok`, `repaired`, `text-fallback` or `failed`, masked; no prompt, reply, tool argument or tool result, but a run event can quote page text (a failed check's reason). A trace records request headers; for a signed-in check it is kept only with `--trace on` | `evidence/rundir.py`, `evidence/report.py`, `graph/nodes.py: coder_turn`, `baseline`, `crew/base.py: _Run`, `controller/shared.py: write_run_evidence`, `verification/runner.py: _capture_evidence`, `appserver/devserver.py: DevServer._record`, `crew/transcript.py: Transcript`, `Trace` |
| `<project>/.contexer/shadow.git` | A private git repository holding a copy of every non-excluded project file at each attempt | Your source code | `checkpoint/shadow.py: ShadowRepo` |
| `~/.contexer/` (or `CONTEXER_HOME`) | `config.toml`; `credentials.toml` with your keys (created with mode 0600 on POSIX; on Windows the mode bits do nothing); and `models.json`, what `contexer setup` measured about a model (provider id, endpoint URL, model id, whether it called a tool, the date; no key). The folder gets mode 0700 when Contexer creates it, whichever file is saved first; an existing folder is left as it is | API keys in plain text | `config/user.py: save_credential`, `home_dir`, `llm/capabilities.py: save_measurement` |

`.contexer/.gitignore` ignores everything there except `contracts/`,
`intent/` and `skills/` (`contract/store.py: ensure_contexer_dir`). Nothing
deletes old runs unless you run `contexer runs prune` (`cli/runs_cli.py: prune`).
With `run --screenshots`, the JPEG screenshots of the target contract's checks
also leave this folder for a branch of the remote (see above). In CI, the Contexer action (`action.yml` at the repository
root) uploads `.contexer/runs/` as the workflow artifact `contexer-report`,
which then holds all of the above for whoever can read the workflow run.
The issue action (`issue/action.yml`) uploads the same folder as
`contexer-report-issue-<n>-<attempt>`. In the two-job issue workflow that
`contexer init --issues` writes, the first job also uploads
`contexer-hand-over-<n>`: `handover.json` (the drafted checks, or the run's
outcome and its status lines, or the reason it stopped) and `change.patch`,
the run's change to your source as a patch (`cli/issue_cli.py: build`,
`github/handoff.py: make_patch`). The second job downloads it and runs
`contexer issue publish`. That workflow has not been run on GitHub yet.

## Limits

**Web apps only.** Every check is a step in Chromium against a URL
(`verification/runner.py: CheckRunner`). There is no check for a command-line
tool, a mobile app, an API without a page, or visual design. TLS certificate
errors are ignored in the test browser (`ignore_https_errors=True` in
`verification/runner.py`, `browser/tools.py` and `observer/playwright.py`).

**Contexer does not edit application code.** None of its agents has a tool
that writes (`tests/test_guardrails.py: test_each_agent_has_exactly_the_tools_in_the_audit_table`).
What Contexer itself writes in a project: `.contexer/`; `contexer.toml` and
workflow files from `init`; and files put back to a snapshot it took
(`restore`, a reverted attempt). It also runs, as programs, the project's
dev server and install command, the `[app] reset` command, and for the review
`npm run test`, `lint` and `typecheck`. Those are your project's code and can
do whatever that code does.

**The coding agent is not sandboxed by Contexer.**

| | What Contexer sets | What remains the agent's own | Reference |
| --- | --- | --- | --- |
| Claude Code | `--permission-mode acceptEdits`; a fixed list of allowed tools (file tools, package installs, build, lint, `git status/diff`); denied: edits under `.contexer/`, `git commit/push/reset/checkout`, `rm -rf` | Its login, its provider, its network access, your Claude Code settings and hooks | `agents/claude_code.py: ClaudeCodeAgent.argv` |
| Codex | `--sandbox workspace-write`, approvals `never`, network access on | Its login and provider. No rule protects `.contexer/` at the agent | `agents/codex_agent.py: CodexAgent.argv` |
| OpenCode | One added rule: edits under `.contexer/` are denied | Everything else in your OpenCode configuration, including shell access | `agents/opencode_agent.py: opencode_env` |

The agent's environment is yours without the repository tokens
(`GITHUB_TOKEN`, `GH_TOKEN`, `CONTEXER_GITHUB_TOKEN`, the Actions tokens) and
without a hosting agent session's variables (`agents/claude_code.py: agent_env`).
Every other variable is passed on, including every model key and the `[auth]`
test credentials loaded from `.env`. The dependency install, the dev server
and the reset command get your environment minus repository tokens, a hosting
agent session's variables, `LANGFUSE_*`, and the keys and choices saved by
`contexer setup` (`procutil.py: child_env`, `config/user.py: from_user_settings`);
a key you export or set in the project's `.env` still reaches them, and
`[app] env` is applied last; the review's npm
scripts get it minus any name containing key, token, secret, password,
credential or auth (`crew/reviewer.py: command_env`).

**What Contexer checks after the agent has run**

- The files that define done (`.contexer/contracts/*.json`, `.contexer/intent/*`, `contexer.toml`) are compared byte for byte after each turn and put back if changed; the run ends as tampered (`controller/shared.py: ContractGuard`). `.contexer/skills/*.md` is put back the same way; that includes a skill you edit by hand while the run is in progress.
- The verdict comes only from replaying the approved checks in Contexer's own browser; the agent's report is not used (`graph/routing.py: settle`).
- When the project has other approved contracts, their checks are replayed once before the first coding turn (`graph/nodes.py: baseline`). An earlier check that passed then and fails after an attempt is a regression and fails the run. One that already failed then does not fail the run: it is left out of the gate and listed as not proven in the verdict, `run.json`, the report and the pull request (`gate/decision.py: decide`). When that first replay could not run (the app does not start or load, or the sign-in fails), every earlier check that fails counts against the change. `verify`, `replay`, the MCP server and the stop hook have no such replay: a failing approved check fails there.
- An attempt that scores lower is reverted to the best snapshot (`checkpoint/shadow.py: ShadowRepo.restore`).
- Before a hand-off, a changed `.git/config` stops it, changed hooks are not run, and the staged change is scanned for secrets (`github/handoff.py: hand_off`).
- In the two-job issue workflow, the job that builds refuses to start when the API reports that its token can push (`cli/issue_cli.py: build`; when the API does not say, the build goes on). The job that publishes reads the approver and the approved checks from GitHub again, and refuses a change that touches `.github/`, a contract other than the approved one, a symbolic link or a submodule, that is over 5 MB, or in which the secret scan finds a secret (`cli/issue_cli.py: publish`, `github/handoff.py: publish_patch`, `patch_problems`). It cannot replay the checks: the "checks proven" it reports is what the first job said.

**What it cannot check**

- What the agent read, including files outside the project, and what it sent to its provider or anywhere else on the network.
- Anything the agent changed outside the project folder, or in paths the snapshot excludes (ignored files, `node_modules`, `.env`). A restore does not undo those.
- Whether code the agent wrote is safe to run. Contexer starts the app, and with it that code, on your machine with your environment minus repository tokens, `LANGFUSE_*` and what `contexer setup` saved.
- Behaviour no approved check covers. A pass means the checks passed, apart from earlier checks that were already failing before the run, which are listed as not proven.

## Not verified

- Requests Chromium makes on its own account, apart from the pages under test, were not examined.
- What the coding agents, LangChain, the `openai` client and Playwright send beyond the requests Contexer asks of them was not examined. One known case: the LangChain library reads `LANGSMITH_TRACING` / `LANGCHAIN_TRACING_V2` from the environment itself. Contexer never sets them, but if they are set in your shell, that library can send agent traces to LangSmith.
- Which host `playwright install` and your package manager download from depends on their own configuration.
- How each provider stores or uses what it receives is governed by your agreement with that provider, not by Contexer.
