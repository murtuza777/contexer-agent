"""A diff that has to be cut is cut by file: what failed first, then the smallest, and it says what is missing (CTX-2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from contexer.checkpoint import ShadowRepo
from contexer.checkpoint.shadow import cut_diff
from contexer.crew.diagnoser import Failure, diagnose
from contexer.crew.reviewer import review
from contexer.verification.checks import Check, CheckResult, ExpectationOutcome
from tests.fakes import ScriptedChatModel, submit

pytestmark = pytest.mark.anyio


def _file(path: str, lines: int, word: str = "x") -> str:
    body = "\n".join(f"+{word} {n}" for n in range(lines))
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -0,0 +1,{lines} @@\n{body}\n"


STAT = " package-lock.json | 900 +\n src/count.js | 40 +\n src/render.js | 5 +\n style.css | 2 +\n 4 files changed\n\n"
LOCK = _file("package-lock.json", 4_000, "lock")
COUNT = _file("src/count.js", 40, "count")
RENDER = _file("src/render.js", 5, "render")
STYLE = _file("style.css", 2, "style")
DIFF = STAT + LOCK + COUNT + RENDER + STYLE


def _task(model: ScriptedChatModel) -> str:
    return next(m for m in model.seen[0] if isinstance(m, HumanMessage)).text


def _failure(page_error: str) -> Failure:
    check = Check.model_validate({"expect": [{"kind": "text", "target": {"test_id": "remaining-count"}, "equals": "0 left"}]})
    outcome = ExpectationOutcome(description='text of [data-testid="remaining-count"] equals "0 left"', passed=False, actual='"1 left"')
    result = CheckResult(criterion_id="count", passed=False, outcomes=[outcome], page_errors=[page_error])
    return Failure(title="The count is wrong", check=check, result=result)


def test_a_diff_that_fits_is_not_touched() -> None:
    assert cut_diff(DIFF, len(DIFF)) == DIFF
    assert cut_diff("", 10) == ""


def test_a_diff_is_cut_by_file_smallest_first_and_names_what_was_left_out() -> None:
    cut = cut_diff(DIFF, 2_000)

    assert cut.startswith(STAT)  # the list of everything that changed stays
    assert STYLE in cut and RENDER in cut and COUNT in cut and "+lock" not in cut
    assert cut.index(STYLE) < cut.index(RENDER) < cut.index(COUNT)
    assert cut.rstrip().endswith("(left out to fit: package-lock.json)")
    assert len(cut) < 2_100


def test_the_files_named_by_what_failed_come_first() -> None:
    log = "TypeError: remaining is not a function\n    at update (http://localhost:3000/src/count.js:12:5)"
    cut = cut_diff(DIFF, 2_000, mentioned_in=log)
    assert cut.index(COUNT) < cut.index(STYLE) < cut.index(RENDER)

    by_name_only = cut_diff(DIFF, 2_000, mentioned_in="render.js:3 Uncaught ReferenceError")
    assert by_name_only.index(RENDER) < by_name_only.index(STYLE)
    # A name inside another name is not a mention: `prerender.js` is not `render.js`.
    not_named = cut_diff(DIFF, 2_000, mentioned_in="at prerender.js:3")
    assert not_named.index(STYLE) < not_named.index(RENDER)


def test_a_file_that_failed_and_does_not_fit_is_cut_short_and_the_rest_is_named() -> None:
    cut = cut_diff(DIFF, 1_500, mentioned_in="npm ERR! package-lock.json is out of date")

    assert cut.index("+lock 0") < len(STAT) + 200 and "+lock 3999" not in cut
    assert "cut short: package-lock.json" in cut
    assert "left out to fit: " in cut and "src/count.js" in cut.split("left out to fit: ")[1]
    assert len(cut) < 1_700


def test_many_files_left_out_are_counted_not_all_listed() -> None:
    many = "".join(_file(f"src/generated/file{n}.js", 30) for n in range(60))
    cut = cut_diff(many, 1_000)
    named = cut.split("left out to fit: ")[1]
    assert named.count(".js") == 20 and "and 37 more" in named  # three fitted


def test_a_snapshot_diff_over_its_limit_is_cut_the_same_way(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    shadow = ShadowRepo(tmp_path)
    before = shadow.snapshot()
    (tmp_path / "big.txt").write_text("".join(f"line {n}\n" for n in range(400)), encoding="utf-8")
    (tmp_path / "small.txt").write_text("small change\n", encoding="utf-8")
    after = shadow.snapshot()

    cut = shadow.diff(before, after, max_chars=1_000)

    assert "+small change" in cut and "+line 399" not in cut and "(left out to fit: big.txt)" in cut
    assert "+line 399" in shadow.diff(before, after)


async def test_the_diagnoser_is_given_the_file_the_page_error_names_before_a_larger_diff_is_cut(tmp_path: Path) -> None:
    long_diff = STAT + LOCK + COUNT + RENDER + STYLE  # the file that failed is 40,000 characters in
    assert long_diff.index(COUNT) > 12_000
    model = ScriptedChatModel(submit())
    await diagnose(
        [_failure("TypeError: remaining is not a function at update (http://localhost:3000/src/count.js:12:5)")],
        model,
        tmp_path,
        diff=long_diff,
        run_dir=None,
    )
    task = _task(model)
    assert "+count 39" in task and "left out to fit: package-lock.json" in task and "+lock 3999" not in task

    model = ScriptedChatModel(submit())
    await diagnose([_failure("x")], model, tmp_path, diff=long_diff, server_log="Error in render.js\n", run_dir=None)
    task = _task(model)
    assert task.index("+render 0") < task.index("+style 0")  # the server log names it


async def test_the_reviewer_is_given_the_small_files_whole_and_told_which_were_left_out(tmp_path: Path) -> None:
    (tmp_path / "style.css").write_text("x\n", encoding="utf-8")
    long_diff = LOCK + COUNT + RENDER + STYLE
    model = ScriptedChatModel(submit(notes=[]))
    await review(long_diff, tmp_path, model, run_project_commands=False)
    task = _task(model)
    assert "+style 1" in task and "+count 39" in task and "+lock 3999" not in task
    assert "left out to fit: package-lock.json" in task and "use the tools to read the rest" in task
