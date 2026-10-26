"""OpenRouter's daily free-request limit: read it, warn before a run, explain it after one."""

import httpx
import pytest
import typer
from rich.console import Console

from contexer.agents.opencode_agent import OpenCodeAgent
from contexer.agents.base import AgentTurn
from contexer.cli.run_cli import agent_hint, check_free_quota
from contexer.controller.run import Attempt, RunOutcome
from contexer.llm import discovery
from contexer.llm.discovery import FreeQuota, is_free_model
from contexer.llm.discovery import openrouter_free_quota as real_quota  # conftest stubs the module's copy


def _key_status(payload: dict, status: int = 200) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(status, json=payload))


def test_the_quota_is_read_from_the_key_status() -> None:
    payload = {"data": {"is_free_tier": True, "free_model_daily_requests": {"used": 45, "limit": 50, "remaining": 5}}}
    assert real_quota("sk-test", transport=_key_status(payload)) == FreeQuota(used=45, limit=50, remaining=5)


@pytest.mark.parametrize(
    "transport",
    [
        _key_status({"data": {"usage": 0}}),  # a key the field does not apply to
        _key_status({"error": {"message": "No auth credentials found"}}, status=401),
        httpx.MockTransport(lambda request: httpx.Response(200, text="<html>")),
    ],
)
def test_an_unknown_quota_never_blocks_a_run(transport: httpx.MockTransport) -> None:
    assert real_quota("sk-test", transport=transport) is None


def test_which_models_count_against_the_free_limit() -> None:
    assert is_free_model("nvidia/nemotron-3-ultra-550b-a55b:free")
    assert is_free_model("openrouter/free")
    assert not is_free_model("anthropic/claude-opus-5-5")


def _free_agent() -> OpenCodeAgent:
    return OpenCodeAgent(model="openrouter/nvidia/nemotron-3-ultra-550b-a55b:free", start_server=False)


@pytest.fixture
def quota(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    def set_remaining(remaining: int) -> None:
        monkeypatch.setattr(discovery, "openrouter_free_quota", lambda *_a, **_k: FreeQuota(50 - remaining, 50, remaining))

    return set_remaining


def test_no_requests_left_stops_before_anything_is_spent(quota) -> None:
    quota(0)
    console = Console(record=True, width=200)
    with pytest.raises(typer.Exit) as stopped:
        check_free_quota(console, None, _free_agent(), yes=True)
    assert stopped.value.exit_code == 3
    text = console.export_text()
    assert "No free requests left today" in text and "00:00 UTC" in text


def test_few_requests_left_asks_first_but_unattended_runs_go_ahead(quota, monkeypatch: pytest.MonkeyPatch) -> None:
    quota(5)
    monkeypatch.setattr(typer, "confirm", lambda *_a, **_k: False)
    console = Console(record=True, width=200)
    with pytest.raises(typer.Exit) as declined:
        check_free_quota(console, None, _free_agent(), yes=False)
    assert declined.value.exit_code == 2
    assert "5 are left today" in console.export_text()

    check_free_quota(Console(record=True), None, _free_agent(), yes=True)  # --yes: warned, not stopped


def test_enough_requests_or_a_paid_model_says_nothing(quota) -> None:
    quota(40)
    console = Console(record=True)
    check_free_quota(console, None, _free_agent(), yes=False)
    quota(0)
    check_free_quota(console, None, OpenCodeAgent(model="anthropic/claude-opus-5-5", start_server=False), yes=False)
    assert console.export_text() == ""


def _outcome(error: str, terminal: str = "agent_error") -> RunOutcome:
    turn = AgentTurn(status="failed", error=error)
    attempt = Attempt(n=1, kind="implement", fresh_session=True, agent=turn, snapshot="0", outcome="error", score=0)
    return RunOutcome(run_id="r", contract_id="notes-count", agent="opencode", terminal=terminal, attempts=[attempt])


def test_a_run_that_hits_the_daily_limit_says_what_to_do() -> None:
    hint = agent_hint(_outcome("APIError: Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000"))
    assert hint is not None and "00:00 UTC" in hint and "contexer run --contract notes-count" in hint
    # The limit can also hit a repair turn of a run that otherwise ended on its checks.
    assert agent_hint(_outcome("free-models-per-day", terminal="failed_checks")) is not None
    hint = agent_hint(_outcome("AI_APICallError: 429 Too Many Requests"))
    assert hint is not None and "rate-limiting" in hint
