"""`contexer runs show RUN`: a run's attempts, and with `--diff` what the run or one attempt changed (DX-4)."""

import io
import json
from pathlib import Path

from rich.console import Console
from rich.pager import Pager
from typer.testing import CliRunner

from contexer.checkpoint import ShadowRepo
from contexer.cli import app
from contexer.cli.runs_cli import _print_diff

RUN = "20261126-100000-aaaa"


def _project(root: Path) -> Path:
    """A run of three attempts: the second made things worse and was undone, so the third began from the first."""
    root.mkdir(parents=True, exist_ok=True)
    shadow = ShadowRepo(root)
    snapshots = {}
    for n, text in enumerate(["start\n", "start\nfirst\n", "broken\n", "start\nfirst\nthird\n"]):
        (root / "app.js").write_text(text, encoding="utf-8")
        snapshots[n] = shadow.snapshot(f"{RUN}/{n}")
    attempts = [
        {"n": 1, "kind": "implement", "snapshot": snapshots[1], "changed_files": ["app.js"], "outcome": "fail", "verified": 2, "refuted": 1, "unverified": 0},
        {"n": 2, "kind": "repair", "snapshot": snapshots[2], "changed_files": ["app.js"], "outcome": "fail", "verified": 0, "refuted": 3, "unverified": 0, "reverted_to": 1},
        {"n": 3, "kind": "repair", "snapshot": snapshots[3], "changed_files": ["app.js"], "outcome": "pass", "verified": 3, "refuted": 0, "unverified": 0},
    ]  # fmt: skip
    folder = root / ".contexer" / "runs" / RUN
    folder.mkdir(parents=True)
    run = {"terminal": "succeeded", "attempts": attempts, "diff": shadow.diff(snapshots[0], snapshots[3])}
    (folder / "run.json").write_text(json.dumps(run), encoding="utf-8")
    return root


def _show(project: Path, *args: str) -> tuple[int, str]:
    result = CliRunner().invoke(app, ["runs", "show", *args, "--dir", str(project)], env={"COLUMNS": "200"})
    return result.exit_code, result.output


def test_show_lists_the_attempts_of_a_run_one_per_line(tmp_path: Path) -> None:
    code, out = _show(_project(tmp_path / "p"), RUN)
    assert code == 0, out
    lines = [" ".join(line.split()) for line in out.splitlines()]
    assert any(line.startswith("1 implement") and "2 of 3 checks proven" in line and "1 file changed" in line for line in lines)
    assert any(line.startswith("2 repair") and "0 of 3" in line and "undone, back to attempt 1" in line for line in lines)
    assert any(line.startswith("3 repair") and "3 of 3" in line for line in lines)
    assert "--diff" in out  # how to see a change


def test_diff_prints_what_the_whole_run_changed_as_plain_text_when_piped(tmp_path: Path) -> None:
    code, out = _show(_project(tmp_path / "p"), RUN, "--diff")
    assert code == 0, out
    assert "+first" in out and "+third" in out and "broken" not in out
    assert "\x1b[" not in out  # no colour codes in a pipe or a file
    assert "diff --git a/app.js b/app.js" in out


def test_diff_of_one_attempt_is_against_the_files_that_attempt_began_from(tmp_path: Path) -> None:
    project = _project(tmp_path / "p")
    code, first = _show(project, RUN, "--diff", "--attempt", "1")
    assert code == 0 and "+first" in first and "third" not in first
    _, second = _show(project, RUN, "--diff", "--attempt", "2")
    assert "+broken" in second and "-first" in second
    # Attempt 2 was undone back to attempt 1, so attempt 3 began from attempt 1 and not from "broken".
    _, third = _show(project, RUN, "--diff", "--attempt", "3")
    assert "+third" in third and "broken" not in third


def test_a_very_long_line_of_a_diff_is_not_wrapped_or_cut(tmp_path: Path) -> None:
    project = _project(tmp_path / "p")
    long = "x" * 500
    shadow = ShadowRepo(project)
    (project / "app.js").write_text(long + "\n", encoding="utf-8")
    run_file = project / ".contexer" / "runs" / RUN / "run.json"
    run = json.loads(run_file.read_text(encoding="utf-8"))
    run["diff"] = shadow.diff(run["attempts"][2]["snapshot"], shadow.snapshot())
    run_file.write_text(json.dumps(run), encoding="utf-8")
    result = CliRunner().invoke(app, ["runs", "show", RUN, "--diff", "--dir", str(project)], env={"COLUMNS": "40"})
    assert "+" + long in result.output.splitlines()


def test_errors_are_one_sentence_with_the_next_command(tmp_path: Path) -> None:
    project = _project(tmp_path / "p")
    code, out = _show(project, "20260101-000000-ffff")
    assert code == 2 and "No agent run" in out and "contexer runs" in out
    code, out = _show(project, "../../etc")
    assert code == 2 and "No agent run" in out
    code, out = _show(project, RUN, "--diff", "--attempt", "7")
    assert code == 2 and "attempts 1 to 3" in " ".join(out.split())
    code, out = _show(project, RUN, "--attempt", "1")
    assert code == 2 and "--diff" in out

    ShadowRepo(project).drop_run(RUN)  # what `contexer runs prune` does to a run's snapshots, here with the folder left
    code, out = _show(project, RUN, "--diff", "--attempt", "1")
    flat = " ".join(out.split())
    assert code == 2 and "snapshots" in flat and f"contexer runs show {RUN} --diff" in flat
    code, out = _show(project, RUN, "--diff")
    assert code == 0 and "+third" in out  # the change of the whole run is in run.json


def test_a_run_that_changed_nothing_says_so(tmp_path: Path) -> None:
    folder = tmp_path / ".contexer" / "runs" / RUN
    folder.mkdir(parents=True)
    (folder / "run.json").write_text(json.dumps({"terminal": "needs_human", "attempts": [], "diff": ""}), encoding="utf-8")
    code, out = _show(tmp_path, RUN, "--diff")
    assert code == 0 and "changed no file" in out
    code, out = _show(tmp_path, RUN)
    assert code == 0 and "no attempt" in out


class _Kept(Pager):
    def __init__(self) -> None:
        self.shown = ""

    def show(self, content: str) -> None:
        self.shown = content


DIFF = "diff --git a/app.js b/app.js\n--- a/app.js\n+++ b/app.js\n@@ -1 +1,2 @@\n start\n+first\n-gone\n"


def test_in_a_terminal_the_diff_is_coloured_and_goes_through_the_pager() -> None:
    console = Console(file=io.StringIO(), width=60, force_terminal=True, color_system="standard", legacy_windows=False)
    pager = _Kept()
    _print_diff(console, DIFF, pager=pager, colour=True)
    assert "\x1b[32m+first\x1b[0m" in pager.shown and "\x1b[31m-gone\x1b[0m" in pager.shown
    assert "\x1b[1m+++ b/app.js\x1b[0m" in pager.shown  # a file header is not an added line
    assert console.file.getvalue() == ""  # nothing beside the pager


def test_a_pager_that_cannot_show_colour_gets_plain_text() -> None:
    console = Console(file=io.StringIO(), width=60, force_terminal=True, color_system="standard", legacy_windows=False)
    pager = _Kept()
    _print_diff(console, DIFF, pager=pager, colour=False)
    assert pager.shown == DIFF
