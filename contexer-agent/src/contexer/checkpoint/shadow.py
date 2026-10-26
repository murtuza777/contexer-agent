"""Per-attempt snapshots in a private git repository.

The snapshot repository lives at ``.contexer/shadow.git`` with the project as
its work tree, so it:

* works for directories that are not git repositories at all;
* never touches the user's own ``.git``, branches, index or stash;
* captures edits however they were made (agent tools, shell commands,
  package installs), because it reads the files, not an agent's log.

Restoring never deletes ignored files (``.env``, ``node_modules``): they are
never part of a snapshot. Files created after the snapshot that are *not*
ignored are removed, which is what makes a revert a real revert.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

SHADOW_DIR = Path(".contexer") / "shadow.git"

# Heavy or generated directories that should never be snapshotted, even in a
# project with no .gitignore of its own.
DEFAULT_EXCLUDES = (
    "/.contexer/",
    "node_modules/",
    ".next/",
    ".nuxt/",
    ".svelte-kit/",
    ".turbo/",
    ".vercel/",
    ".cache/",
    "dist/",
    "coverage/",
    ".venv/",
    "venv/",
    "__pycache__/",
    "*.log",
)

_IDENTITY = {
    "GIT_AUTHOR_NAME": "contexer",
    "GIT_AUTHOR_EMAIL": "contexer@localhost",
    "GIT_COMMITTER_NAME": "contexer",
    "GIT_COMMITTER_EMAIL": "contexer@localhost",
}


class SnapshotError(Exception):
    """A git operation on the snapshot repository failed."""


class ShadowRepo:
    """Snapshots and restores one project directory."""

    def __init__(self, project_dir: str | Path) -> None:
        self.work_tree = Path(project_dir).resolve()
        self.git_dir = self.work_tree / SHADOW_DIR

    # -- public API ---------------------------------------------------------------

    def snapshot(self, ref: Optional[str] = None, message: str = "contexer snapshot") -> str:
        """Record the current files; return the snapshot's commit id."""
        self._ensure()
        self._git("add", "--all", "--", ".")
        tree = self._git("write-tree").strip()
        commit = self._git("commit-tree", tree, "-m", message).strip()
        if ref:
            self._git("update-ref", f"refs/contexer/{ref}", commit)
        return commit

    def restore(self, commit: str) -> None:
        """Make the work tree match ``commit`` (ignored files are left alone)."""
        self._ensure()
        # Index the current state first so files created since the snapshot
        # are known to git and get removed by the reset.
        self._git("add", "--all", "--", ".")
        self._git("read-tree", "-u", "--reset", commit)

    def resolve(self, ref: str) -> Optional[str]:
        """The commit a snapshot ref (``<run>/<n>``) points to, if it exists."""
        if not (self.git_dir / "HEAD").is_file():
            return None
        try:
            return self._git("rev-parse", "--verify", "--quiet", f"refs/contexer/{ref}^{{commit}}").strip() or None
        except SnapshotError:
            return None

    def changed_paths(self, a: str, b: str) -> list[str]:
        out = self._git("diff", "--name-only", "--no-renames", a, b)
        return [line for line in out.splitlines() if line]

    def diff(self, a: str, b: str, max_chars: int = 200_000) -> str:
        text = self._git("diff", "--no-color", "--stat", "--patch", a, b)
        return text if len(text) <= max_chars else text[:max_chars] + "\n... (diff truncated)\n"

    # -- internals ----------------------------------------------------------------

    def _ensure(self) -> None:
        if (self.git_dir / "HEAD").is_file():
            return
        from contexer.contract.store import ensure_contexer_dir

        ensure_contexer_dir(self.work_tree)  # keeps shadow.git out of the user's repo
        self._git("init", "--quiet")
        # Byte-exact snapshots: no line-ending conversion on restore.
        self._git("config", "core.autocrlf", "false")
        self._git("config", "core.safecrlf", "false")
        self._git("config", "core.longpaths", "true")
        self._git("config", "gc.auto", "0")
        exclude = self.git_dir / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text("\n".join(DEFAULT_EXCLUDES) + "\n", encoding="utf-8")

    def _git(self, *args: str) -> str:
        env = dict(os.environ)
        env.update(_IDENTITY)
        env["GIT_DIR"] = str(self.git_dir)
        env["GIT_WORK_TREE"] = str(self.work_tree)
        env.pop("GIT_INDEX_FILE", None)
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=self.work_tree,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SnapshotError(f"git {args[0]} failed: {exc}") from exc
        if proc.returncode != 0:
            raise SnapshotError(f"git {' '.join(args[:2])} failed: {proc.stderr.strip() or proc.stdout.strip()}")
        return proc.stdout
