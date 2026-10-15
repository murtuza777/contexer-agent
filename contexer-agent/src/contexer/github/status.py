"""Report a gate decision to GitHub: a commit status and an Actions job summary.

Commit statuses have only success / failure / error / pending — there is no
``neutral`` that a required check would treat as passing — so "needs action"
is reported as ``failure`` with a description that says why. That keeps the
merge blocked until someone approves the contract or fixes the check.

The full evidence lives in ``report.html`` (uploaded as a workflow artifact);
the status links to the workflow run that holds it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

from contexer.gate.models import GateDecision, RunResult

STATUS_CONTEXT = "contexer/acceptance"
_STATES = {"pass": "success", "fail": "failure", "needs_action": "failure", "error": "error"}
_REMOTE = re.compile(r"github\.com[:/](?P<repo>[^/\s]+/[^/\s]+?)(?:\.git)?/?$")


class GitHubReportError(Exception):
    """The status could not be posted."""


@dataclass(frozen=True)
class GitHubTarget:
    repo: str
    sha: str
    token: str
    api_url: str = "https://api.github.com"
    target_url: Optional[str] = None


def detect_target(project_dir: str | Path, token: Optional[str] = None) -> GitHubTarget:
    """Repository, commit and token from the Actions environment, falling back to git."""
    token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise GitHubReportError("no GITHUB_TOKEN (or GH_TOKEN) to post a commit status with")
    repo = os.environ.get("GITHUB_REPOSITORY") or _repo_from_remote(project_dir)
    if not repo:
        raise GitHubReportError("could not tell which GitHub repository this is (no GITHUB_REPOSITORY or github remote)")
    sha = _pull_request_head_sha() or os.environ.get("GITHUB_SHA") or _git(project_dir, "rev-parse", "HEAD")
    if not sha:
        raise GitHubReportError("could not determine the commit to report on")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    run_id = os.environ.get("GITHUB_RUN_ID")
    target_url = f"{server}/{repo}/actions/runs/{run_id}" if run_id else None
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    return GitHubTarget(repo=repo, sha=sha, token=token, api_url=api_url, target_url=target_url)


def post_status(
    target: GitHubTarget,
    decision: GateDecision,
    *,
    context: str = STATUS_CONTEXT,
    client: Optional[httpx.Client] = None,
) -> dict:
    payload: dict[str, str] = {
        "state": _STATES[decision.outcome],
        "context": context,
        "description": status_description(decision),
    }
    if target.target_url:
        payload["target_url"] = target.target_url
    owns_client = client is None
    http = client or httpx.Client(timeout=20.0)
    try:
        response = http.post(
            f"{target.api_url}/repos/{target.repo}/statuses/{target.sha}",
            headers={
                "Authorization": f"Bearer {target.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json=payload,
        )
    except httpx.HTTPError as exc:
        raise GitHubReportError(f"posting the commit status failed: {exc}") from exc
    finally:
        if owns_client:
            http.close()
    if response.status_code >= 300:
        raise GitHubReportError(f"GitHub refused the commit status ({response.status_code}): {response.text[:300]}")
    return response.json()


def status_description(decision: GateDecision) -> str:
    """At most 140 characters, as GitHub requires."""
    head = {
        "pass": "All checks proven in a browser",
        "fail": "Behaviour refuted in a browser",
        "needs_action": "Needs action before merge",
        "error": "Could not verify",
    }[decision.outcome]
    counts = f"{decision.verified} verified, {decision.refuted} refuted, {decision.unverified} unverified"
    text = f"{head}: {counts}"
    if decision.outcome in ("needs_action", "error") and decision.reasons:
        text = f"{head}: {decision.reasons[0]}"
    return text if len(text) <= 140 else text[:137] + "..."


def step_summary(result: RunResult) -> str:
    """Markdown for ``$GITHUB_STEP_SUMMARY``."""
    d = result.decision
    icon = {"pass": "✅", "fail": "❌", "needs_action": "⚠️", "error": "❌"}[d.outcome]
    lines = [f"## {icon} Contexer acceptance gate: {d.headline()}", ""]
    if d.reasons and d.outcome != "pass":
        lines += ["**Why**", ""] + [f"- {_md(r)}" for r in d.reasons[:15]] + [""]
    for outcome in result.contracts:
        contract = outcome.contract
        lines += [f"### {_md(contract.goal)}", f"`{contract.id}` · {contract.status}", ""]
        lines += ["| | Check | How | Evidence |", "|---|---|---|---|"]
        for r in outcome.verification.criteria_results if outcome.verification else []:
            mark = {"verified": "✅", "refuted": "❌", "unverified": "❔"}[r.verdict]
            how = "proven" if r.proven else ("LLM-judged" if r.method == "judgment" else "heuristic")
            lines.append(f"| {mark} | `{r.criterion_id}` {_md(r.description)} | {how} | {_md(r.evidence)[:160]} |")
        lines.append("")
    lines.append("Full evidence (screenshots, traces, expected vs actual) is in the `contexer-report` artifact.")
    return "\n".join(lines) + "\n"


def write_step_summary(result: RunResult) -> Optional[Path]:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return None
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(step_summary(result))
    return Path(path)


def _md(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def _pull_request_head_sha() -> Optional[str]:
    """On pull_request events GITHUB_SHA is a merge commit; report on the PR head instead."""
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or not Path(event_path).is_file():
        return None
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    head = (event.get("pull_request") or {}).get("head") or {}
    sha = head.get("sha")
    return str(sha) if sha else None


def _repo_from_remote(project_dir: str | Path) -> Optional[str]:
    url = _git(project_dir, "remote", "get-url", "origin")
    match = _REMOTE.search(url or "")
    return match.group("repo") if match else None


def _git(project_dir: str | Path, *args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=str(project_dir), capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""
