"""Shadow-git snapshots: exact restore, ignored files untouched, user repo untouched."""

import subprocess
from pathlib import Path

from contexer.checkpoint import ShadowRepo


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def test_restore_reverts_edits_deletions_and_new_files(tmp_path: Path) -> None:
    _write(tmp_path, "src/app.js", "let a = 1;\n")
    _write(tmp_path, "index.html", "<h1>hi</h1>\n")
    shadow = ShadowRepo(tmp_path)
    good = shadow.snapshot("run/0")

    _write(tmp_path, "src/app.js", "let a = 2; // broken\n")
    (tmp_path / "index.html").unlink()
    _write(tmp_path, "src/new.js", "export {}\n")
    bad = shadow.snapshot("run/1")
    assert sorted(shadow.changed_paths(good, bad)) == ["index.html", "src/app.js", "src/new.js"]

    shadow.restore(good)
    assert (tmp_path / "src" / "app.js").read_text(encoding="utf-8") == "let a = 1;\n"
    assert (tmp_path / "index.html").exists()
    assert not (tmp_path / "src" / "new.js").exists()

    shadow.restore(bad)  # and forward again
    assert "broken" in (tmp_path / "src" / "app.js").read_text(encoding="utf-8")


def test_ignored_and_heavy_files_survive_restore(tmp_path: Path) -> None:
    _write(tmp_path, ".gitignore", ".env\n")
    _write(tmp_path, ".env", "SECRET=1\n")
    _write(tmp_path, "node_modules/pkg/index.js", "module.exports = 1\n")
    _write(tmp_path, "app.js", "1\n")
    shadow = ShadowRepo(tmp_path)
    snap = shadow.snapshot()

    _write(tmp_path, ".env", "SECRET=2\n")
    _write(tmp_path, "node_modules/new/index.js", "x\n")
    _write(tmp_path, "app.js", "2\n")
    shadow.restore(snap)

    assert (tmp_path / "app.js").read_text(encoding="utf-8") == "1\n"
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "SECRET=2\n"  # never snapshotted, never touched
    assert (tmp_path / "node_modules" / "new" / "index.js").exists()


def test_line_endings_are_preserved_exactly(tmp_path: Path) -> None:
    (tmp_path / "crlf.txt").write_bytes(b"a\r\nb\r\n")
    (tmp_path / "lf.txt").write_bytes(b"a\nb\n")
    shadow = ShadowRepo(tmp_path)
    snap = shadow.snapshot()
    (tmp_path / "crlf.txt").write_bytes(b"changed")
    (tmp_path / "lf.txt").write_bytes(b"changed")
    shadow.restore(snap)
    assert (tmp_path / "crlf.txt").read_bytes() == b"a\r\nb\r\n"
    assert (tmp_path / "lf.txt").read_bytes() == b"a\nb\n"


def test_users_own_git_repo_is_untouched(tmp_path: Path) -> None:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True).stdout

    git("init", "-q")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
    _write(tmp_path, "app.js", "1\n")
    status_before = git("status", "--porcelain")
    refs_before = git("for-each-ref")

    shadow = ShadowRepo(tmp_path)
    snap = shadow.snapshot("run/0")
    _write(tmp_path, "app.js", "2\n")
    shadow.restore(snap)

    status_after = git("status", "--porcelain", "--untracked-files=all")
    assert "?? app.js" in status_after and "A " not in status_after  # nothing staged in the user's index
    assert git("for-each-ref") == refs_before  # no refs added to the user's repo
    # Only .contexer/.gitignore is offered for commit; the snapshot repository is ignored.
    assert [line for line in status_after.splitlines() if ".contexer" in line] == ["?? .contexer/.gitignore"]
    assert status_before == "?? app.js\n"


def test_a_home_folder_or_drive_root_is_never_snapshotted(monkeypatch, tmp_path) -> None:
    from pathlib import Path

    import pytest

    from contexer.checkpoint import ShadowRepo, SnapshotError
    from contexer.checkpoint.shadow import unsafe_work_tree

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert "home folder" in unsafe_work_tree(tmp_path)
    assert "root of a drive" in unsafe_work_tree(Path(tmp_path.anchor))
    assert unsafe_work_tree(tmp_path / "my-app") is None
    with pytest.raises(SnapshotError, match="home folder"):
        ShadowRepo(tmp_path).snapshot()
    assert not (tmp_path / ".contexer").exists()


# -- what git ignored when the run began stays out of snapshots, whatever the agent does to .gitignore --------


def test_a_file_that_was_ignored_stays_out_even_after_the_agent_rewrites_gitignore(tmp_path: Path) -> None:
    from contexer.checkpoint import ShadowRepo

    (tmp_path / ".gitignore").write_text("secrets.txt\ndata/\n", encoding="utf-8")
    (tmp_path / "secrets.txt").write_text("API_KEY=real\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "users.json").write_text("[1, 2, 3]\n", encoding="utf-8")
    (tmp_path / "app.js").write_text("one\n", encoding="utf-8")
    shadow = ShadowRepo(tmp_path)
    baseline = shadow.snapshot()

    # The "agent" edits the app and drops the ignore rules.
    (tmp_path / ".gitignore").write_text("# nothing\n", encoding="utf-8")
    (tmp_path / "app.js").write_text("two\n", encoding="utf-8")
    after = shadow.snapshot()

    assert shadow.changed_paths(baseline, after) == [".gitignore", "app.js"]  # not secrets.txt, not data/
    assert "API_KEY" not in shadow.diff(baseline, after)

    shadow.restore(baseline)  # a revert
    assert (tmp_path / "app.js").read_text(encoding="utf-8") == "one\n"
    assert (tmp_path / "secrets.txt").read_text(encoding="utf-8") == "API_KEY=real\n"  # still there
    assert (tmp_path / "data" / "users.json").is_file()


def test_env_files_and_local_databases_are_never_snapshotted_even_with_no_gitignore(tmp_path: Path) -> None:
    from contexer.checkpoint import ShadowRepo

    (tmp_path / "app.js").write_text("one\n", encoding="utf-8")
    shadow = ShadowRepo(tmp_path)
    baseline = shadow.snapshot()

    # Created while the run goes on: by the dev server, or by the agent.
    (tmp_path / ".env").write_text("TOKEN=x\n", encoding="utf-8")
    (tmp_path / ".dev.vars").write_text("SECRET=y\n", encoding="utf-8")
    (tmp_path / "dev.sqlite").write_bytes(b"SQLite format 3\x00")
    (tmp_path / "app.js").write_text("two\n", encoding="utf-8")
    after = shadow.snapshot()

    assert shadow.changed_paths(baseline, after) == ["app.js"]
    shadow.restore(baseline)
    assert (tmp_path / ".env").is_file() and (tmp_path / ".dev.vars").is_file() and (tmp_path / "dev.sqlite").is_file()


def test_an_ignored_name_with_pattern_characters_is_frozen_as_that_name(tmp_path: Path) -> None:
    from contexer.checkpoint import ShadowRepo

    (tmp_path / ".gitignore").write_text(r"notes \[draft\]*.md" + "\n", encoding="utf-8")  # the brackets are literal
    (tmp_path / "notes [draft] #1.md").write_text("private\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("public\n", encoding="utf-8")
    shadow = ShadowRepo(tmp_path)
    baseline = shadow.snapshot()
    (tmp_path / ".gitignore").write_text("", encoding="utf-8")
    (tmp_path / "notes.md").write_text("public, edited\n", encoding="utf-8")
    assert "notes [draft] #1.md" not in shadow.changed_paths(shadow.snapshot(), baseline)
    assert shadow.changed_paths(baseline, shadow.snapshot()) == [".gitignore", "notes.md"]


def test_a_hook_or_a_setting_planted_in_the_snapshot_repository_does_not_run(tmp_path: Path) -> None:
    # The coding agent can write to .contexer/shadow.git through a shell command. Contexer's next snapshot
    # runs git there with the whole environment, which in Actions holds the repository token.
    import sys

    _write(tmp_path, "src/app.js", "let a = 1;\n")
    shadow = ShadowRepo(tmp_path)
    first = shadow.snapshot()
    marker = tmp_path.parent / "ran.txt"
    plant = f'"{Path(sys.executable).as_posix()}" -c "open(r\'{marker.as_posix()}\', \'w\').write(\'x\')"'
    hooks = shadow.git_dir / "hooks"
    hooks.mkdir(exist_ok=True)
    for name in ("pre-commit", "post-commit", "post-index-change", "post-checkout"):
        hook = hooks / name
        hook.write_text("#!/bin/sh\n" + plant + "\n", encoding="utf-8", newline="\n")
        hook.chmod(0o755)
    with (shadow.git_dir / "config").open("a", encoding="utf-8", newline="\n") as config:
        config.write('[core]\n\tfsmonitor = ' + plant.replace('"', '\\"') + "\n[diff]\n\texternal = " + plant.replace('"', '\\"') + "\n")

    _write(tmp_path, "src/app.js", "let a = 2;\n")
    second = shadow.snapshot()
    shadow.diff(first, second)
    shadow.restore(first)

    assert not marker.exists()
    assert (tmp_path / "src/app.js").read_text(encoding="utf-8") == "let a = 1;\n"
