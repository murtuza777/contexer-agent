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
    assert [l for l in status_after.splitlines() if ".contexer" in l] == ["?? .contexer/.gitignore"]
    assert status_before == "?? app.js\n"
