"""GitHub commit status and job summary: never a quiet pass."""

import json
from pathlib import Path

import httpx
import pytest

from contexer.contract import Contract
from contexer.gate import ContractOutcome, GateDecision, RunResult
from contexer.github import GitHubReportError, GitHubTarget, detect_target, post_status, status_description, step_summary
from contexer.verification.checks import CheckResult
from contexer.verification.models import AcceptanceCriterion, CriterionResult, VerificationResult


def _capture() -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"state": json.loads(request.content)["state"]})

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


TARGET = GitHubTarget(repo="acme/shop", sha="abc123", token="t0ken", target_url="https://github.com/acme/shop/actions/runs/9")


@pytest.mark.parametrize(
    ("outcome", "state"),
    [("pass", "success"), ("fail", "failure"), ("needs_action", "failure"), ("error", "error")],
)
def test_outcomes_map_to_states_with_no_quiet_pass(outcome: str, state: str) -> None:
    client, seen = _capture()
    post_status(TARGET, GateDecision(outcome=outcome, reasons=["[c] is a draft"]), client=client)  # type: ignore[arg-type]
    [request] = seen
    body = json.loads(request.content)
    assert request.url.path == "/repos/acme/shop/statuses/abc123"
    assert request.headers["Authorization"] == "Bearer t0ken"
    assert body["state"] == state
    assert body["context"] == "contexer/acceptance"
    assert body["target_url"].endswith("/actions/runs/9")


def test_refused_status_raises() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, text="forbidden")))
    with pytest.raises(GitHubReportError, match="403"):
        post_status(TARGET, GateDecision(outcome="pass"), client=client)


def test_description_fits_githubs_limit_and_explains_needs_action() -> None:
    long_reason = "x" * 500
    text = status_description(GateDecision(outcome="needs_action", reasons=[long_reason]))
    assert len(text) <= 140 and text.startswith("Needs action before merge")
    assert "3 verified" in status_description(GateDecision(outcome="pass", verified=3))


def test_target_uses_the_pull_request_head_not_the_merge_commit(tmp_path: Path, monkeypatch) -> None:
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"head": {"sha": "headsha"}}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/shop")
    monkeypatch.setenv("GITHUB_SHA", "mergesha")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    target = detect_target(tmp_path)
    assert (target.repo, target.sha) == ("acme/shop", "headsha")
    assert target.target_url == "https://github.com/acme/shop/actions/runs/42"


def test_missing_token_is_a_clear_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(GitHubReportError, match="GITHUB_TOKEN"):
        detect_target(tmp_path)


def test_step_summary_lists_each_check_with_how_it_was_decided() -> None:
    contract = Contract(id="cart", goal="Cart | totals", criteria=[AcceptanceCriterion(id="a", description="d")])
    results = [
        CriterionResult(criterion_id="a", description="Adds to cart", passed=False, method="assertion",
                        evidence="expected 1, got 0", check_result=CheckResult(criterion_id="a", passed=False)),
        CriterionResult(criterion_id="b", description="Looks tidy", passed=True, method="judgment"),
    ]
    result = RunResult(
        run_id="r",
        project_dir="p",
        started_at="now",
        contracts=[ContractOutcome(contract=contract, verification=VerificationResult(passed=False, criteria_results=results))],
        decision=GateDecision(outcome="fail", refuted=1, reasons=["[cart/a] Adds to cart"]),
    )
    md = step_summary(result)
    assert md.startswith("## ❌ Contexer acceptance gate: FAIL")
    assert "| ❌ | `a` Adds to cart | proven | expected 1, got 0 |" in md
    assert "| ✅ | `b` Looks tidy | LLM-judged |" in md
    assert "Cart \\| totals" in md  # pipes escaped so the table survives
