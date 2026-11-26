# Try Contexer yourself

Two paths: **as a user** (install it and use it on an app) and **as a
developer** (work on Contexer itself). Each step says what you should see, so
you can tell when something is wrong.

## As a user

The first four steps take about ten minutes and end with your first
`contexer test` result, on a small app that Contexer creates for you. Step 5
is your own app.

### 1. Install (2 minutes)

You need Python 3.11 or newer and git. Node.js is needed only if your own app
is JavaScript with a dev server.

```bash
uv tool install contexer-agent
contexer --version
```

You should see `contexer 0.6.0` or newer.

- `uv tool install` (or `pipx install contexer-agent`) puts Contexer in its
  own environment and the `contexer` command on your PATH. No uv? On Windows:
  `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`; on macOS and
  Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- `pip install contexer-agent` works too, but read the Windows notes below if
  `contexer` is then "not recognized".
- The package is `contexer-agent`. `pip install contexer` installs a different
  project that owns that name on PyPI.
- For the newest code before a release, install from GitHub:
  `uv tool install "git+https://github.com/murtuza777/contexer-agent.git#subdirectory=contexer-agent"`.

#### If the install fails on Windows

- **`Fatal error in launcher: Unable to create process using "...\Python312\python.exe" ...pip.exe`**:
  the `pip` on your PATH belongs to a Python that was uninstalled or moved.
  Use `uv tool install contexer-agent`, or `py -m pip install contexer-agent`,
  and remove the stale `...\Python312\Scripts` folder from your PATH.
- **`contexer : The term 'contexer' is not recognized`**: either the install
  failed (scroll up for the error), or pip put the command in a Scripts folder
  that is not on PATH (pip prints a warning naming it). Use
  `uv tool install` or `pipx`, which put it on PATH, or run it as
  `py -m contexer`. Open a new terminal after changing PATH.

### 2. Watch it catch a bug, with no key (1 minute)

```bash
contexer demo
```

A new install has no browser yet. The demo offers to download Chromium
(about 150 MB, once); say yes. `contexer setup --browser` does the same on
its own.

It creates `contexer-demo/`, a todo app that a coding agent "finished" with a
bug left in, and runs the app's 7 approved checks in Chromium. Expect
`FAIL: 6 verified, 1 refuted, 0 unverified`, with `expected ... "1 left"`
and `actual: "2 left"` under the check that failed. No model was called:
replaying approved checks never needs one.

### 3. Set up a model (2 minutes)

`contexer test` and `contexer run` use a model of your choice, with your key.

```bash
contexer setup
contexer doctor
```

`contexer setup` asks for a provider, your key (hidden as you type) and a
model. It sends one real request to the model. Nothing is saved unless the
model answers. `contexer models --providers` lists
the 15 providers; for free use, pick **openrouter** with a key from
https://openrouter.ai/keys. A stronger model tests better.

In `contexer doctor` every line should be ✓ or !; a ✗ prints its fix
underneath. It also says whether your model can call tools, which
`contexer test` needs.

Prefer not to save a key? Export it instead (`ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, or `AZURE_OPENAI_API_KEY` with
`AZURE_OPENAI_ENDPOINT`) and pass `--provider` and `--model` to the command.

### 4. Your first `contexer test` (3 to 5 minutes)

Say what the app should do, in your own words. Contexer uses the app like a
person would and tells you what does not hold.

```bash
cd contexer-demo
contexer test "Users can add tasks and complete them, and the remaining count stays correct"
```

What happens, in order:

1. If the sentence can be read two ways, Contexer asks which you meant
   (at most a few questions; `--yes` takes the likeliest reading and says
   which it took).
2. The tester uses the app in Chromium. This is the slow part: a few
   minutes, and it is where the model's tokens go.
3. Every finding is replayed by code in a fresh browser. Only findings that
   replay are reported; a finding that does not is counted as unconfirmed
   and never called a bug.

You should see, in this order:

- **Confirmed bugs**, each with the steps that reproduce it and what the
  browser saw. On this app: ticking a task throws `refesh is not defined`,
  and the count stays at `2 left` where `1 left` was expected.
- The behaviours that work, and anything the sentence did not settle, as a
  question for you and not as a bug.
- A **fix prompt**, printed in full and saved as `fix-prompt.md` in the
  run's folder. Add `--copy` to the command to put it on the clipboard.
- The paths of the intent Contexer wrote down and of the report.

The exit code is 1 because there are confirmed bugs. No application code was
changed. When this guide was last followed from a clean install (Windows 11,
`gpt-5.4`), this step found both bugs in 20 tester steps.

Then close the loop. Paste the fix prompt into your coding agent (Claude
Code, Codex, Cursor, any of them) in the `contexer-demo` folder. When it
says it is done:

```bash
contexer test --again
```

`--again` replays the checks the last run saved, with no model. You should
see the checks that failed now pass. If one still fails it says which and
stops; nothing is taken on the agent's word.

Things worth trying:

- **It got your meaning wrong:** `contexer test --correct "deleting should
  ask first"` records what you meant and tests again.
- **Keep the checks:** `--save` writes them as a draft contract you can
  approve and replay in CI.
- **Limit the spend:** `--steps N` caps the tester's model calls,
  `--max-tokens N` caps the whole run.

### 5. Use it on your own app

In your app's folder:

```bash
contexer test "what your app should do, in a sentence or two"
```

Contexer starts the app itself (static files, Vite, Next.js, or `[app]
start` in `contexer.toml`), or uses one you already run with `--url`. For an
app behind a login, add `[auth]` to `contexer.toml` and keep the credentials
in environment variables named `CONTEXER_TEST_...`
([how](../README.md#apps-behind-a-login)).

To have a coding agent build something and have Contexer prove it, you need
one of Claude Code, Codex or OpenCode installed, and a git repository:

```bash
contexer run "Users can export their data as CSV" --pr
```

What happens, in order:

1. Contexer starts your app, writes down what it understood, drafts checks
   from the goal and the app as it is, and asks about anything unclear.
2. It shows the checks and asks **Approve these checks?** Read them; this is
   your definition of done. Answer `y`, `n`, or type what to change.
3. Before the coding agent starts, a line says what the run can cost at
   most. `--max-usd 5` sets one budget for everything.
4. The coding agent works. A block in the terminal shows every check with
   its state, what is happening now, and the time and money so far.
5. Contexer proves every check in Chromium. What fails goes back to the
   agent with what the browser saw, up to 2 repair rounds; an attempt that
   makes things worse is undone.
6. When the checks pass, the diff is read once for things a check cannot
   see (a secret, a deleted test, a removed confirmation).
7. It ends with one summary: the outcome, the pull request (a draft if
   something still fails or the review found something serious), and the
   report.

Press Ctrl+C at any time: the agent stops at once and your files go back to
the best attempt. `contexer run --resume <run>` continues from where it
stopped; `contexer restore <run> --stopped` brings the unfinished work
back instead.

Things worth trying deliberately:

- **A goal your app already meets:** the preview says every check already
  passes, which warns that the checks may not test anything new.
- **Reject the checks (`n`):** nothing changes.
- **Replay later:** `contexer verify --all` re-runs every approved check with
  no model.
- **In CI:** `contexer run ... --yes --json` prints the run as one event
  per line.

### 6. Guard pull requests and take issues on GitHub

```bash
contexer init --ci        # replays approved checks on every pull request
contexer init --issues    # label an issue "contexer", reply /contexer approve
```

Commit the workflow files. For `--issues`, add your model key as a
repository secret, and allow GitHub Actions to create pull requests
(Settings → Actions → General). Then label an issue `contexer`: a comment with
the checks appears; reply `/contexer approve` to have it built.

## As a developer

```bash
git clone https://github.com/murtuza777/contexer-agent.git
cd contexer-agent/contexer-agent
python -m venv .venv
source .venv/bin/activate         # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m playwright install chromium
```

Run the tests (about half an hour on a laptop; real Chromium, Node and git,
no network or model):

```bash
python -m pytest -q -p no:cacheprovider --deselect tests/test_opencode_integration.py::test_live_opencode_e2e
```

Add `--no-browser` to skip each test at the moment it starts a browser; the
rest run whole, in about 12 minutes. CI does that on Windows and macOS, and runs
everything on Linux.

Measure accuracy on the seeded-bug benchmark (about 10 minutes; do not run
other heavy jobs at the same time):

```bash
contexer bench --repeats 2
```

To test a change end to end without spending model requests, use the
scripted agent, which replays file edits from a JSON file:

```bash
echo '[{"app.js": "...the fixed file..."}]' > turns.json
contexer run --contract todo-basics --agent scripted --model turns.json --pr
```

To test with a real agent, put your model key in `contexer-agent/.env` (git
ignores it) and run `contexer run ... --agent claude-code` on a copy of a
fixture app from `bench/fixtures/`.

Where things live:

| Path | What |
| --- | --- |
| `src/contexer/cli/` | Commands; `term.py` is the terminal design every command uses, `runview.py` draws a run |
| `src/contexer/graph/` | The run loop: implement, prove, repair, review, keep the best attempt |
| `src/contexer/crew/` | Contexer's own agents: Intent, Tester, Diagnoser, Triage, Reviewer |
| `src/contexer/verification/` | The check language and the Playwright runner |
| `src/contexer/github/` | Pull-request hand-off and the issue flow |
| `bench/fixtures/` | The seeded-bug benchmark apps |
| `../website/` | The landing page (`npm run dev`) |
| `../marketing/launch-video/` | The launch video (`npm run studio`) |
