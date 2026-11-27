# Launch brief, 2026-11-20

Where Contexer stands against what exists, what its users still need, and
how to release it. The outside facts here come from web searches read
through result summaries, not from the primary pages. Prices and features
of other products change and several were taken from third-party pages:
check each against its source before repeating it in public.

---

## 1. Who else is here

Every major coding agent now opens a browser and checks its own work:
Claude Code (Chrome, Playwright MCP, a preview browser), Cursor (browser
tool, Bugbot), Codex, Google Antigravity, Devin, Replit Agent, GitHub
Copilot's coding agent. "It opens a browser" is no longer a reason to
choose anything.

| Closest | What it does | How Contexer differs |
| --- | --- | --- |
| Ranger Feature Review | A CLI the coding agent calls; a browser agent walks scenarios and returns a verdict; evidence goes to a hosted dashboard. Closed, paid per user | The verdict is a model's; the evidence leaves the machine; the coding agent drives the loop |
| Devin | A cloud agent that tests its own pull request and returns a recording | It is the agent, and it grades itself |
| GitHub Copilot coding agent | Assign an issue; it codes, runs the app through Playwright, puts screenshots in the pull request | No checks approved before the build |
| Cursor (browser tool, Bugbot) | The agent tests and screenshots; a second product reviews pull requests | Bound to the editor; self-graded |
| CodeRabbit, Greptile | Review of pull requests by a model | The review step only |
| TestSprite | Generates and runs tests for AI-written code, as a cloud service | Does not drive the build, the repair or the pull request |

What none of the tools looked at combines:

1. A person approves the checks before anything is built.
2. Pass or fail is decided by code replaying those checks, not by a model.
3. Any coding agent, the user's own key, on the user's machine, no account.

That is the position. The review of the diff, the rollback and the budget
are useful and easy to copy; they are not it.

**The threat** is that self-verification inside every agent makes an
outside harness look optional. The answer is in what users still report in
late 2026: agents that say done when they are not, tests bent to pass,
"it grades its own homework". An agent checking itself does not end that.

---

## 2. What users of coding agents ask for

From issue trackers, forums and blog posts of 2025 and 2026.

| Want | Contexer today |
| --- | --- |
| The agent says done when it is not | The reason Contexer exists |
| Tests pass and prove nothing; tests deleted or loosened | Replayed checks; the scan for skipped, focused, deleted and loosened tests |
| Fixing one thing breaks another | Earlier approved contracts are replayed on every run |
| Verify without clicking through by hand | `contexer run`, `contexer test` |
| Cost and loops when left alone overnight | One budget for the run, round limits, a stop at the best attempt |
| Rules in prompts get ignored; enforce them in code | The tamper guard, the gate, the legal moves |
| Proof attached to the work | The pull request body and `report.html`; **no screenshot or video in the pull request itself** |
| Start work from an issue tracker | GitHub issues only, in Actions, not yet run against a real issue |
| Review is the bottleneck with several agents at once | **One run per project** |
| Steer or queue from a phone | **Nothing** |
| Verify what is not a web page | **Nothing**: browser only |

The three gaps that matter most before a launch:

1. **Use it from inside the coding agent.** People live in Claude Code or
   Codex. A plugin or skill that lets the agent call `contexer verify` and
   be told what failed puts Contexer where they already are. The closest
   competitor distributes this way.
2. **Evidence a reviewer can see without the machine.** Screenshots of each
   check, or a trace, in the pull request, and a `--json` event stream so
   CI and other tools can read a run.
3. **A first run that cannot go wrong**, above all on Windows: one command
   to install, Chromium fetched, a model key asked for once, and a sample
   app that passes in five minutes.

Since this was written: the first gap is built (`contexer mcp`, the stop
hook and `contexer init --agent`, in version 0.6.0; run in Claude Code only
so far), and so is the second (`--json` events, and in version 0.7.0
`trace.jsonl` and screenshots in the pull request with `--pr --screenshots`;
a trace is never pushed).

---

## 3. The terminal

Today the output is a column of lines printed as things happen, with a
spinner. That reads like a log. What people praise in the agent CLIs is
not decoration; it is knowing at a glance what is happening and what it
has cost:

- one status line that stays put: the step, the time, the spend;
- the plan as a short list that ticks off in place;
- tool output collapsed to a line unless it failed;
- a summary at the end that fits on one screen;
- the same run readable as plain lines in CI and as JSON for tools.

Contexer supervises a run and asks few questions. It is not a chat. So:

1. Keep the output in the terminal's scrollback (Rich), and redesign it as
   one live panel: the checks as a list with their state, the attempt, the
   agent's current action on one line, and time and cost in a footer.
2. Add `--json`: one event per line. Everything else is built on it.
3. Later, an optional full-screen view (`contexer watch`, Textual) reading
   the same events.

Full-screen by default would take away the scrollback and add a second
thing to keep working on Windows.

---

## 4. Open or closed source

**Open the command-line tool, under Apache-2.0. Keep the name, and any
hosted team product, proprietary.**

Why:

- Contexer runs agents with access to a repository and its tokens. With no
  brand behind it, source a person can read is the cheapest trust there is.
- With no users, being unknown is a larger risk than being copied.
- The tools that people install locally in this area are open (Cline,
  Aider, OpenHands, spec-kit). The ones that are closed sell a hosted
  service with accounts, which Contexer does not have.

What it costs:

- Open source is distribution, not income. Aider has users and no paid
  product; Vibe Kanban was open and its company closed.
- The idea is easy to copy. A licence such as FSL would stop a hosted
  clone, at the price of not being open source in the sense people expect.
- Support falls on one person.

Where money could come from later, the usual split: the local tool is
free; a team pays for shared run history and a dashboard, a GitHub App
that runs the gate and the issue flow without setup, organisation policy,
single sign-on.

What closed source would need to be believed: signed installers for three
systems, security documentation, a hosted service with a pricing page,
support, and an audit such as SOC 2 once selling to companies. That is
months of work that is not the product, before the first user.

---

## 5. Before the first hundred users

Must exist on the first day:

- One line to install (`uv tool install contexer-agent`), tried on a clean
  Windows, macOS and Linux machine, including the browser download.
- A sixty-second recording of a real run: a check fails, the cause is
  found, the repair passes, the pull request opens.
- A quickstart that reaches a first result in five minutes on a sample app.
- A page that says what it does and does not do: web apps only, never
  writes code, what is sent to which model provider, no telemetry.
- The licence, a security policy, issue templates.
- What a run costs, with a real example.

Still to do in the product:

- The three gaps in section 2.
- macOS and Codex, run for real.
- The issue flow, run against a real issue.
- The release: the tag, and the upload to PyPI as `contexer-agent`.

Where to announce it first: Show HN with the recording, and the Claude
Code communities the same week, since that is where the complaints it
answers are posted.

What to watch: installs that reach a first completed run, the time to a
first passing check, runs that end in a pull request, people who come back
in the second week, failures by operating system, issues opened by
strangers. Stars say little.
