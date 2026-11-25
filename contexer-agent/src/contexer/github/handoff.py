"""Hand a run's work over for review: a branch, one commit and a pull request.

The pull request's description carries the evidence: every check with its
verdict, the regression replay, the attempts and what they cost. A run whose
checks all passed opens a pull request ready for review; any other run with
changes opens a draft that says what still fails. A run that passed but whose
review found a high-severity security note is a draft too: the checks did
pass, and a person looks before it is merged.

For a run on the graph engine the description also carries what was
understood (the intent), each attempt with what was decided after it, and the
review's notes.

Everything that can be checked before the agent starts is checked by
:func:`plan_handoff`, so a run never spends its budget and then finds it
cannot hand anything over. The commit holds only the files the run changed
and the approved contract, never other work in the checkout.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from contexer.contract import Contract
from contexer.contract.store import AUTOMATIC_APPROVAL, CONTEXER_DIR, CONTRACTS_DIR
from contexer.crew.reviewer import holds_pull_request, prescan
from contexer.crew.triage import MOVE_LABELS
from contexer.github.api import GitHubClient, GitHubError, github_token, repo_of
from contexer.procutil import REPOSITORY_TOKENS

if TYPE_CHECKING:
    from contexer.controller.models import RunOutcome
    from contexer.intent.store import IntentSpec

PROJECT_URL = "https://github.com/murtuza777/contexer-agent"
_BOT = ("Contexer", "contexer@users.noreply.github.com")


class HandoffError(Exception):
    """The work cannot be handed over as a pull request."""


@dataclass
class HandoffPlan:
    project: Path
    root: Path  # the top of the git checkout; the project may be a folder inside it
    base: str  # the branch the work starts from
    remote: str | None
    repo: str | None  # owner/name on GitHub
    # The repository's settings and hooks as they were before any agent ran (see ``_git_state``).
    git_state: dict[str, str] = field(default_factory=dict)


@dataclass
class Handoff:
    branch: str
    commit: str
    pushed: bool
    url: str | None  # the pull request, or a link that opens one
    is_pull_request: bool
    draft: bool
    note: str = ""


def plan_handoff(project: str | Path) -> HandoffPlan:
    """Check the checkout can take a branch and a pull request, before any agent runs."""
    project = Path(project).resolve()
    top = _git(project, "rev-parse", "--show-toplevel")
    if top is None:
        raise HandoffError(f"{project} is not in a git repository; `git init` and commit it, or run without --pr")
    root = Path(top).resolve()
    if _git(root, "rev-parse", "--verify", "--quiet", "HEAD") is None:
        raise HandoffError("the repository has no commits yet; commit the project first, so the pull request has a base")
    base = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if base is None:
        raise HandoffError("HEAD is detached; check out the branch the pull request should target")
    status = _run_git(root, ("status", "--porcelain", "--untracked-files=no"), 30)  # unstripped: "XY path"
    dirty = [line[3:] for line in status.stdout.splitlines() if line.strip()] if status.returncode == 0 else []
    if dirty:
        listed = ", ".join(dirty[:3]) + (f" and {len(dirty) - 3} more" if len(dirty) > 3 else "")
        raise HandoffError(
            f"uncommitted changes in {listed}; commit or stash them first, so the pull request holds only this run's work"
        )
    remotes = (_git(root, "remote") or "").split()
    remote = "origin" if "origin" in remotes else (remotes[0] if remotes else None)
    repo = repo_of(root, remote) if remote else None
    return HandoffPlan(project=project, root=root, base=base, remote=remote, repo=repo, git_state=_git_state(root))


def hand_off(
    plan: HandoffPlan,
    outcome: RunOutcome,
    contract: Contract,
    *,
    issue: int | None = None,
    client_factory: Callable[[str, str], GitHubClient] | None = None,
) -> Handoff | None:
    """Commit the run's changes to a new branch, push it and open a pull request. None if nothing changed."""
    if not outcome.changed_files:
        return None
    if outcome.approved_hash and contract.content_hash() != outcome.approved_hash:
        # The run proved the checks it remembers. A contract file that now says something else was written
        # after they were approved, by something other than an approval: it is not committed as "approved".
        raise HandoffError(
            f"the contract {contract.id} changed after its checks were approved in this run, so nothing was committed. "
            f"Look at {CONTEXER_DIR}/{CONTRACTS_DIR}/{contract.id}.json, approve it again if the change is yours, and hand the work off yourself."
        )
    # The coding agent ran in this checkout with a shell. What it could have left for git to run is looked at before
    # git is asked to do anything: a changed setting stops the hand-off, a changed hook is not run.
    now = _git_state(plan.root)
    if plan.git_state and now.get(_CONFIG) != plan.git_state.get(_CONFIG):
        raise HandoffError(
            "the repository's git settings (.git/config) changed while the agent worked, so nothing was committed: a setting "
            "there can name a program for git to run. Look at the file, put it right, and hand the work off yourself."
        )
    hooks_changed = bool(plan.git_state) and {k: v for k, v in now.items() if k != _CONFIG} != {
        k: v for k, v in plan.git_state.items() if k != _CONFIG
    }
    quiet = _NO_HOOKS if hooks_changed or os.environ.get("GITHUB_ACTIONS") == "true" else ()
    prefix = plan.project.relative_to(plan.root)
    paths = [(prefix / p).as_posix() for p in outcome.changed_files]
    contract_file = (prefix / CONTEXER_DIR / CONTRACTS_DIR / f"{contract.id}.json").as_posix()
    note = "The repository's git hooks changed during the run, so they were not run for this commit or this push. " if hooks_changed else ""
    if (plan.root / contract_file).is_file():
        if _git(plan.root, "check-ignore", "--quiet", contract_file) is None:
            paths.append(contract_file)
        else:
            note = f"{contract_file} is ignored by git, so the contract is not in the pull request. "

    branch = _free_branch(plan, f"contexer/{contract.id}")
    _git_or_fail(plan.root, *quiet, "switch", "--quiet", "-c", branch)
    _git_or_fail(plan.root, *quiet, "add", "--all", "--", *paths)
    # What is scanned is what is staged, all of it. The diff a run keeps is cut to size, and a lockfile alone can fill it.
    staged = _git(plan.root, "diff", "--cached", "--no-ext-diff", "--no-textconv", "--no-color", "--", *paths, timeout=120)
    automatic = contract.approval is not None and contract.approval.by == AUTOMATIC_APPROVAL
    held = holds_pull_request(outcome.review) or automatic
    succeeded = outcome.terminal == "succeeded" and not held
    if held and outcome.terminal == "succeeded":
        note += (
            "Opened as a draft: the checks were approved with --yes and nobody read them. "
            if automatic and not holds_pull_request(outcome.review)
            else "Opened as a draft: the review has a high-severity note. "
        )
    try:
        _git_or_fail(plan.root, *quiet, *_identity(plan.root), "commit", "--quiet", "-m", _commit_message(outcome, contract))
    except HandoffError as exc:  # a pre-commit hook, usually
        raise HandoffError(f"{exc}\nThe changes are staged on branch {branch}; commit and push them yourself.") from exc
    commit = _git(plan.root, "rev-parse", "HEAD") or ""

    if plan.remote is None:
        return Handoff(branch, commit, False, None, False, not succeeded, note + "The repository has no remote to push to.")
    # A draft is still a push. Whatever the outcome, a change that adds a secret stays on this machine.
    if staged is None:
        return Handoff(
            branch, commit, False, None, False, True,
            note + f"Not pushed: the change could not be read back to scan it for secrets. The work is committed on the local "
            f"branch {branch}; look it over and push it yourself.",
        )  # fmt: skip
    leaked = [n for n in prescan(staged) if n.category == "security" and n.severity == "high"]
    if leaked:
        where = ", ".join(f"{_in_project(n.file, prefix)}:{n.line}" if n.line else _in_project(n.file, prefix) for n in leaked[:3])
        return Handoff(
            branch, commit, False, None, False, True,
            note + f"Not pushed: the change adds what looks like a secret ({where}). The work is committed on the local "
            f"branch {branch}. Remove the secret (and revoke it if it is real), amend the commit, then push it yourself.",
        )  # fmt: skip
    pushed = _git(plan.root, *quiet, *_push_auth(plan), "push", "--quiet", "--set-upstream", plan.remote, branch, timeout=180, tokens=True)
    if pushed is None:
        return Handoff(
            branch, commit, False, None, False, not succeeded,
            note + f"`git push {plan.remote} {branch}` failed; push the branch yourself.",
        )
    if plan.repo is None:
        return Handoff(branch, commit, True, None, False, not succeeded, note + f"Pushed to {plan.remote}; open a merge request there.")

    compare = f"https://github.com/{plan.repo}/compare/{plan.base}...{branch}?expand=1"
    token = github_token()
    if token is None:
        return Handoff(branch, commit, True, compare, False, not succeeded, note + "No GitHub token (GITHUB_TOKEN or `gh auth login`); open the pull request from the link.")
    factory = client_factory or (lambda repo, tok: GitHubClient(repo, tok))
    client = factory(plan.repo, token)
    try:
        pull = client.open_pull(
            title=_title(outcome, contract),
            head=branch,
            base=plan.base,
            body=pull_request_body(outcome, contract, issue=issue, intent=_intent(plan.project, outcome)),
            draft=not succeeded,
        )
    except GitHubError as exc:
        return Handoff(branch, commit, True, compare, False, not succeeded, note + f"Opening the pull request failed: {exc}")
    finally:
        client.close()
    return Handoff(branch, commit, True, str(pull.get("html_url") or compare), True, bool(pull.get("draft", not succeeded)), note)


# -- the pull request ---------------------------------------------------------------------


def _intent(project: Path, outcome: RunOutcome) -> IntentSpec | None:
    """The intent the run wrote, when it wrote one (graph engine, from a goal)."""
    if not outcome.intent_id:
        return None
    from contexer.intent.store import IntentStore

    store = IntentStore(project)
    try:
        return store.load(outcome.intent_id) if store.exists(outcome.intent_id) else None
    except Exception:  # the evidence matters more than one section of it
        return None


def pull_request_body(
    outcome: RunOutcome, contract: Contract, *, issue: int | None = None, intent: IntentSpec | None = None
) -> str:
    final = outcome.final
    decision = final.decision if final is not None else None
    lines: list[str] = []
    if outcome.terminal == "succeeded" and decision is not None:
        lines.append(f"✅ **All {decision.verified} checks proven in a real browser.**")
        if holds_pull_request(outcome.review):
            lines += [
                "",
                "⚠️ **Opened as a draft:** reading the diff found a high-severity note (see Review below). "
                "The checks passed; a person should look at it before this is merged.",
            ]
    else:
        lines.append(f"⚠️ **Not done yet:** {_inert(outcome.reason)}")
    if contract.approval is not None and contract.approval.by == AUTOMATIC_APPROVAL:
        lines += [
            "",
            "⚠️ **The checks were approved automatically (`--yes`).** Nobody read them before the work was built "
            "against them. Read the definition of done below as carefully as the code: a check can pass for the wrong reason.",
        ]
    lines += ["", "### Goal", "", _quote(contract.goal), ""]
    if intent is not None and (intent.behaviours or intent.assumptions or intent.corrections):
        lines += ["### What was understood", ""]
        lines += [f"- {_md(line)}" for line in intent.behaviours]
        if intent.corrections:
            lines += ["", "Corrections from the person:", "", *[f"- {_md(c.text)}" for c in intent.corrections]]
        if intent.assumptions:
            lines += ["", "Assumed without asking:", "", *[f"- {_md(line)}" for line in intent.assumptions]]
        lines.append("")

    for result in final.contracts if final is not None else []:
        target = result.contract.id == contract.id
        rows = result.verification.criteria_results if result.verification else []
        if target:
            lines += ["### Definition of done", "", "| | Check | Evidence |", "|---|---|---|"]
            for r in rows:
                mark = {"verified": "✅", "refuted": "❌", "unverified": "❔"}[r.verdict]
                how = "" if r.proven else (" *(LLM-judged)*" if r.method == "judgment" else " *(heuristic)*")
                lines.append(f"| {mark} | {_md(r.description)}{how} | {_md(r.evidence)[:200]} |")
            lines.append("")
    others = [r for r in (final.contracts if final is not None else []) if r.contract.id != contract.id]
    if others:
        held = sum(1 for r in others for c in (r.verification.criteria_results if r.verification else []) if c.verdict == "verified")
        total = sum(len(r.verification.criteria_results) if r.verification else 0 for r in others)
        lines += [
            "### Regression replay",
            "",
            f"{held} of {total} checks from {len(others)} earlier approved contract(s) still pass.",
            "",
        ]

    lines += _attempt_lines(outcome)
    lines += _review_lines(outcome)

    attempts = len(outcome.attempts)
    repairs = max(attempts - 1, 0)
    cost = f" · ${outcome.cost_usd:.2f}" if outcome.cost_usd else ""
    lines += [
        "### How it got here",
        "",
        f"- **Agent:** {outcome.agent} · {attempts} attempt(s), {repairs} repair round(s){cost} · "
        f"{_duration(outcome.duration_seconds)}",
    ]
    if contract.approval is not None:
        lines.append(
            f"- **Contract:** `{CONTEXER_DIR}/{CONTRACTS_DIR}/{contract.id}.json`, approved by "
            f"{contract.approval.by} (sha256 `{contract.approval.sha256[:12]}`)"
        )
    lines.append(f"- **Evidence:** {_evidence_link(outcome)}")
    lines.append("")
    if issue is not None:
        lines += [f"Closes #{issue}", ""]
    lines += [
        "---",
        f"Opened by [Contexer]({PROJECT_URL}). The agent's own report never counts: every check above ran "
        "in Chromium against the app as changed here, and the contract's checks replay on later pull requests.",
    ]
    return "\n".join(lines) + "\n"


def _attempt_lines(outcome: RunOutcome) -> list[str]:
    """Each attempt and what was decided after it. Only when there was more than one, or a decision to show."""
    if len(outcome.attempts) < 2 and not outcome.triage:
        return []
    decided = {d.attempt: d for d in outcome.triage}
    lines = ["### Attempts", "", "| # | Result | What was decided next |", "|---|---|---|"]
    for attempt in outcome.attempts:
        result = f"{attempt.outcome}: {attempt.verified} proven, {attempt.refuted} failed, {attempt.unverified} not run"
        decision = decided.get(attempt.n)
        if decision is not None:
            who = "a model" if decision.source == "model" else "the rules"
            after = f"{MOVE_LABELS.get(decision.move, decision.move).capitalize()} ({who}): {_md(decision.reason)[:300]}"
        else:
            after = _md(attempt.note)[:300] if attempt.note else ""
        lines.append(f"| {attempt.n} | {_md(result)} | {after} |")
    return [*lines, ""]


def _review_lines(outcome: RunOutcome) -> list[str]:
    if not outcome.review:
        return []
    lines = [
        "### Review",
        "",
        "What reading the diff found after the checks passed. A note does not change the verdict: the checks "
        "decide that. \"A program\" means code saw it in the diff or ran a command; \"a model\" is advice.",
        "",
        "| Severity | About | Where | Found by | Note |",
        "|---|---|---|---|---|",
    ]
    for note in outcome.review:
        where = f"`{note.file}:{note.line}`" if note.file and note.line else (f"`{note.file}`" if note.file else "")
        by = "a program" if note.backed else "a model"
        lines.append(f"| {note.severity} | {note.category} | {where} | {by} | {_md(note.explanation)[:400]} |")
    return [*lines, ""]


def _title(outcome: RunOutcome, contract: Contract) -> str:
    title = contract.goal.strip().splitlines()[0].strip() if contract.goal.strip() else contract.id
    return _shorten(title, 100)


def _shorten(text: str, limit: int) -> str:
    """Cut at a word boundary, so a subject never ends mid-word."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{cut}…"


def _commit_message(outcome: RunOutcome, contract: Contract) -> str:
    subject = _shorten(_title(outcome, contract), 72)
    decision = outcome.final.decision if outcome.final is not None else None
    if outcome.terminal == "succeeded" and decision is not None:
        proof = f"Contexer proved all {decision.verified} checks in Chromium"
    else:
        proof = f"Contexer: not done yet — {outcome.reason}"
    return f"{subject}\n\n{proof} (contract {contract.id}, run {outcome.run_id}).\n"


def _evidence_link(outcome: RunOutcome) -> str:
    run_id = os.environ.get("GITHUB_RUN_ID")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if run_id and repo:
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
        return f"screenshots and expected-vs-actual in the `contexer-report` artifact of [this workflow run]({server}/{repo}/actions/runs/{run_id})"
    return f"`report.html` in `{CONTEXER_DIR}/runs/{outcome.run_id}/` on the machine that ran it"


def _quote(text: str) -> str:
    return "\n".join(f"> {_inert(line)}" if line.strip() else ">" for line in text.strip()[:3000].splitlines())


def _md(text: str) -> str:
    return _inert(" ".join(str(text).split())).replace("|", "\\|")


_MENTION = re.compile(r"@(?=[A-Za-z0-9])")
_ISSUE_REF = re.compile(r"#(?=\d)")


def _inert(text: str) -> str:
    """Text from the app, an issue or a model, so that GitHub shows it and does nothing with it.

    No mention notifies anyone, no ``#12`` links or closes an issue, and no link or image is live. The only
    issue reference a pull request body acts on is the ``Closes #N`` Contexer writes itself.
    """
    text = _MENTION.sub("@\u200b", _ISSUE_REF.sub("#\u200b", text))
    return text.replace("](", "]\u200b(").replace("![", "!\u200b[").replace("<", "&lt;")


def _duration(seconds: float) -> str:
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


# -- git ----------------------------------------------------------------------------------


def _free_branch(plan: HandoffPlan, wanted: str) -> str:
    candidate, n = wanted, 2
    while _branch_taken(plan, candidate):
        candidate, n = f"{wanted}-{n}", n + 1
    return candidate


def _branch_taken(plan: HandoffPlan, branch: str) -> bool:
    if _git(plan.root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}") is not None:
        return True
    if plan.remote is None:
        return False
    return bool(_git(plan.root, *_NO_HOOKS, *_push_auth(plan), "ls-remote", "--heads", plan.remote, branch, timeout=60, tokens=True))


def _push_auth(plan: HandoffPlan) -> list[str]:
    """In Actions, push with the token directly.

    The issue workflow checks out without persisted credentials, so the coding agent finds no token in
    .git/config; only this push uses one.
    """
    token = github_token() if os.environ.get("GITHUB_ACTIONS") == "true" and plan.repo else None
    if token is None:
        return []
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    return ["-c", f"http.{server}/.extraheader=AUTHORIZATION: basic {basic}"]


def _identity(root: Path) -> list[str]:
    """A commit identity for checkouts that have none, such as a fresh CI runner."""
    if _git(root, "config", "user.email"):
        return []
    return ["-c", f"user.name={_BOT[0]}", "-c", f"user.email={_BOT[1]}"]


def _git(cwd: Path, *args: str, timeout: float = 30, tokens: bool = False) -> str | None:
    try:
        out = _run_git(cwd, args, timeout, tokens=tokens)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _git_or_fail(cwd: Path, *args: str) -> str:
    try:
        out = _run_git(cwd, args, 120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HandoffError(f"git {args[0]} failed: {exc}") from exc
    if out.returncode != 0:
        verb = next((a for a in args if not a.startswith("-") and "=" not in a), args[0])
        raise HandoffError(f"git {verb} failed: {(out.stderr or out.stdout).strip()[-600:]}")
    return out.stdout.strip()


def _in_project(path: str, prefix: Path) -> str:
    """A path from the repository's root as the person knows it: from the project's folder."""
    lead = prefix.as_posix()
    return path[len(lead) + 1 :] if lead not in ("", ".") and path.startswith(lead + "/") else path


_CONFIG = ".git/config"
# No hook of the repository is run, whatever its settings say where they are.
_NO_HOOKS = ("-c", f"core.hooksPath={os.devnull}")


def _git_state(root: Path) -> dict[str, str]:
    """A digest of the repository's own settings and of each of its hooks.

    Taken before any agent runs and again before the hand-off. The hooks are looked for where git itself
    looks (``core.hooksPath`` can point into the project, as husky does), and a sample that git ships is
    not a hook.
    """
    state: dict[str, str] = {}
    for name, args in ((_CONFIG, ("rev-parse", "--git-path", "config")), ("hooks", ("rev-parse", "--git-path", "hooks"))):
        found = _git(root, *args)
        if not found:
            continue
        path = (root / found).resolve()
        files = [path] if name == _CONFIG else (sorted(p for p in path.iterdir() if p.is_file() and p.suffix != ".sample") if path.is_dir() else [])
        for file in files:
            try:
                digest = hashlib.sha256(file.read_bytes()).hexdigest()
            except OSError:
                digest = "unreadable"
            state[name if name == _CONFIG else f"hooks/{file.name}"] = digest
    return state


def _run_git(cwd: Path, args: tuple[str, ...], timeout: float, *, tokens: bool = False) -> subprocess.CompletedProcess[str]:
    """Run git in the person's checkout.

    Without ``tokens`` (everything but a push) the environment has no repository token: a hook that
    runs on a commit is the project's code. The file-system monitor setting names a program too, and is
    never used.
    """
    env = {k: v for k, v in os.environ.items() if tokens or k not in REPOSITORY_TOKENS}
    env["GIT_TERMINAL_PROMPT"] = "0"  # never wait on a password prompt nobody sees
    return subprocess.run(
        ["git", "-c", "core.fsmonitor=false", *args],
        cwd=str(cwd), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )  # fmt: skip
