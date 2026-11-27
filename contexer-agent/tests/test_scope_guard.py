"""The scope guard (AGT-3): the scan counts what a change took away, and the files nobody named.

Assertions, a confirmation, a validation: each removal is a note with its count and the lines. A file
that the goal, the Planner's brief and the Diagnoser's leads never named is listed in one low note.
No model decides any of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from contexer.crew.reviewer import prescan, review, scope_notes
from tests.fakes import AgentScript, submit
from tests.loop_helpers import GOOD_JS, RecordingAgent, contract, copy_todo
from tests.test_graph_review import _graph

pytestmark = pytest.mark.anyio


def _diff(path: str, added: list[str], removed: list[str] | None = None, start: int = 10, new: bool = False) -> str:
    removed = removed or []
    return "\n".join(
        [
            f"diff --git a/{path} b/{path}",
            "--- /dev/null" if new else f"--- a/{path}",
            f"+++ b/{path}",
            f"@@ -{start},{len(removed)} +{start},{len(added)} @@",
            *[f"-{line}" for line in removed],
            *[f"+{line}" for line in added],
            "",
        ]
    )


# -- what was taken away, counted, with the lines -----------------------------------------------


def test_removed_assertions_are_counted_and_the_lines_are_shown() -> None:
    [note] = prescan(
        _diff(
            "tests/cart.test.js",
            ["  expect(total).toBeDefined();"],
            removed=["  expect(total).toBe(30);", "  const items = load();", "  expect(items).toHaveLength(2);"],
            start=12,
        )
    )
    assert (note.severity, note.category, note.backed) == ("medium", "tests", True)
    assert "2 assertions were removed" in note.explanation and "1 added" in note.explanation
    assert "line 12 `expect(total).toBe(30);`" in note.explanation and "line 14 `expect(items).toHaveLength(2);`" in note.explanation


def test_a_removed_confirmation_is_counted_and_the_line_is_shown() -> None:
    [note] = prescan(_diff("src/list.js", ["  remove(id);"], removed=['  if (!confirm("Delete this entry?")) return;', "  remove(id);"], start=40))
    assert (note.severity, note.category) == ("medium", "logic")
    assert "1 confirmation" in note.explanation and 'line 40 `if (!confirm("Delete this entry?")) return;`' in note.explanation


@pytest.mark.parametrize(
    ("path", "removed", "added"),
    [
        ("public/signup.html", ['<input name="email" type="email" required>'], ['<input name="email" type="email">']),
        ("src/Form.tsx", ["<input name={name} minLength={8} />"], ["<input name={name} />"]),
        ("src/signup.js", ["  if (!validateEmail(email)) return showError();"], []),
        ("src/signup.js", ["  if (!form.checkValidity()) return;"], ["  // submit"]),
        ("app/forms.py", ["    if not is_valid_age(age):", '        raise ValidationError("age")'], []),
    ],
)
def test_a_removed_validation_is_a_backed_medium_note_with_the_lines(path: str, removed: list[str], added: list[str]) -> None:
    [note] = prescan(_diff(path, added, removed=removed, start=8))
    assert (note.file, note.severity, note.category, note.source, note.backed) == (path, "medium", "logic", "scan", True)
    assert f"{len(removed)} validation" in note.explanation and f"line 8 `{removed[0].strip()}`" in note.explanation


def test_a_validation_that_was_reworded_or_moved_is_not_a_removal() -> None:
    reworded = _diff("src/signup.js", ["  if (!isValidEmail(email)) return showError();"], removed=["  if (!validateEmail(email)) return showError();"])
    assert prescan(reworded) == []
    moved = _diff("src/signup.js", ["  submit(email);"], removed=["  if (!validateEmail(email)) return;"]) + _diff(
        "src/validate.js", ["export function check(email) {", "  return validateEmail(email);", "}"], new=True
    )
    assert prescan(moved) == []  # the change validates as often as before, in another file


def test_what_only_sounds_like_a_validation_is_left_alone() -> None:
    assert prescan(_diff("src/cache.js", [], removed=["  client.invalidateQueries(['todos']);"])) == []
    assert prescan(_diff("README.md", [], removed=["A name is required."])) == []
    assert prescan(_diff("tests/signup.test.js", ["  // gone"], removed=["  fill(form); // required"])) == []


def test_a_line_that_holds_a_secret_is_counted_and_not_shown() -> None:
    key = "AKIA" + "QX4ZT7PLM2VB9KDE"
    [note] = prescan(_diff("src/signup.js", [], removed=[f'  if (!validate(input, "{key}")) return;'], start=3))
    assert "1 validation" in note.explanation and "line 3" in note.explanation and key not in note.explanation


def test_many_removed_lines_are_counted_and_only_the_first_few_are_shown() -> None:
    lines = [f"  expect(value{i}).toBe({i});" for i in range(6)]
    [note] = prescan(_diff("src/cart.spec.ts", [], removed=lines, start=1))
    assert "6 assertions" in note.explanation and "value2" in note.explanation and "value3" not in note.explanation
    assert "and 3 more" in note.explanation


# -- files nobody named ------------------------------------------------------------------------


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "app"
    (project / "src").mkdir(parents=True)
    for name in ("src/cart.js", "src/auth.js", "src/list.js", "package-lock.json"):
        (project / name).write_text("// here\n", encoding="utf-8")
    return project


PLAN = "A brief from reading the project\n\nFiles to change: `src/cart.js`\n\nRead first: `src/list.js`"


def test_a_changed_file_that_nothing_named_is_one_low_note_with_the_count(tmp_path: Path) -> None:
    project = _project(tmp_path)
    diff = (
        _diff("src/cart.js", ["  return sum;"], removed=["  return 0;"])
        + _diff("src/auth.js", ["  return true;"], removed=["  return isAdmin(user);", "  // checked"])
        + _diff("src/list.js", ["// tidy"])
        + _diff("src/new-helper.js", ["export const x = 1;"], new=True)
        + _diff("package-lock.json", ['"x": 1'])
    )
    [note] = scope_notes(diff, project, "The cart shows its total", ["The total is 30"], PLAN)

    assert (note.file, note.line, note.severity, note.category, note.source, note.backed) == ("", 0, "low", "other", "scan", True)
    # The brief named cart.js and list.js; a new file and a lock file are no surprise.
    assert "1 file" in note.explanation and "`src/auth.js` (+1 -2)" in note.explanation
    for named in ("cart.js", "list.js", "new-helper.js", "package-lock.json"):
        assert named not in note.explanation


def test_a_file_the_goal_or_a_check_names_is_in_scope(tmp_path: Path) -> None:
    project = _project(tmp_path)
    diff = _diff("src/cart.js", ["  return sum;"]) + _diff("src/auth.js", ["  return true;"])
    assert scope_notes(diff, project, "Fix the role check in src/auth.js", [], PLAN) == []
    assert scope_notes(diff, project, "The cart shows its total", ["auth.js no longer logs the token"], PLAN) == []
    [note] = scope_notes(diff, project, "The author's name is shown", [], PLAN)  # "author" is not auth.js
    assert "`src/auth.js`" in note.explanation


def test_without_a_plan_that_names_a_file_nothing_is_known_about_scope(tmp_path: Path) -> None:
    project = _project(tmp_path)
    diff = _diff("src/cart.js", ["  return sum;"]) + _diff("src/auth.js", ["  return true;"])
    assert scope_notes(diff, project, "The cart shows its total", [], "") == []
    assert scope_notes(diff, project, "The cart shows its total", [], "Order of work:\n- Render the list first, e.g. the rows.") == []
    assert scope_notes(diff, project, "The cart shows its total", [], "Files to change: `../../outside.js`, `src/missing.js`") == []


def test_a_deleted_file_is_listed_and_a_long_list_is_cut(tmp_path: Path) -> None:
    project = _project(tmp_path)
    deleted = "\n".join(["diff --git a/src/auth.js b/src/auth.js", "--- a/src/auth.js", "+++ /dev/null", "@@ -1,1 +0,0 @@", "-// here", ""])
    [note] = scope_notes(deleted, project, "", [], PLAN)
    assert "`src/auth.js` (deleted)" in note.explanation

    many = "".join(_diff(f"src/extra{i:02d}.js", ["// x"]) for i in range(12))
    [note] = scope_notes(many, project, "", [], PLAN)
    assert "12 files" in note.explanation and "extra07.js" in note.explanation and "extra08.js" not in note.explanation and "and 4 more" in note.explanation


async def test_the_review_adds_the_scope_note_and_it_starts_no_repair_and_holds_nothing(tmp_path: Path) -> None:
    project = _project(tmp_path)
    diff = _diff("src/cart.js", ["  return sum;"]) + _diff("src/auth.js", ["  return true;"])
    result = await review(diff, project, None, intent="The cart shows its total", plan=PLAN, run_project_commands=False, lookup=None)

    [note] = result.notes
    assert note.severity == "low" and "src/auth.js" in note.explanation
    assert result.blocking == [] and not result.holds_pull_request
    assert (await review(diff, project, None, intent="The cart shows its total", run_project_commands=False, lookup=None)).notes == []


async def test_in_a_run_the_planners_brief_says_which_files_were_named(tmp_path: Path) -> None:
    project = copy_todo(tmp_path)
    model = AgentScript(planner=[submit(change=["app.js"], order=["Update the count in render()."])])
    agent = RecordingAgent([{"app.js": GOOD_JS + "// tidied\n", "style.css": "body { margin: 0; }\n"}])
    outcome = await _graph(project, agent, model=model).run(contract(project))

    assert outcome.terminal == "succeeded" and len(agent.prompts) == 1  # advice: no repair turn
    scope = [note for note in outcome.review if "never named" in note.explanation]
    assert len(scope) == 1 and "`style.css`" in scope[0].explanation and "app.js" not in scope[0].explanation
    assert scope[0].severity == "low" and scope[0].backed
