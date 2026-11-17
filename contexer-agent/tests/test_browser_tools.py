"""Browser tools: a model can operate the app, and every action is recorded in the check language.

Real Chromium against the todo and members fixtures; no model.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import pytest

from contexer.appserver import open_app
from contexer.browser.tools import BrowserSession
from contexer.contract import ContractStore
from contexer.evidence.rundir import RunDir
from contexer.gate.session import VerificationSession
from contexer.verification.checks import MASK, Check, Expectation, Step

pytestmark = pytest.mark.anyio

FIXTURES = Path(__file__).resolve().parents[1] / "bench" / "fixtures"
TOOL_NAMES = [
    "snapshot", "click", "fill", "press", "select", "check", "uncheck", "hover", "goto",
    "read_errors", "screenshot", "expect", "reset",
]  # fmt: skip


def _copy(name: str, tmp_path: Path, bug: Optional[str] = None) -> Path:
    work = tmp_path / name
    shutil.copytree(FIXTURES / name / "app", work, ignore=shutil.ignore_patterns("runs"))
    if bug:
        shutil.copytree(FIXTURES / name / "bugs" / bug, work, dirs_exist_ok=True)
    return work


@pytest.fixture
async def todo(tmp_path: Path) -> AsyncIterator[BrowserSession]:
    work = _copy("todo", tmp_path)
    with open_app(work) as running:
        async with BrowserSession(running.url, run_dir=tmp_path / "run") as session:
            yield session


async def call(session: BrowserSession, name: str, **args: Any) -> str:
    """Call a tool the way the agent loop does: by name, with the arguments a model would send."""
    tool = next(t for t in session.tools() if t.name == name)
    return str(await tool.ainvoke(args))


def _contract_check(criterion_id: str) -> Check:
    contract = ContractStore(FIXTURES / "todo" / "app").load("todo-basics")
    check = next(c.check for c in contract.criteria if c.id == criterion_id)
    assert check is not None
    return check


async def test_the_tools_are_the_verbs_of_the_check_language(todo: BrowserSession) -> None:
    tools = todo.tools()
    assert [t.name for t in tools] == TOOL_NAMES
    assert all(t.description for t in tools)
    # A model is told which locator strategies exist: the schema names them.
    schema = json.dumps(next(t for t in tools if t.name == "click").args_schema.model_json_schema())  # type: ignore[union-attr]
    for strategy in ("role", "name", "text", "label", "placeholder", "test_id", "css"):
        assert f'"{strategy}"' in schema


async def test_actions_are_recorded_as_the_same_steps_the_hand_written_contract_uses(todo: BrowserSession) -> None:
    wanted = _contract_check("complete-decrements")

    assert (await call(todo, "fill", target={"placeholder": "What needs doing?"}, value="Buy milk")).startswith("ok")
    await call(todo, "click", target={"role": "button", "name": "Add"})
    await call(todo, "fill", target={"placeholder": "What needs doing?"}, value="Walk dog")
    await call(todo, "click", target={"role": "button", "name": "Add"})
    await call(todo, "check", target={"role": "checkbox", "name": "Complete Buy milk"})
    seen = await call(todo, "expect", kind="text", target={"test_id": "remaining-count"}, equals="1 left")

    assert todo.recorder.steps == wanted.steps
    assert seen.startswith("e1 PASS")
    [observation] = todo.recorder.observations
    assert observation.id == "e1" and observation.passed
    assert observation.steps == wanted.steps
    assert observation.expectation == wanted.expect[0]


async def test_press_select_hover_uncheck_and_goto_are_recorded_too(todo: BrowserSession) -> None:
    await call(todo, "fill", target={"placeholder": "What needs doing?"}, value="Buy milk")
    await call(todo, "press", key="Enter", target={"placeholder": "What needs doing?"})
    await call(todo, "check", target={"role": "checkbox", "name": "Complete Buy milk"})
    await call(todo, "uncheck", target={"role": "checkbox", "name": "Complete Buy milk"})
    await call(todo, "hover", target={"role": "button", "name": "Clear completed"})
    await call(todo, "goto", path="/index.html")

    assert [s.action for s in todo.recorder.steps] == ["fill", "press", "check", "uncheck", "hover", "goto"]
    assert todo.recorder.steps[1] == _contract_check("add-clears-input").steps[1]
    assert todo.recorder.steps[-1] == Step(action="goto", value="/index.html")


async def test_snapshot_shows_roles_names_test_ids_and_placeholders_and_records_nothing(todo: BrowserSession) -> None:
    snapshot = await call(todo, "snapshot")
    assert 'button "Add"' in snapshot
    assert "remaining-count" in snapshot and "What needs doing?" in snapshot
    assert todo.recorder.steps == [] and todo.recorder.observations == []


async def test_a_locator_that_matches_nothing_is_a_clear_error_with_the_snapshot_not_an_exception(
    todo: BrowserSession,
) -> None:
    result = await call(todo, "click", target={"role": "button", "name": "Save task"})

    assert result.startswith("Error:")
    assert 'button "Save task"' in result and "matches nothing" in result
    assert 'button "Add"' in result  # what the page offers instead
    assert todo.recorder.steps == []  # an action that did not happen is not part of the recording


async def test_a_selector_form_the_runner_does_not_support_is_refused(todo: BrowserSession) -> None:
    two = await call(todo, "click", target={"role": "button", "text": "Add"})
    assert two.startswith("Error:") and "exactly one of" in two
    xpath = await call(todo, "click", target={"xpath": "//button"})
    assert xpath.startswith("Error:")
    role = await call(todo, "click", target={"role": "clickything", "name": "Add"})
    assert role.startswith("Error:") and "unknown ARIA role" in role
    assert todo.recorder.steps == []


async def test_expect_reports_pass_or_fail_with_what_was_seen(todo: BrowserSession) -> None:
    await call(todo, "fill", target={"placeholder": "What needs doing?"}, value="Buy milk")
    await call(todo, "click", target={"role": "button", "name": "Add"})

    passed = await call(todo, "expect", kind="visible", target={"text": "Buy milk"})
    failed = await call(todo, "expect", kind="text", target={"test_id": "remaining-count"}, equals="5 left")
    invalid = await call(todo, "expect", kind="text", target={"test_id": "remaining-count"})
    baseline = await call(todo, "expect", kind="text", target={"test_id": "remaining-count"}, changed=True)

    assert passed.startswith("e1 PASS")
    assert failed.startswith("e2 FAIL") and '"1 left"' in failed
    assert invalid.startswith("Error:") and "needs equals, contains, matches" in invalid
    assert baseline.startswith("Error:") and "changed" in baseline  # nothing to compare with mid-exploration
    assert [(o.id, o.passed) for o in todo.recorder.observations] == [("e1", True), ("e2", False)]
    assert todo.recorder.observations[1].expectation == Expectation.model_validate(
        {"kind": "text", "target": {"test_id": "remaining-count"}, "equals": "5 left"}
    )


async def test_read_errors_reports_uncaught_exceptions_and_failed_requests(tmp_path: Path) -> None:
    work = _copy("todo", tmp_path, bug="complete-throws")
    with open_app(work) as running:
        async with BrowserSession(running.url, run_dir=tmp_path / "run") as session:
            assert (await call(session, "read_errors")).startswith("No errors")
            await call(session, "fill", target={"placeholder": "What needs doing?"}, value="Buy milk")
            await call(session, "click", target={"role": "button", "name": "Add"})
            await call(session, "check", target={"role": "checkbox", "name": "Complete Buy milk"})
            errors = await call(session, "read_errors")
            assert "exception" in errors.lower()
            no_errors = await call(session, "expect", kind="no_errors")
            assert no_errors.startswith("e1 FAIL")

            await call(session, "goto", path="/missing-page.html")
            assert "404" in await call(session, "read_errors")
            assert len(session.recorder.steps) == 4  # reading errors records nothing


async def test_screenshot_saves_a_jpeg_in_the_run_folder(todo: BrowserSession, tmp_path: Path) -> None:
    result = await call(todo, "screenshot")
    shots = sorted((tmp_path / "run").rglob("*.jpg"))
    assert len(shots) == 1 and shots[0].stat().st_size > 1000
    assert shots[0].name in result
    assert todo.recorder.steps == []


async def test_reset_gives_a_fresh_page_and_starts_a_new_recording(todo: BrowserSession) -> None:
    await call(todo, "fill", target={"placeholder": "What needs doing?"}, value="Buy milk")
    await call(todo, "click", target={"role": "button", "name": "Add"})
    await call(todo, "expect", kind="visible", target={"text": "Buy milk"})

    result = await call(todo, "reset")

    assert result.startswith("ok")
    assert 'button "Add"' in result  # the fresh page comes with the answer
    assert todo.recorder.steps == []
    # What was observed before the reset keeps the steps that led to it.
    assert len(todo.recorder.observations[0].steps) == 2
    gone = await call(todo, "expect", kind="hidden", target={"text": "Buy milk"})
    assert gone.startswith("e2 PASS")
    assert todo.recorder.observations[1].steps == []


async def test_reset_runs_the_projects_reset_command_and_reports_when_it_fails(tmp_path: Path) -> None:
    work = _copy("todo", tmp_path)
    ran: list[str] = []

    async def reset_ok() -> Optional[str]:
        ran.append("reset")
        return None

    async def reset_broken() -> Optional[str]:
        return "`npm run db:reset` exited with code 1"

    with open_app(work) as running:
        async with BrowserSession(running.url, reset=reset_ok) as session:
            assert (await call(session, "reset")).startswith("ok")
            assert ran == ["reset"]
        async with BrowserSession(running.url, reset=reset_broken) as session:
            failed = await call(session, "reset")
            assert failed.startswith("Error:") and "db:reset" in failed


async def test_the_page_reuses_the_projects_sign_in_and_can_be_reset_signed_out(tmp_path: Path) -> None:
    work = _copy("members", tmp_path)
    with open_app(work) as running:
        verification = VerificationSession(work, RunDir.create(work))
        state = await verification.signed_in_state(running)
        assert state is not None, verification.sign_in_error
        async with BrowserSession(running.url, storage_state=state) as session:
            signed_in = await call(session, "expect", kind="visible", target={"role": "heading", "name": "Dashboard"})
            assert signed_in.startswith("e1 PASS")
            assert session.recorder.observations[0].login is None  # follows the project: signed in

            assert (await call(session, "reset", signed_out=True)).startswith("ok")
            signed_out = await call(session, "expect", kind="hidden", target={"role": "heading", "name": "Dashboard"})
            assert signed_out.startswith("e2 PASS")
            assert session.recorder.observations[1].login is False


async def test_a_typed_password_is_masked_in_what_the_model_reads(tmp_path: Path) -> None:
    work = _copy("members", tmp_path)
    with open_app(work) as running:
        async with BrowserSession(running.url) as session:
            await call(session, "goto", path="/login.html")
            typed = await call(session, "fill", target={"label": "Password"}, value="correct-horse")
            snapshot = await call(session, "snapshot")
            missing = await call(session, "click", target={"role": "button", "name": "No such button"})

            assert "correct-horse" not in typed
            assert "correct-horse" not in snapshot and MASK in snapshot
            assert "correct-horse" not in missing  # the snapshot inside an error is masked too
            # The recording keeps the real value: a replay has to type it.
            assert session.recorder.steps[-1].value == "correct-horse"
            assert "correct-horse" in session.secrets


async def test_closing_the_session_closes_the_browser(tmp_path: Path) -> None:
    work = _copy("todo", tmp_path)
    with open_app(work) as running:
        async with BrowserSession(running.url) as session:
            assert (await call(session, "snapshot")) != ""
        after = await call(session, "snapshot")
        assert after.startswith("Error:") and "closed" in after


async def test_an_action_that_lands_but_reports_a_timeout_does_not_corrupt_the_recording(
    todo: BrowserSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slow machine can time out an action that did happen. The recording must still match the page."""
    perform = todo._runner._perform

    async def lands_then_times_out(page: Any, step: Step, base_url: str) -> None:
        await perform(page, step, base_url)
        raise TimeoutError("Locator.fill: Timeout 3000ms exceeded.")

    monkeypatch.setattr(todo._runner, "_perform", lands_then_times_out)

    # A fill can be checked: the text is in the field, so it happened and is recorded.
    filled = await call(todo, "fill", target={"placeholder": "What needs doing?"}, value="Buy milk")
    assert filled.startswith("ok")
    assert [s.action for s in todo.recorder.steps] == ["fill"]

    # A click cannot be checked. It is not recorded, the model is told to reset, and what is
    # observed from here on is marked unreliable.
    clicked = await call(todo, "click", target={"role": "button", "name": "Add"})
    assert clicked.startswith("Error:") and "reset" in clicked
    assert [s.action for s in todo.recorder.steps] == ["fill"]
    monkeypatch.setattr(todo._runner, "_perform", perform)
    await call(todo, "expect", kind="visible", target={"text": "Buy milk"})
    assert todo.recorder.observations[-1].reliable is False

    # A fresh page clears it.
    await call(todo, "reset")
    await call(todo, "expect", kind="hidden", target={"text": "Buy milk"})
    assert todo.recorder.observations[-1].reliable is True


async def test_a_target_sent_as_text_gets_an_example_instead_of_a_schema_error(todo: BrowserSession) -> None:
    result = await call(todo, "click", target="<parameter=placeholder>\nWhat needs doing?")
    assert result.startswith("Error:") and '{"role": "button", "name": "Add"}' in result
    unknown = await call(todo, "click", target={"button": "Add"})
    assert unknown.startswith("Error:") and '{"placeholder": "Email"}' in unknown
    assert todo.recorder.steps == []


async def test_a_count_may_be_given_as_an_exact_number(todo: BrowserSession) -> None:
    """Models write `count equals 1`; the check language says min and max. Accept the first, record the second."""
    await call(todo, "fill", target={"placeholder": "What needs doing?"}, value="Buy milk")
    await call(todo, "click", target={"role": "button", "name": "Add"})

    exact = await call(todo, "expect", kind="count", target={"role": "listitem"}, equals="1")
    wrong = await call(todo, "expect", kind="count", target={"role": "listitem"}, equals="3")

    assert exact.startswith("e1 PASS") and wrong.startswith("e2 FAIL")
    assert todo.recorder.observations[0].expectation == Expectation.model_validate(
        {"kind": "count", "target": {"role": "listitem"}, "min": 1, "max": 1}
    )
    not_a_number = await call(todo, "expect", kind="count", target={"role": "listitem"}, equals="many")
    assert not_a_number.startswith("Error:")


def test_only_the_password_of_a_sign_in_is_a_secret_not_the_email() -> None:
    """Masking the sign-in email hid a real bug: a page that greets the member by email looked like dots."""
    from contexer.browser.tools import credential_secrets
    from contexer.config.project import load_project_config

    auth = load_project_config(FIXTURES / "members" / "app").auth
    assert auth is not None
    assert credential_secrets(auth.as_check()) == ["correct-horse"]

    by_reference = Check.model_validate(
        {
            "steps": [
                {"action": "fill", "target": {"label": "Username"}, "value": "${APP_USER}"},
                {"action": "fill", "target": {"css": "#field-2"}, "value": "${APP_PASSWORD}"},
                {"action": "fill", "target": {"placeholder": "One-time code"}, "value": "123456"},
                {"action": "click", "target": {"role": "button", "name": "Sign in"}},
            ],
            "expect": [{"kind": "visible", "target": {"text": "Home"}}],
        }
    )
    env = {"APP_USER": "ada", "APP_PASSWORD": "s3cret-value"}
    assert credential_secrets(by_reference, env) == ["s3cret-value", "123456"]
