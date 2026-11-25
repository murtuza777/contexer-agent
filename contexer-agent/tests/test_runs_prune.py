"""`contexer runs prune`: it removes old run folders and their snapshots, and nothing else (DX-5)."""

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from contexer.checkpoint import ShadowRepo
from contexer.checkpoint.lock import run_lock
from contexer.cli import app

OLD, MID, NEW = "20261101-100000-aaaa", "20261102-100000-bbbb", "20261103-100000-cccc"


def _project(root: Path, runs: tuple[str, ...] = (OLD, MID, NEW)) -> Path:
    """A project with a contract, an intent file, and one run per id: a folder with evidence and two snapshots."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "app.js").write_text("start\n", encoding="utf-8")
    for rel, text in (("contracts/todo.json", '{"id": "todo"}'), ("intent/todo.md", "# todo\n"), ("skills/app.md", "x\n"),
                      ("hook-state.json", "{}")):
        path = root / ".contexer" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    shadow = ShadowRepo(root)
    for run in runs:
        folder = root / ".contexer" / "runs" / run
        (folder / "checks").mkdir(parents=True)
        (folder / "run.json").write_text(json.dumps({"terminal": "succeeded", "attempts": [{}]}), encoding="utf-8")
        (folder / "checks" / "shot.png").write_bytes(b"x" * 2048)
        shadow.snapshot(f"{run}/0")
        (root / "app.js").write_text(f"work of {run}\n", encoding="utf-8")
        shadow.snapshot(f"{run}/1")
    return root


def _prune(project: Path, *args: str, input: str | None = None) -> tuple[int, str]:
    result = CliRunner().invoke(app, ["runs", "prune", "--dir", str(project), *args], env={"COLUMNS": "200"}, input=input)
    return result.exit_code, " ".join(re.sub(r"\x1b\[[0-9;]*m", "", result.output).split())


def _folders(project: Path) -> list[str]:
    return sorted(p.name for p in (project / ".contexer" / "runs").iterdir())


def _digest(*roots: Path) -> str:
    """One hash over the names and bytes of everything under the given files and folders."""
    seen = hashlib.sha256()
    for root in roots:
        for path in sorted([root, *root.rglob("*")] if root.is_dir() else [root]):
            seen.update(str(path).encode())
            if path.is_file():
                seen.update(path.read_bytes())
    return seen.hexdigest()


def _link(link: Path, target: Path) -> bool:
    """A folder link from ``link`` to ``target``: a junction on Windows, a symlink elsewhere. False if the OS refuses."""
    if sys.platform == "win32":
        return subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True).returncode == 0
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        return False
    return True


def test_keeps_the_newest_and_removes_folders_and_their_snapshots_only(tmp_path: Path) -> None:
    project = _project(tmp_path)
    kept = (project / ".contexer" / "contracts", project / ".contexer" / "intent", project / ".contexer" / "skills",
            project / ".contexer" / "hook-state.json", project / "app.js", project / ".contexer" / "runs" / NEW)
    before = _digest(*kept)

    code, out = _prune(project, "--keep", "1", "--yes")

    assert code == 0, out
    assert _folders(project) == [NEW]
    assert OLD in out and MID in out and "Removed 2 runs" in out and "freed" in out
    shadow = ShadowRepo(project)
    assert shadow.resolve(f"{OLD}/0") is None and shadow.resolve(f"{MID}/1") is None
    assert shadow.resolve(f"{NEW}/0") and shadow.resolve(f"{NEW}/1")
    assert _digest(*kept) == before
    assert not (project / ".contexer" / "run.lock").exists()


def test_a_kept_run_can_still_be_restored_and_a_removed_runs_objects_are_gone(tmp_path: Path) -> None:
    project = _project(tmp_path)
    shadow = ShadowRepo(project)
    removed_commit = shadow.resolve(f"{OLD}/1")
    assert removed_commit
    # Something in the removed run's snapshot that no other snapshot holds.
    removed_blob = shadow._git("rev-parse", f"{removed_commit}:app.js").strip()

    code, out = _prune(project, "--keep", "1", "--yes")
    assert code == 0, out

    with pytest.raises(Exception, match="cat-file"):
        shadow._git("cat-file", "-e", removed_blob)
    (project / "app.js").write_text("later edit\n", encoding="utf-8")
    result = CliRunner().invoke(app, ["restore", NEW, "--attempt", "0", "--dir", str(project)])
    assert result.exit_code == 0, result.output
    assert (project / "app.js").read_text(encoding="utf-8") == f"work of {MID}\n"  # what was there when NEW began
    result = CliRunner().invoke(app, ["restore", OLD, "--attempt", "0", "--dir", str(project)])
    assert result.exit_code == 1 and "No snapshot" in result.output


def test_nothing_is_removed_while_a_run_holds_the_lock(tmp_path: Path) -> None:
    project = _project(tmp_path)
    with run_lock(project, "20261120-090000-busy"):
        code, out = _prune(project, "--keep", "0", "--yes")
    assert code == 2
    assert "20261120-090000-busy" in out and "Nothing was removed" in out
    assert _folders(project) == [OLD, MID, NEW]
    assert ShadowRepo(project).resolve(f"{OLD}/0")


def test_dry_run_lists_and_removes_nothing(tmp_path: Path) -> None:
    project = _project(tmp_path)
    before = _digest(project)
    code, out = _prune(project, "--keep", "1", "--dry-run")
    assert code == 0, out
    assert OLD in out and MID in out and NEW not in out
    assert "2 snapshots" in out and "KB" in out and "Dry run" in out
    assert _digest(project) == before  # not even a lock file


def test_with_nobody_at_the_terminal_and_no_yes_nothing_is_removed(tmp_path: Path) -> None:
    project = _project(tmp_path)
    code, out = _prune(project, "--keep", "1")
    assert code == 2
    assert OLD in out and "Nothing was removed" in out and "--yes" in out
    assert _folders(project) == [OLD, MID, NEW]


def test_it_asks_before_removing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from contexer.cli import runs_cli

    monkeypatch.setattr(runs_cli, "is_interactive", lambda: True)
    project = _project(tmp_path)
    code, out = _prune(project, "--keep", "1", input="n\n")
    assert code == 0 and "Nothing was removed" in out
    assert _folders(project) == [OLD, MID, NEW]
    code, out = _prune(project, "--keep", "1", input="y\n")
    assert code == 0 and _folders(project) == [NEW]


def test_a_stopped_run_is_kept_until_it_is_asked_for(tmp_path: Path) -> None:
    project = _project(tmp_path)
    stopped = project / ".contexer" / "runs" / OLD
    (stopped / "run.json").write_text(json.dumps({"terminal": "cancelled"}), encoding="utf-8")
    (stopped / "checkpoint.sqlite").write_bytes(b"")
    ShadowRepo(project).snapshot(f"{OLD}/stopped")

    code, out = _prune(project, "--keep", "1", "--yes")
    assert code == 0, out
    assert _folders(project) == [OLD, NEW]
    assert f"Kept {OLD}" in out and "--resume" in out and "--include-unfinished" in out
    assert ShadowRepo(project).resolve(f"{OLD}/stopped")

    code, out = _prune(project, "--keep", "1", "--yes", "--include-unfinished")
    assert code == 0, out
    assert _folders(project) == [NEW]
    assert ShadowRepo(project).resolve(f"{OLD}/stopped") is None


def test_a_run_killed_before_it_wrote_an_outcome_counts_as_unfinished(tmp_path: Path) -> None:
    project = _project(tmp_path)
    killed = project / ".contexer" / "runs" / OLD
    (killed / "run.json").unlink()
    (killed / "checkpoint.sqlite").write_bytes(b"")
    code, out = _prune(project, "--keep", "0", "--yes")
    assert code == 0, out
    assert _folders(project) == [OLD]


def test_a_link_in_the_runs_folder_is_not_followed(tmp_path: Path) -> None:
    project = _project(tmp_path / "project", runs=(MID, NEW))
    outside = tmp_path / "outside"
    (outside / "deep").mkdir(parents=True)
    (outside / "deep" / "keep.txt").write_text("mine\n", encoding="utf-8")
    runs = project / ".contexer" / "runs"
    if not _link(runs / OLD, outside) or not _link(runs / MID / "linked", outside):
        pytest.skip("this system does not allow creating a folder link here")
    before = _digest(outside)

    code, out = _prune(project, "--keep", "0", "--yes")

    assert code == 0, out
    assert _digest(outside) == before  # neither through a link named like a run, nor through one inside a run
    assert _folders(project) == [OLD]  # the link itself is left for the person
    assert f"Left {OLD}" in out and "link" in out


def test_a_runs_folder_that_is_itself_a_link_is_refused(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / ".contexer").mkdir(parents=True)
    outside = tmp_path / "outside"
    (outside / OLD).mkdir(parents=True)
    (outside / OLD / "keep.txt").write_text("mine\n", encoding="utf-8")
    if not _link(project / ".contexer" / "runs", outside):
        pytest.skip("this system does not allow creating a folder link here")
    code, out = _prune(project, "--keep", "0", "--yes")
    assert code == 1 and "link" in out
    assert (outside / OLD / "keep.txt").is_file()


def test_folders_that_are_not_runs_and_files_are_left(tmp_path: Path) -> None:
    project = _project(tmp_path)
    runs = project / ".contexer" / "runs"
    (runs / "notes").mkdir()
    (runs / "notes" / "mine.txt").write_text("x", encoding="utf-8")
    (runs / "20261101-090000-zzzz.txt").write_text("x", encoding="utf-8")
    code, out = _prune(project, "--keep", "0", "--yes")
    assert code == 0, out
    assert _folders(project) == ["20261101-090000-zzzz.txt", "notes"]
    assert "Left notes" in out


def test_read_only_files_in_a_run_folder_are_removed(tmp_path: Path) -> None:
    project = _project(tmp_path)
    locked = project / ".contexer" / "runs" / OLD / "trace" / "objects" / "pack.idx"
    locked.parent.mkdir(parents=True)
    locked.write_bytes(b"x")
    locked.chmod(stat.S_IREAD)
    code, out = _prune(project, "--keep", "2", "--yes")
    assert code == 0, out
    assert _folders(project) == [MID, NEW]


def test_nothing_to_remove_and_no_runs_at_all(tmp_path: Path) -> None:
    code, out = _prune(tmp_path)
    assert code == 0 and "No runs" in out
    assert not (tmp_path / ".contexer").exists()  # asking did not create anything
    project = _project(tmp_path / "p")
    code, out = _prune(project)  # the default keeps more than three
    assert code == 0 and "Nothing to remove" in out
    assert _folders(project) == [OLD, MID, NEW]


def test_keep_must_not_be_negative_and_dir_may_come_first(tmp_path: Path) -> None:
    project = _project(tmp_path)
    code, _ = _prune(project, "--keep", "-1", "--yes")
    assert code == 2 and _folders(project) == [OLD, MID, NEW]
    result = CliRunner().invoke(app, ["runs", "--dir", str(project), "prune", "--keep", "2", "--yes"])
    assert result.exit_code == 0, result.output
    assert _folders(project) == [MID, NEW]
