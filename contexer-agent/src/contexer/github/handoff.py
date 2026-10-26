"""Hand a run's work over for review: a branch, one commit and a pull request.

The pull request's description carries the evidence: every check with its
verdict, the regression replay, the attempts and what they cost. A run whose
checks all passed opens a pull request ready for review; any other run with
changes opens a draft that says what still fails.

Everything that can be checked before the agent starts is checked by
:func:`plan_handoff`, so a run never spends its budget and then finds it
cannot hand anything over. The commit holds only the files the run changed
and the approved contract, never other work in the checkout.
"""

from __future__ import annotations

import base64
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from contexer.contract import Contract
from contexer.contract.store import CONTEXER_DIR, CONTRACTS_DIR
from contexer.github.api import GitHubClient, GitHubError, github_token, repo_of

if TYPE_CHECKING:
    from contexer.controller.run import RunOutcome

PROJECT_URL = "https://github.com/murtuza777/contexer-agent"
_BOT = ("Contexer", "contexer@users.noreply.github.com")


class HandoffError(Exception):
    """The work cannot be handed over as a pull request."""


@dataclass
class HandoffPlan:
    project: Path
    root: Path  # the top of the git checkout; the project may be a folder inside it
    base: str  # the branch the work starts from
    remote: Optional[str]
    repo: Optional[str]  # owner/name on GitHub


@dataclass
class Handoff:
    branch: str
    commit: str
    pushed: bool
    url: Optional[str]  # the pull request, or a link that opens one
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
    return HandoffPlan(project=project, root=root, base=base, remote=remote, repo=repo)


def hand_off(
    plan: HandoffPlan,
    outcome: "RunOutcome",
    contract: Contract,
    *,
    issue: Optional[int] = None,
    client_factory: Optional[Callable[[str, str], GitHubClient]] = None,
) -> Optional[Handoff]:
    """Commit the run's changes to a new branch, push it and open a pull request. None if nothing changed."""
    if not outcome.changed_files:
        return None
    prefix = plan.project.relative_to(plan.root)
    paths = [(prefix / p).as_posix() for p in outcome.changed_files]
    contract_file = (prefix / CONTEXER_DIR / CONTRACTS_DIR / f"{contract.id}.json").as_posix()
    note = ""
    if (plan.root / contract_file).is_file():
        if _git(plan.root, "check-ignore", "--quiet", contract_file) is None:
            paths.append(contract_file)
        else:
            note = f"{contract_file} is ignored by git, so the contract is not in the pull request. "

    branch = _free_branch(plan, f"contexer/{contract.id}")
    _git_or_fail(plan.root, "switch", "--quiet", "-c", branch)
    _git_or_fail(plan.root, "add", "--all", "--", *paths)
    succeeded = outcome.terminal == "succeeded"
    try:
        _git_or_fail(plan.root, *_identity(plan.root), "commit", "--quiet", "-m", _commit_message(outcome, contract))
    except HandoffError as exc:  # a pre-commit hook, usually
        raise HandoffError(f"{exc}\nThe changes are staged on branch {branch}; commit and push them yourself.") from exc
    commit = _git(plan.root, "rev-parse", "HEAD") or ""

    if plan.remote is None:
        return Handoff(branch, commit, False, None, False, not succeeded, note + "The repository has no remote to push to.")
    pushed = _git(plan.root, *_push_auth(plan), "push", "--quiet", "--set-upstream", plan.remote, branch, timeout=180)
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
            body=pull_request_body(outcome, contract, issue=issue),
            draft=not succeeded,
        )
    except GitHubError as exc:
        return Handoff(branch, commit, True, compare, False, not succeeded, note + f"Opening the pull request failed: {exc}")
    finally:
        client.close()
    return Handoff(branch, commit, True, str(pull.get("html_url") or compare), True, bool(pull.get("draft", not succeeded)), note)


# -- the pull request ---------------------------------------------------------------------


def pull_request_body(outcome: "RunOutcome", contract: Contract, *, issue: Optional[int] = None) -> str:
    final = outcome.final
    decision = final.decision if final is not None else None
    lines: list[str] = []
    if outcome.terminal == "succeeded" and decision is not None:
        lines.append(f"✅ **All {decision.verified} checks proven in a real browser.**")
    else:
        lines.append(f"⚠️ **Not done yet:** {outcome.reason}")
    lines += ["", "### Goal", "", _quote(contract.goal), ""]

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


def _title(outcome: "RunOutcome", contract: Contract) -> str:
    title = contract.goal.strip().splitlines()[0].strip() if contract.goal.strip() else contract.id
    return title if len(title) <= 100 else title[:97] + "..."


def _commit_message(outcome: "RunOutcome", contract: Contract) -> str:
    subject = _title(outcome, contract)
    subject = subject if len(subject) <= 72 else subject[:69] + "..."
    decision = outcome.final.decision if outcome.final is not None else None
    if outcome.terminal == "succeeded" and decision is not None:
        proof = f"Contexer proved all {decision.verified} checks in Chromium"
    else:
        proof = f"Contexer: not done yet — {outcome.reason}"
    return f"{subject}\n\n{proof} (contract {contract.id}, run {outcome.run_id}).\n"


def _evidence_link(outcome: "RunOutcome") -> str:
    run_id = os.environ.get("GITHUB_RUN_ID")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if run_id and repo:
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
        return f"screenshots and expected-vs-actual in the `contexer-report` artifact of [this workflow run]({server}/{repo}/actions/runs/{run_id})"
    return f"`report.html` in `{CONTEXER_DIR}/runs/{outcome.run_id}/` on the machine that ran it"


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" if line.strip() else ">" for line in text.strip()[:3000].splitlines())


def _md(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


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
    return bool(_git(plan.root, *_push_auth(plan), "ls-remote", "--heads", plan.remote, branch, timeout=60))


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


def _git(cwd: Path, *args: str, timeout: float = 30) -> Optional[str]:
    try:
        out = _run_git(cwd, args, timeout)
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


def _run_git(cwd: Path, args: tuple[str, ...], timeout: float) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")  # never wait on a password prompt nobody sees
    return subprocess.run(
        ["git", *args], cwd=str(cwd), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
    )
