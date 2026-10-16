"""Runner evidence (screenshots, traces) and how failed steps are classified."""

from pathlib import Path

import pytest

from contexer.verification.checks import Check
from contexer.verification.models import CriterionResult
from contexer.verification.runner import CheckRunner
from contexer.workflow.app_server import StaticAppServer

pytestmark = pytest.mark.anyio

APP = """<!doctype html>
<html><head><meta charset="utf-8"><title>Steps</title><link rel="icon" href="data:,"></head>
<body>
  <label><input type="checkbox" id="stuck" aria-label="Stuck box"> Stuck</label>
  <label><input type="checkbox" id="ok" aria-label="Working box"> Working</label>
  <button disabled>Disabled action</button>
  <script>
    // A checkbox whose handler immediately undoes the click: the bug class
    // where the UI ignores the user.
    document.getElementById("stuck").addEventListener("click", (e) => { e.preventDefault(); });
  </script>
</body></html>
"""


def check(raw: dict) -> Check:
    return Check.model_validate(raw)


@pytest.fixture
def app_url(tmp_path: Path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(APP, encoding="utf-8")
    with StaticAppServer(site) as server:
        yield server.url


@pytest.fixture
def runner() -> CheckRunner:
    return CheckRunner(action_timeout=1.0, expect_timeout=0.5)


async def test_checkbox_that_ignores_the_click_is_refuted_not_blocked(runner: CheckRunner, app_url: str) -> None:
    [result] = await runner.run(
        app_url,
        [("stuck", check({"steps": [{"action": "check", "target": {"role": "checkbox", "name": "Stuck box"}}],
                          "expect": [{"kind": "no_errors"}]}))],
    )
    assert not result.passed
    assert not result.blocked
    assert result.failed_step is None
    assert "stayed unchecked" in result.outcomes[0].actual
    verdict = CriterionResult(criterion_id="stuck", description="", passed=False, method="assertion", check_result=result)
    assert verdict.verdict == "refuted"


async def test_disabled_target_is_refuted_with_reason(runner: CheckRunner, app_url: str) -> None:
    [result] = await runner.run(
        app_url,
        [("disabled", check({"steps": [{"action": "click", "target": {"role": "button", "name": "Disabled action"}}],
                             "expect": [{"kind": "no_errors"}]}))],
    )
    assert not result.blocked
    assert result.outcomes[0].actual == "the element is disabled"


async def test_missing_target_stays_unverified(runner: CheckRunner, app_url: str) -> None:
    [result] = await runner.run(
        app_url,
        [("missing", check({"steps": [{"action": "click", "target": {"role": "button", "name": "Nope"}}],
                            "expect": [{"kind": "no_errors"}]}))],
    )
    assert result.blocked
    verdict = CriterionResult(criterion_id="missing", description="", passed=False, method="assertion", check_result=result)
    assert verdict.verdict == "unverified"


async def test_artifacts_dir_gets_a_screenshot_per_check_and_traces_on_failure(app_url: str, tmp_path: Path) -> None:
    runner = CheckRunner(action_timeout=1.0, expect_timeout=0.5, trace="on-failure")
    artifacts = tmp_path / "evidence"
    ok, bad = await runner.run(
        app_url,
        [
            ("works", check({"steps": [{"action": "check", "target": {"role": "checkbox", "name": "Working box"}}],
                             "expect": [{"kind": "no_errors"}]})),
            ("stuck", check({"steps": [{"action": "check", "target": {"role": "checkbox", "name": "Stuck box"}}],
                             "expect": [{"kind": "no_errors"}]})),
        ],
        artifacts_dir=artifacts,
    )
    assert ok.passed and ok.screenshot and Path(ok.screenshot).is_file()
    assert ok.trace is None  # passing checks keep no trace in on-failure mode
    assert bad.screenshot and Path(bad.screenshot).is_file()
    assert bad.trace and Path(bad.trace).is_file()


async def test_checked_expectation_reads_the_live_state(runner: CheckRunner, app_url: str) -> None:
    [ok, bad] = await runner.run(
        app_url,
        [
            ("ticks", check({"steps": [{"action": "check", "target": {"role": "checkbox", "name": "Working box"}}],
                             "expect": [{"kind": "checked", "target": {"role": "checkbox", "name": "Working box"}}]})),
            ("stays", check({"expect": [{"kind": "checked", "target": {"role": "checkbox", "name": "Working box"}}]})),
        ],
    )
    assert ok.passed
    assert not bad.passed and bad.outcomes[0].actual == "not checked"


async def test_role_name_also_matches_what_the_user_sees(tmp_path: Path) -> None:
    site = tmp_path / "labels"
    site.mkdir()
    (site / "index.html").write_text(
        '<!doctype html><html><head><meta charset="utf-8"><link rel="icon" href="data:,"></head><body>'
        '<ul><li>Milk <button aria-label="Delete Milk" onclick="this.parentElement.remove()">×</button></li></ul>'
        "</body></html>",
        encoding="utf-8",
    )
    with StaticAppServer(site) as server:
        runner = CheckRunner(action_timeout=1.0, expect_timeout=0.5)
        by_text, by_name, missing = await runner.run(
            server.url,
            [
                ("text", check({"steps": [{"action": "click", "target": {"role": "button", "name": "×"}}],
                                "expect": [{"kind": "hidden", "target": {"text": "Milk"}}]})),
                ("name", check({"expect": [{"kind": "visible", "target": {"role": "button", "name": "Delete Milk"}}]})),
                ("none", check({"expect": [{"kind": "visible", "target": {"role": "button", "name": "Archive"}}]})),
            ],
        )
    assert by_text.passed, by_text.failure_report()
    assert by_name.passed
    assert not missing.passed  # matching what users see must not make absent elements appear
