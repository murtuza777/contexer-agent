"""End-to-end test of the autonomous Contexer loop."""

from __future__ import annotations

import functools
import http.server
import socket
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from contexer.observer.playwright import PlaywrightObserver
from contexer.opencode.adapter import OpenCodeAdapter
from contexer.opencode.models import ExecutionStatus, OpenCodeDiffItem, OpenCodeExecutionResult, OpenCodeSession
from contexer.verification.verifier import Verifier
from contexer.workflow.loop import AutonomousLoop


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def local_web_app(tmp_path):
    """Spawns a local HTTP server serving a test HTML application."""
    port = _find_free_port()
    html_file = tmp_path / "index.html"
    html_file.write_text(
        "<html><head><title>Test App</title></head><body><h1>Welcome to our App</h1></body></html>",
        encoding="utf-8",
    )

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield f"http://127.0.0.1:{port}", html_file

    server.shutdown()
    server.server_close()


@pytest.mark.anyio
async def test_autonomous_loop_end_to_end(local_web_app):
    """Prove the complete loop: Attempt 1 fails -> Repair prompt dispatched -> Attempt 2 passes."""
    app_url, html_file = local_web_app

    # Mock OpenCode adapter to simulate realistic coding engine behavior
    adapter = MagicMock(spec=OpenCodeAdapter)
    adapter.create_session = AsyncMock(return_value=OpenCodeSession(id="ses_auto_123", title="Test Task"))

    call_count = 0

    async def _send_prompt_side_effect(session_id: str, prompt: str, **kwargs):
        nonlocal call_count
        call_count += 1
        # First call is initial prompt: does NOT fix the button
        if call_count == 1:
            return OpenCodeExecutionResult(
                session_id=session_id,
                status=ExecutionStatus.COMPLETED,
                duration_seconds=1.0,
                response_text="Created initial layout without button.",
                diff=[],
            )

        # Subsequent call is the repair prompt: fixes index.html
        html_file.write_text(
            "<html><head><title>Test App</title></head><body><h1>Welcome</h1><button id='cta'>Get Started</button></body></html>",
            encoding="utf-8",
        )
        return OpenCodeExecutionResult(
            session_id=session_id,
            status=ExecutionStatus.COMPLETED,
            duration_seconds=1.2,
            response_text="Added Get Started button to index.html.",
            diff=[OpenCodeDiffItem(file="index.html", patch="+<button>Get Started</button>", additions=1, deletions=0)],
        )

    adapter.send_prompt = AsyncMock(side_effect=_send_prompt_side_effect)

    from contexer.workflow.criteria import GoalAnalyzer
    from contexer.workflow.planner import EngineeringPlanner
    from contexer.repair.repair import RepairEngine

    observer = PlaywrightObserver(headless=True)
    verifier = Verifier()  # Deterministic criteria verification
    loop = AutonomousLoop(
        adapter=adapter,
        observer=observer,
        verifier=verifier,
        max_attempts=3,
        goal_analyzer=GoalAnalyzer(llm_provider=None),
        planner=EngineeringPlanner(llm_provider=None),
        repair_engine=RepairEngine(llm_provider=None),
    )

    goal = "Create a landing page with a 'Get Started' button."
    result = await loop.run(goal=goal, app_url=app_url)

    # Verifications:
    # 1. Loop succeeded
    assert result.passed is True
    # 2. Required 2 attempts (1 initial failure + 1 repair)
    assert result.attempts == 2
    # 3. Verification result confirms success
    assert result.verification is not None
    assert result.verification.passed is True
    # 4. Final observation saw the button
    assert result.observation is not None
    assert "Get Started" in result.observation.visible_text
    # 5. OpenCode received both the initial goal and the repair prompt
    assert adapter.send_prompt.await_count == 2
    # 6. The button criterion was proven by an executed check, not judged
    button = next(r for r in result.verification.criteria_results if r.criterion_id == "crit-text-1")
    assert button.passed and button.method == "assertion"
    # 7. The coding agent got the executable contract up front...
    initial_prompt = adapter.send_prompt.await_args_list[0].kwargs["prompt"]
    assert 'expect: button "Get Started" is visible' in initial_prompt
    # ...and the repair prompt carried what the browser actually saw
    repair_prompt = adapter.send_prompt.await_args_list[1].kwargs["prompt"]
    assert "Checks That Must Pass" in repair_prompt
    assert 'expected: button "Get Started" is visible' in repair_prompt
    assert "actual:   <no matching element>" in repair_prompt


# -- verification without a coding agent ----------------------------------------------

import io  # noqa: E402

from rich.console import Console  # noqa: E402

from contexer.project.manager import ProjectManager  # noqa: E402
from contexer.project.models import Project, ProjectType  # noqa: E402
from contexer.workflow.inspector import RepositoryContext  # noqa: E402


def _verify_loop(tmp_path: Path) -> tuple[AutonomousLoop, io.StringIO]:
    from contexer.workflow.criteria import GoalAnalyzer

    out = io.StringIO()
    loop = AutonomousLoop(
        console=Console(file=out, width=200, force_terminal=False),
        project_manager=ProjectManager(workspace_root=tmp_path),
        goal_analyzer=GoalAnalyzer(llm_provider=None),
        verifier=Verifier(),
    )
    return loop, out


def _static_project(tmp_path: Path, body: str) -> Project:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(
        f"<html><head><title>Launch</title></head><body><h1>Get started today</h1>{body}</body></html>",
        encoding="utf-8",
    )
    return Project(name="site", path=site, project_type=ProjectType.EXISTING)


@pytest.mark.anyio
async def test_verify_only_serves_static_project_and_proves_criteria(tmp_path: Path) -> None:
    loop, out = _verify_loop(tmp_path)
    project = _static_project(tmp_path, "<button>Get Started</button>")

    result = await loop.verify_only("Create a landing page with a 'Get Started' button", project=project)

    assert result.passed is True, result.verification
    assert result.app_url.startswith("http://127.0.0.1:")  # served over HTTP, not file://
    assert result.verification is not None
    methods = {r.criterion_id: r.method for r in result.verification.criteria_results}
    assert methods["crit-text-1"] == "assertion"
    assert methods["crit-runtime"] == "assertion"
    rendered = out.getvalue()
    assert "crit-text-1" in rendered  # criterion ids are escaped, not eaten as Rich markup
    assert "proven" in rendered


@pytest.mark.anyio
async def test_verify_only_fails_when_the_element_is_missing(tmp_path: Path) -> None:
    loop, out = _verify_loop(tmp_path)
    project = _static_project(tmp_path, "<a href='#'>Get Started</a>")  # a link, not a button

    result = await loop.verify_only("Create a landing page with a 'Get Started' button", project=project)

    assert result.passed is False
    assert result.verification is not None
    button = next(r for r in result.verification.criteria_results if r.criterion_id == "crit-text-1")
    assert not button.passed and button.method == "assertion"
    assert "<no matching element>" in out.getvalue()


@pytest.mark.anyio
async def test_run_requires_a_coding_agent(tmp_path: Path) -> None:
    loop, _ = _verify_loop(tmp_path)
    with pytest.raises(ValueError, match="coding agent"):
        await loop.run("anything")


def test_explicit_url_wins(tmp_path: Path) -> None:
    loop, _ = _verify_loop(tmp_path)
    project = Project(name="web", path=tmp_path, project_type=ProjectType.EXISTING)
    node_ctx = RepositoryContext(project_name="web", project_path=str(tmp_path), is_static_site=False)

    with loop._open_app(project, "http://localhost:5173", node_ctx) as app:
        assert (app.url, app.kind) == ("http://localhost:5173", "external")


@pytest.mark.anyio
async def test_unstartable_project_fails_cleanly_instead_of_guessing_a_port(tmp_path: Path) -> None:
    loop, out = _verify_loop(tmp_path)
    web = tmp_path / "web"
    web.mkdir()
    (web / "pyproject.toml").write_text("[project]\nname = 'web'\n", encoding="utf-8")
    project = Project(name="web", path=web, project_type=ProjectType.EXISTING)

    result = await loop.verify_only("anything", project=project)

    assert result.passed is False
    assert result.error and "contexer.toml" in result.error
    assert "Could not start the app" in out.getvalue()
