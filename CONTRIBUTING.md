# Contributing to Contexer

Thanks for helping. This page covers setup, how work is tracked, and what a
pull request needs.

## Set up

```bash
git clone https://github.com/murtuza777/contexer-agent.git
cd contexer-agent/contexer-agent
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
python -m playwright install chromium
```

You need Python 3.11 or newer, Node 22 and git. No model key is needed to run
the tests.

## Run the checks

```bash
python -m ruff check src tests
python -m pyright src
python -m pytest -q -p no:cacheprovider --deselect tests/test_opencode_integration.py::test_live_opencode_e2e
contexer bench --repeats 2
```

The tests take about half an hour on one process and about 11 minutes with
`-n auto` (pytest-xdist, in the `dev` extra): they drive real Chromium, real
Node process trees and real git. CI runs both commands on Linux for every push and pull
request.

## How work is tracked

- The plan is in [docs/agentic](contexer-agent/docs/agentic/architecture.md),
  one file per phase.
- Every ticket in those files is a GitHub issue, grouped by a milestone per
  phase. A ticket states its goal, scope, acceptance checks and how it is
  verified.
- Pick an issue, comment that you are taking it, and keep the pull request to
  that one ticket.
- Found a bug or have an idea that is not a ticket? Open an issue with the
  matching template first.

## Rules for the code

These are what keeps Contexer trustworthy. A pull request that breaks one will
not be merged.

1. **Only a check that ran counts as proof.** No model output may be labelled
   `proven`, and no agent may decide that a run succeeded.
2. **Agents never write application code.** Only the external coding agent
   edits the user's project.
3. **Never leave a project worse than it was found.** Anything that changes
   files takes a snapshot first and can restore it.
4. **No secret in a prompt, a log, a transcript or a commit.**
5. **Tests need no network and no model.** Use the scripted agent and recorded
   model replies. Live tests skip themselves when a key is missing.
6. **Measure before claiming.** A change that affects accuracy comes with
   benchmark numbers, whatever they are.
7. **Assume the model is compromised.** A guardrail is a property of the
   code, with a test in which a scripted model does what an attacker wants.
   An instruction in a prompt is not a guardrail. A new tool for an agent
   goes into the tool audit in `docs/architecture.md`.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org):

```text
feat(tester): record every browser action as a check step
fix(appserver): kill the whole process tree on timeout
docs(agentic): add the project-skills ticket
```

Types in use: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`. Add
`!` for a breaking change. One logical change per commit; the body says why.

## Pull requests

- Branch from `main`: `feat/<ticket>-short-name`, for example
  `feat/t1.1-browser-tools`.
- Link the issue (`Closes #12`).
- Tests for new behaviour; the full suite green.
- Update the docs the change touches, and `CHANGELOG.md` under "Unreleased".
- Fill in the pull request template, including how you verified the change.

## Reporting security problems

Do not open a public issue. See [SECURITY.md](SECURITY.md).

## Licence

By contributing you agree that your work is released under the
[MIT licence](LICENSE).
