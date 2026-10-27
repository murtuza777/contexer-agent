# Try Contexer yourself

Two paths: **as a user** (install it and use it on an app) and **as a
developer** (work on Contexer itself). Each step says what you should see, so
you can tell when something is wrong.

## As a user

### 1. Install (2 minutes)

Python 3.11 or newer, git, and Node.js if your app is JavaScript.

```bash
pip install "git+https://github.com/murtuza777/contexer-agent.git#subdirectory=contexer-agent"
contexer --help
```

You should see the commands grouped under *Get started*, *Build and prove*,
*CI and GitHub* and *More*.

Install from GitHub, not `pip install contexer`: that name on PyPI belongs to
another project.

### 2. Set up a model and a coding agent (2 minutes)

```bash
npm install -g opencode-ai     # the free coding agent; or use Claude Code or Codex
contexer setup
```

`contexer setup` asks for a provider, your key (hidden as you type) and a
model. It checks the key, sends one real request to the model, and offers to
install Chromium. Nothing is saved unless the model answers. For free use,
pick **openrouter** with a key from https://openrouter.ai/keys.

```bash
contexer doctor
```

Every line should be ✓ or !; a ✗ prints its fix underneath. It also shows how
many free OpenRouter requests are left today (50 a day; a small change takes
about 15).

### 3. Watch it catch a bug, with no key (1 minute)

```bash
contexer demo --fix
```

It creates `contexer-demo/`, a todo app with a bug, and proves its 7 checks in
Chromium. Expect `FAIL: 6 verified, 1 refuted` with `expected "1 left"`,
`actual "2 left"`. Then a simulated agent applies the fix and the run ends
`✓ Succeeded`. Open `contexer-demo/.contexer/runs/*/report.html` to see the
evidence report.

### 4. Use it on your own app

In your app's folder (a git repository with no uncommitted changes, if you
want a pull request):

```bash
contexer run "Users can export their data as CSV" --pr
```

What happens, in order:

1. Contexer starts your app (static, Vite, Next.js, or `[app] start` in
   `contexer.toml`), drafts checks from the goal, and tries each one on the app
   as it is today.
2. It shows the checklist and asks **Approve these checks?** Read them; this
   is your definition of done. Answer `y`.
3. The coding agent works. You see each file it reads or edits, and a live
   line with the elapsed time.
4. Contexer proves every check in Chromium. Failures go back to the agent
   with expected vs actual, up to 2 repair rounds.
5. It ends with one summary: the outcome, the pull request (or a draft if
   something still fails), the branch, and the report.

Press Ctrl+C at any time: the agent stops at once and your files go back to
the best attempt. `contexer restore <run> --stopped` brings the unfinished
work back.

Things worth trying deliberately:

- **A goal your app already meets:** the preview says every check already
  passes, which warns that the checks may not test anything new.
- **Reject the checklist (`n`):** nothing changes; edit
  `.contexer/contracts/<id>.json` and run `contexer run --contract <id>`.
- **Replay later:** `contexer verify --all` re-runs every approved check with
  no model.
- **An app behind a login:** add `[auth]` to `contexer.toml` (see the README).

### 5. Guard pull requests and take issues on GitHub

```bash
contexer init --ci        # replays approved checks on every pull request
contexer init --issues    # label an issue "contexer", reply /contexer approve
```

Commit the workflow files. For `--issues`, add `OPENROUTER_API_KEY` as a
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

Run the tests (about 8 minutes; real Chromium, Node and git, no network or
model):

```bash
python -m pytest -q -p no:cacheprovider --deselect tests/test_opencode_integration.py::test_live_opencode_e2e
```

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

To test with a real agent, put `OPENROUTER_API_KEY` in `contexer-agent/.env`
(git ignores it) and run `contexer run ... --agent opencode` on a copy of a
fixture app from `bench/fixtures/`. Check the free-request count with
`contexer doctor` first.

Where things live:

| Path | What |
| --- | --- |
| `src/contexer/cli/` | Commands; `term.py` is the terminal design every command uses |
| `src/contexer/controller/` | The run: implement, prove, repair, keep the best attempt |
| `src/contexer/verification/` | The check language and the Playwright runner |
| `src/contexer/github/` | Pull-request hand-off and the issue flow |
| `bench/fixtures/` | The seeded-bug benchmark apps |
| `../website/` | The landing page (`npm run dev`) |
| `../marketing/launch-video/` | The launch video (`npm run studio`) |
