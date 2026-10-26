"""A small GitHub REST client for issues, pull requests and comments.

The token comes from ``GITHUB_TOKEN`` or ``GH_TOKEN`` (as in Actions), else
from the GitHub CLI's own login (``gh auth token``), so a developer who
already uses ``gh`` needs nothing more.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

import httpx

_REMOTE = re.compile(r"github\.com[:/](?P<repo>[^/\s]+/[^/\s]+?)(?:\.git)?/?$")


class GitHubError(Exception):
    """GitHub could not be reached, or refused the request."""


def github_token() -> Optional[str]:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    gh = shutil.which("gh")
    if gh is None:
        return None
    try:
        out = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def repo_from_url(url: str) -> Optional[str]:
    """``owner/name`` from a GitHub remote URL (https or ssh)."""
    match = _REMOTE.search(url.strip())
    return match.group("repo") if match else None


def repo_of(project_dir: str | Path, remote: str = "origin") -> Optional[str]:
    """The GitHub repository a checkout pushes to: ``GITHUB_REPOSITORY`` in Actions, else the remote."""
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    try:
        out = subprocess.run(
            ["git", "remote", "get-url", remote], cwd=str(project_dir), capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return repo_from_url(out.stdout) if out.returncode == 0 else None


class GitHubClient:
    def __init__(
        self,
        repo: str,
        token: str,
        api_url: Optional[str] = None,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self.repo = repo
        self.api_url = (api_url or os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
        self._http = httpx.Client(
            timeout=30.0,
            transport=transport,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- issues and comments ------------------------------------------------------

    def issue(self, number: int) -> dict[str, Any]:
        issue = self._request("GET", f"/repos/{self.repo}/issues/{number}")
        if issue.get("pull_request"):
            raise GitHubError(f"#{number} in {self.repo} is a pull request, not an issue")
        return issue

    def comments(self, number: int) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for page in range(1, 11):
            batch = self._request("GET", f"/repos/{self.repo}/issues/{number}/comments?per_page=100&page={page}")
            found.extend(batch)
            if len(batch) < 100:
                break
        return found

    def comment(self, number: int, body: str) -> dict[str, Any]:
        return self._request("POST", f"/repos/{self.repo}/issues/{number}/comments", {"body": body})

    def edit_comment(self, comment_id: int, body: str) -> dict[str, Any]:
        return self._request("PATCH", f"/repos/{self.repo}/issues/comments/{comment_id}", {"body": body})

    def permission(self, user: str) -> str:
        """``admin``, ``maintain``, ``write``, ``triage``, ``read`` or ``none``."""
        data = self._request("GET", f"/repos/{self.repo}/collaborators/{user}/permission")
        return str(data.get("role_name") or data.get("permission") or "none")

    # -- pull requests --------------------------------------------------------------

    def open_pull(self, *, title: str, head: str, base: str, body: str, draft: bool) -> dict[str, Any]:
        """Open a pull request, or return the one already open for ``head``."""
        payload = {"title": title, "head": head, "base": base, "body": body, "draft": draft}
        try:
            return self._request("POST", f"/repos/{self.repo}/pulls", payload)
        except GitHubError as exc:
            text = str(exc).lower()
            if draft and "draft" in text and "not supported" in text:
                # Private repositories on some plans have no draft pull requests.
                payload.update(draft=False, title=f"[Draft] {title}")
                return self._request("POST", f"/repos/{self.repo}/pulls", payload)
            if "already exists" in text:
                owner = self.repo.split("/", 1)[0]
                existing = self._request("GET", f"/repos/{self.repo}/pulls?state=open&head={owner}:{head}")
                if existing:
                    return existing[0]
            raise

    # -- internals ------------------------------------------------------------------

    def _request(self, method: str, path: str, payload: Optional[dict[str, Any]] = None) -> Any:
        try:
            response = self._http.request(method, f"{self.api_url}{path}", json=payload)
        except httpx.HTTPError as exc:
            raise GitHubError(f"could not reach GitHub: {exc}") from exc
        if response.status_code >= 300:
            try:
                data = response.json()
                detail = data.get("message", "")
                errors = "; ".join(str(e.get("message") or e) for e in data.get("errors", []) if e)
                detail = f"{detail} ({errors})" if errors else detail
            except (ValueError, AttributeError):
                detail = response.text[:300]
            raise GitHubError(f"GitHub answered {response.status_code} to {method} {path.split('?')[0]}: {detail}")
        return response.json() if response.content else {}
