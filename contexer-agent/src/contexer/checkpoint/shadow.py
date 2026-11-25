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

import contextlib
import os
import re
import subprocess
from pathlib import Path

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
    # Files that hold secrets or local data. A project with no .gitignore still must not lose them on a revert,
    # and they must never reach a diff, a prompt or a pull request.
    ".env",
    ".env.local",
    ".env.*.local",
    ".dev.vars",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
)
# Paths git ignored at some snapshot of this project. Once here, a path stays out of every later snapshot.
_FROZEN_FILE = "contexer-frozen"
_MAX_FROZEN = 5000
# What a run may be called where its snapshots are listed or dropped: one ref-name component, nothing git reads as a pattern.
_RUN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_PRUNE_PROGRAM = "gc.recentObjectsHook"

_IDENTITY = {
    "GIT_AUTHOR_NAME": "contexer",
    "GIT_AUTHOR_EMAIL": "contexer@localhost",
    "GIT_COMMITTER_NAME": "contexer",
    "GIT_COMMITTER_EMAIL": "contexer@localhost",
}


class SnapshotError(Exception):
    """A git operation on the snapshot repository failed."""


def unsafe_work_tree(path: str | Path) -> str | None:
    """Why ``path`` must not be snapshotted, if it must not: a home folder or a drive root holds far
    more than an app, and a snapshot would copy all of it."""
    resolved = Path(path).resolve()
    if resolved == Path(resolved.anchor):
        return f"{resolved} is the root of a drive"
    if resolved == Path.home().resolve():
        return f"{resolved} is your home folder"
    return None


class ShadowRepo:
    """Snapshots and restores one project directory."""

    def __init__(self, project_dir: str | Path) -> None:
        self.work_tree = Path(project_dir).resolve()
        self.git_dir = self.work_tree / SHADOW_DIR

    # -- public API ---------------------------------------------------------------

    def snapshot(self, ref: str | None = None, message: str = "contexer snapshot") -> str:
        """Record the current files; return the snapshot's commit id."""
        self._ensure()
        self._freeze_ignored()
        self._git("add", "--all", "--", ".")
        tree = self._git("write-tree").strip()
        commit = self._git("commit-tree", tree, "-m", message).strip()
        if ref:
            self._git("update-ref", f"refs/contexer/{ref}", commit)
        return commit

    def tree(self) -> str:
        """The id of the current files as a tree: the same files give the same id. Records no snapshot."""
        self._ensure()
        self._freeze_ignored()
        self._git("add", "--all", "--", ".")
        return self._git("write-tree").strip()

    def restore(self, commit: str) -> None:
        """Make the work tree match ``commit`` (ignored files are left alone)."""
        self._ensure()
        # Index the current state first so files created since the snapshot
        # are known to git and get removed by the reset.
        self._freeze_ignored()
        self._git("add", "--all", "--", ".")
        self._git("read-tree", "-u", "--reset", commit)

    def resolve(self, ref: str) -> str | None:
        """The commit a snapshot ref (``<run>/<n>``) points to, if it exists."""
        if not (self.git_dir / "HEAD").is_file():
            return None
        try:
            return self._git("rev-parse", "--verify", "--quiet", f"refs/contexer/{ref}^{{commit}}").strip() or None
        except SnapshotError:
            return None

    def changed_paths(self, a: str, b: str) -> list[str]:
        out = self._git("diff", "--no-ext-diff", "--no-textconv", "--name-only", "--no-renames", a, b)
        return [line for line in out.splitlines() if line]

    def diff(self, a: str, b: str, max_chars: int = 200_000) -> str:
        text = self._git("diff", "--no-ext-diff", "--no-textconv", "--no-color", "--stat", "--patch", a, b)
        return text if len(text) <= max_chars else text[:max_chars] + "\n... (diff truncated)\n"

    def run_refs(self, run: str) -> list[str]:
        """The snapshots one run owns, as ``<run>/<name>``. A run is named exactly: never a pattern, never a path."""
        if not _RUN_NAME.fullmatch(run):
            raise SnapshotError(f"'{run}' is not the name of a run")
        if not (self.git_dir / "HEAD").is_file():
            return []
        prefix = f"refs/contexer/{run}/"
        listed = self._git("for-each-ref", "--format=%(refname)", prefix).splitlines()
        return sorted(ref.removeprefix("refs/contexer/") for ref in listed if ref.startswith(prefix))

    def drop_run(self, run: str) -> int:
        """Forget one run's snapshots; return how many there were. The space comes back at the next :meth:`collect`."""
        refs = self.run_refs(run)
        for ref in refs:
            self._git("update-ref", "-d", f"refs/contexer/{ref}")
        return len(refs)

    def collect(self) -> None:
        """Delete what no remaining snapshot needs. ``gc.auto`` is 0, so nothing else ever does this."""
        if not (self.git_dir / "HEAD").is_file():
            return
        # `gc.recentObjectsHook` names a program that git starts while pruning, and no command-line setting
        # turns it off. Contexer never sets it, so one found in this repository's config was planted: remove it.
        if self._configured(_PRUNE_PROGRAM):
            with contextlib.suppress(SnapshotError):
                self._git("config", "--local", "--unset-all", _PRUNE_PROGRAM)
            if self._configured(_PRUNE_PROGRAM):
                raise SnapshotError(f"{_PRUNE_PROGRAM} is set in your git configuration; nothing was collected")
        self._git("gc", "--prune=now", "--quiet")

    def _configured(self, key: str) -> bool:
        try:
            return bool(self._git("config", "--get-all", key).strip())
        except SnapshotError:  # git config exits 1 for a key that is not set
            return False

    # -- internals ----------------------------------------------------------------

    def _ensure(self) -> None:
        if (self.git_dir / "HEAD").is_file():
            return
        unsafe = unsafe_work_tree(self.work_tree)
        if unsafe:
            raise SnapshotError(f"{unsafe}; run Contexer in your app's folder")
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

    def _freeze_ignored(self) -> None:
        """Keep out of this and every later snapshot whatever git ignores right now.

        The shadow repository reads the project's own ``.gitignore``. A coding agent can edit that file,
        and without this, a path it un-ignores (``.env``, a data folder) would be snapshotted: its
        contents would enter the diff, the prompts and a pull request, and a revert to an earlier
        snapshot would delete it from disk. The first snapshot of a run is taken before the agent
        starts, so what the person ignored is frozen then, and the list only grows.
        """
        info = self.git_dir / "info"
        frozen_file = info / _FROZEN_FILE
        known = frozenset(frozen_file.read_text(encoding="utf-8").splitlines()) if frozen_file.is_file() else frozenset()
        listed = self._git("ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z")
        now = {_as_pattern(path) for path in listed.split("\0") if path}
        if now <= known or len(known) >= _MAX_FROZEN:
            return
        frozen = sorted(known | now)[:_MAX_FROZEN]
        frozen_file.write_text("\n".join(frozen) + "\n", encoding="utf-8")
        (info / "exclude").write_text("\n".join([*DEFAULT_EXCLUDES, *frozen]) + "\n", encoding="utf-8")

    def _git(self, *args: str) -> str:
        env = dict(os.environ)
        env.update(_IDENTITY)
        env["GIT_DIR"] = str(self.git_dir)
        env["GIT_WORK_TREE"] = str(self.work_tree)
        env.pop("GIT_INDEX_FILE", None)
        try:
            proc = subprocess.run(
                ["git", *_NO_PROGRAMS, *args],
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


# The snapshot repository is a folder in the project, so the coding agent can write to it. These settings, given
# on the command line, win over anything written into its config: no hook, no file-system monitor and
# no signing program is ever started by a snapshot, a diff or a restore.
_NO_PROGRAMS = (
    "-c", f"core.hooksPath={os.devnull}",
    "-c", "core.fsmonitor=false",
    "-c", "commit.gpgSign=false",
    "-c", "core.pager=cat",
)  # fmt: skip


def _as_pattern(path: str) -> str:
    """One path, as git printed it, as an ignore pattern that matches that path and nothing else."""
    escaped = "".join(f"\\{char}" if char in "\\*?[]" else char for char in path)
    if escaped.endswith(" "):
        escaped = escaped[:-1] + "\\ "
    return "/" + escaped
