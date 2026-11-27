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

Text that comes from an issue, the app, a model or git is written so that
GitHub shows it and does nothing with it (``_plain``, ``_inert``, ``_code``).
Screenshots are pushed and shown only when asked for (``_push_screenshots``).

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
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from contexer.contract import Contract
from contexer.contract.store import AUTOMATIC_APPROVAL, CONTEXER_DIR, CONTRACTS_DIR
from contexer.crew.reviewer import holds_pull_request, prescan
from contexer.crew.triage import MOVE_LABELS
from contexer.evidence.screenshots import CheckScreenshot, check_screenshots
from contexer.github.api import GitHubClient, GitHubError, github_token, repo_of
from contexer.procutil import REPOSITORY_TOKENS

if TYPE_CHECKING:
    from contexer.controller.models import RunOutcome
    from contexer.intent.store import IntentSpec

PROJECT_URL = "https://github.com/murtuza777/contexer-agent"
_BOT = ("Contexer", "contexer@users.noreply.github.com")


class HandoffError(Exception):
    """The work cannot be handed over as a pull request.

    Its text can hold file names an agent chose and what git printed, and it is posted in an issue
    comment, so it is made plain (see ``_plain``).
    """

    def __init__(self, message: str) -> None:
        super().__init__(_plain(message))


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

    def __post_init__(self) -> None:
        self.note = _plain(self.note)  # it names files an agent chose, and is posted in an issue comment


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
    screenshots: bool = False,
) -> Handoff | None:
    """Commit the run's changes to a new branch, push it and open a pull request. None if nothing changed.

    With ``screenshots``, one screenshot per check is pushed to a branch of its own and shown in the pull
    request. It is asked for, never the default: they show the app's data to whoever can read the repository.
    """
    if not outcome.changed_files:
        return None
    now = _unchanged_or_fail(plan, outcome, contract)
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
    flaky = flaky_checks(outcome)
    held = holds_pull_request(outcome.review) or automatic or bool(flaky)
    succeeded = outcome.terminal == "succeeded" and not held
    if held and outcome.terminal == "succeeded":
        if holds_pull_request(outcome.review):
            note += "Opened as a draft: the review has a high-severity note. "
        elif automatic:
            note += "Opened as a draft: the checks were approved with --yes and nobody read them. "
        if flaky:
            note += (
                f"Opened as a draft: {', '.join(flaky)} failed on the first replay and passed on the second (flaky). "
                "An intermittent bug looks the same. "
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
    # Only here: the change passed the secret scan and is on the remote, and a pull request can show them.
    shown: Screenshots | None = None
    if screenshots:
        shots = check_screenshots(outcome.final, contract.id, outcome.run_dir)
        pushed_to = f"contexer-evidence/{contract.id}-{commit[:8]}"
        if not shots:
            note += "No screenshots were pushed: the run kept none in its folder. "
        elif _push_screenshots(plan, shots, pushed_to, contract.id):
            shown = Screenshots(plan.repo, pushed_to, shots)
        else:
            note += f"The screenshots could not be pushed to {plan.remote}, so the pull request has none. "
    factory = client_factory or (lambda repo, tok: GitHubClient(repo, tok))
    client = factory(plan.repo, token)
    try:
        pull = client.open_pull(
            title=_title(outcome, contract),
            head=branch,
            base=plan.base,
            body=pull_request_body(outcome, contract, issue=issue, intent=_intent(plan.project, outcome), screenshots=shown),
            draft=not succeeded,
        )
    except GitHubError as exc:
        left = f" The screenshots are on the branch {shown.branch} of {plan.remote}; delete it if they should not stay there." if shown else ""
        return Handoff(branch, commit, True, compare, False, not succeeded, note + f"Opening the pull request failed: {exc}{left}")
    finally:
        client.close()
    return Handoff(branch, commit, True, str(pull.get("html_url") or compare), True, bool(pull.get("draft", not succeeded)), note)


def _unchanged_or_fail(plan: HandoffPlan, outcome: RunOutcome, contract: Contract) -> dict[str, str]:
    """Stop when the contract or the repository's git settings changed during the run. The git state as it is now."""
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
    return now


# -- a build with no write token: the change leaves as a patch, another job pushes it -----------------

# A patch larger than this is not published. A lockfile is well under it; a change this large is read by nobody.
MAX_PATCH_BYTES = 5_000_000
# What a published change may hold: files, and files that can be run. A deletion has no mode. Not a
# symbolic link (120000) and not a submodule (160000): each makes a path mean something other than its content.
_FILE_MODES = frozenset({"100644", "100755", "000000"})
# The index refuses the names Windows and macOS read as ``.git``, whatever system applies the patch.
_STRICT_NAMES = ("-c", "core.protectNTFS=true", "-c", "core.protectHFS=true")


def make_patch(plan: HandoffPlan, outcome: RunOutcome, contract: Contract) -> bytes | None:
    """The run's change as a patch: the files the run changed and the approved contract. None if nothing changed.

    For a job that holds no token to push with (the issue workflow's first job). The checkout's own index and
    branch are left as they are: the files are staged in an index of their own.
    """
    if not outcome.changed_files:
        return None
    _unchanged_or_fail(plan, outcome, contract)
    prefix = plan.project.relative_to(plan.root)
    paths = [(prefix / p).as_posix() for p in outcome.changed_files]
    contract_file = (prefix / CONTEXER_DIR / CONTRACTS_DIR / f"{contract.id}.json").as_posix()
    if (plan.root / contract_file).is_file() and _git(plan.root, "check-ignore", "--quiet", contract_file) is None:
        paths.append(contract_file)
    with tempfile.TemporaryDirectory() as scratch:
        index = Path(scratch) / "index"
        _raw_or_fail(plan.root, "read-tree", "HEAD", index=index)
        _raw_or_fail(plan.root, "add", "--all", "--", *paths, index=index)
        patch = _raw_or_fail(
            plan.root, "diff", "--cached", "--binary", "--full-index", "--no-renames", "--no-ext-diff", "--no-textconv",
            "--no-color", "HEAD", "--", *paths, index=index,
        )  # fmt: skip
    return patch or None


def patch_problems(entries: list[tuple[str, str]], contract_file: str) -> list[str]:
    """Why a change may not be published, one sentence per entry at fault. ``entries`` are (new mode, path).

    Nothing under ``.github/``: a workflow there runs with the repository's secrets. No contract except the
    approved one, added, changed or deleted: the contracts are what later pull requests are held to. Only files.
    """
    problems: list[str] = []
    for mode, path in entries:
        parts =[part.casefold() for part in path.split("/")]
        shown = _code(path)[:200]
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in path) or "\\" in path:
            problems.append(f"a file name has a control character or a backslash ({shown})")
        elif ".git" in parts or ".." in parts:
            problems.append(f"{shown} is not a path inside the repository's files")
        elif parts[0] == ".github":
            problems.append(f"{shown} is under .github/")
        elif path != contract_file and any(pair == (CONTEXER_DIR, CONTRACTS_DIR) for pair in zip(parts, parts[1:], strict=False)):
            problems.append(f"{shown} is a contract other than the approved one")
        elif mode not in _FILE_MODES:
            problems.append(f"{shown} is a symbolic link or a submodule (mode {_code(mode)})")
    return problems


def publish_patch(
    plan: HandoffPlan,
    patch: bytes,
    outcome: RunOutcome,
    contract: Contract,
    *,
    approved_by: str,
    issue: int | None = None,
    intent: IntentSpec | None = None,
    client_factory: Callable[[str, str], GitHubClient] | None = None,
) -> Handoff:
    """Commit a patch that another job made, push it and open the pull request.

    The patch and ``outcome`` come from a job in which a coding agent had a shell, so neither is believed.
    ``contract`` and ``approved_by`` are what this job read on the issue itself. The patch is applied to an
    index of its own and the commit is made from that index: no file of it is written to the checkout, and
    nothing of the project is run. What it would commit is then read back from the index (not from the
    patch's text) and refused when ``patch_problems`` finds anything, when the contract in it is not the one
    approved on the issue, or when the secret scan finds a secret. What ``outcome`` says about the checks is
    shown as it was reported; this job cannot replay them.
    """
    if len(patch) > MAX_PATCH_BYTES:
        raise HandoffError(f"the change is {len(patch):,} bytes as a patch, over the {MAX_PATCH_BYTES:,} this job publishes; nothing was pushed")
    if plan.remote is None or plan.repo is None:
        raise HandoffError("the checkout has no GitHub remote to push to")
    prefix = plan.project.relative_to(plan.root)
    contract_file = (prefix / CONTEXER_DIR / CONTRACTS_DIR / f"{contract.id}.json").as_posix()
    shown = contract.model_copy(update={"approval": None})
    with tempfile.TemporaryDirectory() as scratch:
        index = Path(scratch) / "index"
        _raw_or_fail(plan.root, "read-tree", "HEAD", index=index)
        applied = _git_raw(plan.root, *_STRICT_NAMES, "apply", "--cached", "--whitespace=nowarn", "-", data=patch, index=index)
        if applied is None or applied.returncode != 0:
            said = applied.stderr.decode("utf-8", errors="replace").strip()[-400:] if applied is not None else "git could not be run"
            raise HandoffError(f"the change does not apply to {plan.base} as this job checked it out, so nothing was pushed: {said}")
        raw = _raw_or_fail(plan.root, "diff-index", "--cached", "--raw", "-z", "--no-renames", "--no-abbrev", "HEAD", index=index)
        entries = _raw_entries(raw)
        if not entries:
            raise HandoffError("the change is empty once applied; nothing was pushed")
        problems = patch_problems([(mode, path) for mode, _blob, path in entries], contract_file)
        for _mode, blob, path in entries:
            if path == contract_file and not problems:
                held = _approved_contract(plan.root, blob)
                if held is None or held.content_hash() != contract.content_hash():
                    problems.append(f"{_code(path)} does not hold the checks that were approved on the issue")
                elif held.approval is None or held.approval.by != approved_by or held.approval.sha256 != contract.content_hash():
                    problems.append(f"{_code(path)} does not record the approval that was given on the issue")
                else:
                    shown = held
        if problems:
            more = f" and {len(problems) - 3} more" if len(problems) > 3 else ""
            raise HandoffError(f"the change was not pushed: {'; '.join(problems[:3])}{more}")
        staged = _raw_or_fail(plan.root, "diff-index", "--cached", "-p", "--no-ext-diff", "--no-textconv", "--no-color", "HEAD", index=index)
        leaked = [n for n in prescan(staged.decode("utf-8", errors="replace")) if n.category == "security" and n.severity == "high"]
        if leaked:
            where = ", ".join(f"{_in_project(n.file, prefix)}:{n.line}" if n.line else _in_project(n.file, prefix) for n in leaked[:3])
            raise HandoffError(
                f"the change was not pushed: it adds what looks like a secret ({where}). Revoke it if it is real; the change is in "
                "this workflow run's artifact for whoever takes it from here."
            )
        tree = _raw_or_fail(plan.root, "write-tree", index=index).decode().strip()

    # Text for a commit message: the run's id is the other job's word, and a line break in it would add a trailer.
    outcome = outcome.model_copy(update={"run_id": outcome.run_id if re.fullmatch(r"[\w.-]{1,80}", outcome.run_id) else "unknown"})
    who = ("-c", f"user.name={_BOT[0]}", "-c", f"user.email={_BOT[1]}")
    message = _commit_message(outcome, shown)
    commit = _raw_or_fail(plan.root, *who, "commit-tree", "--no-gpg-sign", "-p", "HEAD", "-m", message, tree).decode().strip()
    automatic = shown.approval is not None and shown.approval.by == AUTOMATIC_APPROVAL
    succeeded = outcome.terminal == "succeeded" and not (holds_pull_request(outcome.review) or automatic or flaky_checks(outcome))
    branch = _free_branch(plan, f"contexer/{contract.id}")
    # Pushed by its id: no local branch, no checkout, and no hook of the repository.
    ref = f"{commit}:refs/heads/{branch}"
    if _git(plan.root, *_NO_HOOKS, *_push_auth(plan), "push", "--quiet", plan.remote, ref, timeout=180, tokens=True) is None:
        raise HandoffError(f"`git push {plan.remote} {branch}` failed, so there is no pull request")
    compare = f"https://github.com/{plan.repo}/compare/{plan.base}...{branch}?expand=1"
    token = github_token()
    if token is None:
        return Handoff(branch, commit, True, compare, False, not succeeded, "No GitHub token; open the pull request from the link.")
    factory = client_factory or (lambda repo, tok: GitHubClient(repo, tok))
    client = factory(plan.repo, token)
    try:
        pull = client.open_pull(
            title=_title(outcome, shown),
            head=branch,
            base=plan.base,
            body=pull_request_body(outcome, shown, issue=issue, intent=intent),
            draft=not succeeded,
        )
    except GitHubError as exc:
        return Handoff(branch, commit, True, compare, False, not succeeded, f"Opening the pull request failed: {exc}")
    finally:
        client.close()
    return Handoff(branch, commit, True, str(pull.get("html_url") or compare), True, bool(pull.get("draft", not succeeded)))


def _raw_entries(raw: bytes) -> list[tuple[str, str, str]]:
    """``git diff-index --raw -z`` as (new mode, new blob, path), one per changed path."""
    fields = raw.decode("utf-8", errors="surrogateescape").split("\0")
    entries: list[tuple[str, str, str]] = []
    for meta, path in zip(fields[0::2], fields[1::2], strict=False):
        parts = meta.lstrip(":").split()  # old mode, new mode, old blob, new blob, status
        if len(parts) >= 5:
            entries.append((parts[1], parts[3], path.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")))
    return entries


def _approved_contract(root: Path, blob: str) -> Contract | None:
    """The contract a blob holds, or None when it is not one."""
    found = _git_raw(root, "cat-file", "blob", blob)
    if found is None or found.returncode != 0:
        return None
    try:
        return Contract.model_validate_json(found.stdout)
    except ValueError:
        return None


@dataclass
class Screenshots:
    """The screenshots that were pushed, and where: what the pull request's body shows."""

    repo: str
    branch: str
    shots: list[CheckScreenshot]


def _push_screenshots(plan: HandoffPlan, shots: list[CheckScreenshot], branch: str, contract_id: str) -> bool:
    """Push the screenshots to ``branch`` as one commit with no parent. False if a step failed.

    No local branch, no index and no checkout: the files go into git's store, a tree and a commit are made
    from them, and the commit is pushed by its id. So nothing lands on the default branch or in the work's
    history, and the pull request links the images by the branch's name: once the branch is deleted the
    links no longer resolve. No hook of the repository runs for this push: it is not the person's work.
    """
    entries = []
    for shot in shots:
        blob = _git_in(plan.root, shot.data, "hash-object", "-w", "--no-filters", "--stdin")
        if not blob:
            return False
        entries.append(f"100644 blob {blob}\t{shot.name}\0")
    tree = _git_in(plan.root, "".join(entries).encode(), "mktree", "-z")
    if not tree:
        return False
    message = f"Contexer: screenshots of the checks of {contract_id}"
    who = ("-c", f"user.name={_BOT[0]}", "-c", f"user.email={_BOT[1]}")
    made = _git(plan.root, *who, "commit-tree", "--no-gpg-sign", "-m", message, tree)
    if not made:
        return False
    ref = f"{made}:refs/heads/{branch}"
    return _git(plan.root, *_NO_HOOKS, *_push_auth(plan), "push", "--quiet", plan.remote or "", ref, timeout=180, tokens=True) is not None


def flaky_checks(outcome: RunOutcome) -> list[str]:
    """The checks of the final result that failed on the first replay and passed on the second."""
    final = outcome.final
    found: list[str] = []
    for held in final.contracts if final is not None else []:
        for result in held.verification.criteria_results if held.verification is not None else []:
            if result.check_result is not None and result.check_result.flaky:
                found.append(result.criterion_id)
    return found


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
    outcome: RunOutcome,
    contract: Contract,
    *,
    issue: int | None = None,
    intent: IntentSpec | None = None,
    screenshots: Screenshots | None = None,
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
        flaky = flaky_checks(outcome)
        if flaky:
            lines += [
                "",
                f"⚠️ **Opened as a draft: flaky.** {', '.join(f'`{_code(name)}`' for name in flaky)} failed on the "
                "first replay and passed on the second. A slow page and an intermittent bug look the same; a person "
                "should look before this is merged.",
            ]
    else:
        lines.append(f"⚠️ **Not done yet:** {_md(outcome.reason)}")
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
                lines.append(f"| {mark} | {_md(r.description)}{how} | {_md(r.evidence, 200)} |")
            lines.append("")
    if screenshots is not None:
        lines += _screenshot_lines(screenshots)
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
        f"- **Agent:** {_md(outcome.agent)} ·{attempts} attempt(s), {repairs} repair round(s){cost} · "
        f"{_duration(outcome.duration_seconds)}",
    ]
    if contract.approval is not None:
        lines.append(
            f"- **Contract:** `{CONTEXER_DIR}/{CONTRACTS_DIR}/{contract.id}.json`, approved by "
            f"{_md(contract.approval.by)} (sha256 `{_code(contract.approval.sha256[:12])}`)"
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


def _screenshot_lines(screens: Screenshots) -> list[str]:
    """The checks that did not pass first and open, the others folded away. Says where the files are."""
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")

    def shown(shot: CheckScreenshot) -> list[str]:
        mark, last = ("✅", "") if shot.passed else ("❌", " (did not pass: the last screen it reached)")
        image = f"{server}/{screens.repo}/blob/{screens.branch}/{shot.name}?raw=true"
        return [f"{mark} `{_code(shot.check_id)}` {_md(shot.description, 200)}{last}", "", f"![Screenshot]({image})", ""]

    passed = [shot for shot in screens.shots if shot.passed]
    lines = [
        "### Screenshots",
        "",
        f"The page as each check last saw it. These are files Contexer pushed to the branch `{screens.branch}` of "
        "this repository because it was asked to (`--screenshots`). They show the app's data as the checks saw "
        "it, to everyone who can read the repository. Deleting that branch removes them from this description.",
        "",
    ]
    for shot in screens.shots:
        lines += shown(shot) if not shot.passed else []
    if passed:
        lines += ["<details>", f"<summary>{len(passed)} that passed</summary>", ""]
        for shot in passed:
            lines += shown(shot)
        lines += ["</details>", ""]
    return lines


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
            after = f"{MOVE_LABELS.get(decision.move, decision.move).capitalize()} ({who}): {_md(decision.reason, 300)}"
        else:
            after = _md(attempt.note, 300) if attempt.note else ""
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
        file = _code(note.file).replace("|", "\\|")  # in a table a bar ends the cell, inside a code span too
        where = f"`{file}:{note.line}`" if file and note.line else (f"`{file}`" if file else "")
        by = "a program" if note.backed else "a model"
        lines.append(f"| {note.severity} | {note.category} | {where} | {by} | {_md(note.explanation, 400)} |")
    return [*lines, ""]


def _title(outcome: RunOutcome, contract: Contract, limit: int = 100) -> str:
    """The goal's first line, shortened and then made plain: a goal that says "closes #12" closes nothing."""
    title = contract.goal.strip().splitlines()[0].strip() if contract.goal.strip() else contract.id
    return _plain(_shorten(title, limit))


def _shorten(text: str, limit: int) -> str:
    """Cut at a word boundary, so a subject never ends mid-word."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{cut}…"


def _commit_message(outcome: RunOutcome, contract: Contract) -> str:
    subject = _title(outcome, contract, 72)
    decision = outcome.final.decision if outcome.final is not None else None
    if outcome.terminal == "succeeded" and decision is not None:
        proof = f"Contexer proved all {decision.verified} checks in Chromium"
    else:
        # One line: a reason of several could add a trailer to the commit, or a line that closes an issue.
        proof = f"Contexer: not done yet — {_plain(' '.join(outcome.reason.split()))}"
    return f"{subject}\n\n{proof} (contract {contract.id}, run {outcome.run_id}).\n"


def _evidence_link(outcome: RunOutcome) -> str:
    run_id = os.environ.get("GITHUB_RUN_ID")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if run_id and repo:
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
        # The gate's Action names it contexer-report, the issue Action contexer-report-issue-<n>-<attempt>.
        return (
            "screenshots and expected-vs-actual in the artifact whose name starts with `contexer-report`, on "
            f"[this workflow run]({server}/{repo}/actions/runs/{run_id})"
        )
    return f"`report.html` in `{CONTEXER_DIR}/runs/{outcome.run_id}/` on the machine that ran it"


_HEADING = re.compile(r"^(\s*)#")


def _quote(text: str) -> str:
    """Several lines as one quote. No line of it is a heading."""
    lines = (_HEADING.sub(r"\1\\#", _inert(line)) for line in text.strip()[:3000].splitlines())
    return "\n".join(f"> {line}" if line.strip() else ">" for line in lines)


def _md(text: str, limit: int | None = None) -> str:
    """One line for a table cell or a list item. Shortened first: a cut after escaping can halve an escape."""
    return _inert(" ".join(str(text).split())[:limit]).replace("|", "\\|")


def _code(text: str) -> str:
    """Text for a code span: nothing in it ends the span, and a file name is copied as it is."""
    return " ".join(str(text).replace("`", "").split())


# What GitHub acts on in text, each matched just before the character that completes it: a mention or an
# e-mail address, #12 and GH-12, a bare URL, a tag or a comment, a link, an image, a link definition, a
# character reference (&#64; is an @) and a code fence.
_LIVE = re.compile(
    r"@(?=[A-Za-z0-9])|#(?=\d)|(?i:GH-)(?=\d)|:(?=//)|(?i:www)(?=\.)|<(?=[A-Za-z/!?])"
    r"|\](?=[(\[:])|!(?=\[)|&(?=[#A-Za-z])|`(?=`)|~(?=~)"
)


def _plain(text: str) -> str:
    """Text from the app, an issue, a model or git, so that GitHub shows it and does nothing with it.

    A zero-width space goes where a mention, an issue reference, a URL, a link, an image, a tag or a code
    fence would otherwise form: nobody is notified and no issue is linked or closed. Nothing is removed, and
    doing it twice changes nothing. Used alone where the text is not markdown or is shown as it is: a
    title, a commit message, a note, an error.
    """
    return _LIVE.sub(lambda found: found.group(0) + "\u200b", text)


def _inert(text: str) -> str:
    """``_plain``, then ``&``, ``<`` and ``[`` as character references. For the pull request's body.

    The only issue reference the body acts on is the ``Closes #N`` Contexer writes itself.
    """
    return _plain(text).replace("&", "&amp;").replace("<", "&lt;").replace("[", "&#91;")


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


def _git_in(cwd: Path, data: bytes, *args: str) -> str | None:
    """Run git with ``data`` on its standard input. What it printed, or None if it failed."""
    try:
        out = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", *args], cwd=str(cwd), env=_git_env(False), input=data, capture_output=True, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.decode("utf-8", errors="replace").strip() if out.returncode == 0 else None


def _git_raw(
    cwd: Path, *args: str, data: bytes | None = None, index: Path | None = None, timeout: float = 120
) -> subprocess.CompletedProcess[bytes] | None:
    """Run git and keep what it printed as bytes (a patch is not always text). None if it could not be run.

    With ``index``, git works on that index file and leaves the checkout's own alone. No repository token.
    """
    env = _git_env(False)
    if index is not None:
        env["GIT_INDEX_FILE"] = str(index)
    try:
        return subprocess.run(
            ["git", "-c", "core.fsmonitor=false", *args], cwd=str(cwd), env=env, input=data, capture_output=True, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _raw_or_fail(cwd: Path, *args: str, index: Path | None = None) -> bytes:
    out = _git_raw(cwd, *args, index=index)
    verb = next((a for a in args if not a.startswith("-") and "=" not in a), args[0])
    if out is None:
        raise HandoffError(f"git {verb} could not be run")
    if out.returncode != 0:
        raise HandoffError(f"git {verb} failed: {(out.stderr or out.stdout).decode('utf-8', errors='replace').strip()[-600:]}")
    return out.stdout


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
    return subprocess.run(
        ["git", "-c", "core.fsmonitor=false", *args],
        cwd=str(cwd), env=_git_env(tokens), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )  # fmt: skip


def _git_env(tokens: bool) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if tokens or k not in REPOSITORY_TOKENS}
    env["GIT_TERMINAL_PROMPT"] = "0"  # never wait on a password prompt nobody sees
    return env
