"""Gate outcomes are fail-safe: only proven verdicts pass, anything undecided blocks."""

from typing import Optional

from contexer.contract import Contract
from contexer.gate import ContractOutcome, decide
from contexer.verification.checks import CheckResult
from contexer.verification.models import AcceptanceCriterion, CriterionResult, VerificationResult


def _result(cid: str, passed: bool, method: str = "assertion", blocked: bool = False) -> CriterionResult:
    check = CheckResult(criterion_id=cid, passed=passed, blocked=blocked) if method == "assertion" else None
    return CriterionResult(
        criterion_id=cid, description=cid, passed=passed, method=method, check_result=check  # type: ignore[arg-type]
    )


def _outcome(results: list[CriterionResult], approved: bool = True, error: Optional[str] = None) -> ContractOutcome:
    contract = Contract(
        id="c", goal="g", criteria=[AcceptanceCriterion(id=r.criterion_id, description="d") for r in results]
    )
    if approved:
        contract = contract.approved_by("tester")
    verification = VerificationResult(passed=all(r.passed for r in results), criteria_results=results)
    return ContractOutcome(contract=contract, verification=None if error else verification, error=error)


def test_all_proven_verified_passes() -> None:
    decision = decide([_outcome([_result("a", True), _result("b", True)])])
    assert decision.outcome == "pass"
    assert decision.exit_code == 0
    assert decision.verified == 2


def test_a_refuted_proven_check_fails() -> None:
    decision = decide([_outcome([_result("a", True), _result("b", False)])])
    assert decision.outcome == "fail"
    assert decision.exit_code == 1
    assert decision.refuted == 1


def test_blocked_check_needs_action_never_passes() -> None:
    decision = decide([_outcome([_result("a", True), _result("b", False, blocked=True)])])
    assert decision.outcome == "needs_action"
    assert decision.unverified == 1


def test_fail_outranks_needs_action() -> None:
    decision = decide([_outcome([_result("a", False), _result("b", False, blocked=True)])])
    assert decision.outcome == "fail"


def test_judged_results_are_advisory_by_default() -> None:
    outcome = _outcome([_result("a", True), _result("b", False, method="judgment")])
    assert decide([outcome]).outcome == "pass"
    assert decide([outcome]).advisory == 1
    assert decide([outcome], judged_policy="block").outcome == "fail"


def test_contract_with_only_judged_criteria_proves_nothing() -> None:
    decision = decide([_outcome([_result("a", True, method="judgment")])])
    assert decision.outcome == "needs_action"


def test_drafts_block_in_gate_mode_but_not_ad_hoc() -> None:
    outcome = _outcome([_result("a", True)], approved=False)
    assert decide([outcome]).outcome == "needs_action"
    assert decide([outcome], require_approval=False).outcome == "pass"


def test_modified_contract_needs_reapproval() -> None:
    outcome = _outcome([_result("a", True)])
    outcome.contract.goal = "edited after approval"
    decision = decide([outcome])
    assert decision.outcome == "needs_action"
    assert "re-approve" in decision.reasons[0]


def test_app_error_and_contract_errors_are_errors() -> None:
    assert decide([], app_error="unreachable").outcome == "error"
    assert decide([_outcome([], error="boom")]).exit_code == 3
    assert decide([]).outcome == "needs_action"
