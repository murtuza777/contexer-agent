"""Contracts: hashing, approval status, and the on-disk store."""

import json
from pathlib import Path

import pytest

from contexer.contract import Contract, ContractError, ContractStore, slugify
from contexer.verification.checks import Check
from contexer.verification.models import AcceptanceCriterion


def _contract(cid: str = "add-task") -> Contract:
    return Contract(
        id=cid,
        goal="Users can add a task",
        criteria=[
            AcceptanceCriterion(
                id="crit-1",
                description="Adding shows the task",
                verification_method="interactive_test",
                check=Check.model_validate(
                    {
                        "steps": [{"action": "fill", "target": {"placeholder": "Task"}, "value": "Milk"}],
                        "expect": [{"kind": "css", "target": {"css": "body"}, "property": "color", "changed": True}],
                    }
                ),
            ),
            AcceptanceCriterion(id="crit-2", description="Looks tidy"),
        ],
    )


def test_status_moves_from_draft_to_approved_to_modified() -> None:
    contract = _contract()
    assert contract.status == "draft"

    approved = contract.approved_by("alice")
    assert approved.status == "approved"
    assert approved.approval is not None and approved.approval.sha256 == approved.content_hash()

    edited = approved.model_copy(update={"goal": "Users can add two tasks"})
    assert edited.status == "modified"


def test_hash_ignores_metadata_but_not_checks() -> None:
    a = _contract()
    b = a.model_copy(update={"summary": "different", "created_at": "2000-01-01T00:00:00Z"})
    assert a.content_hash() == b.content_hash()

    changed = _contract()
    assert changed.criteria[0].check is not None
    changed.criteria[0].check.steps[0].value = "Bread"
    assert changed.content_hash() != a.content_hash()


def test_store_round_trips_dsl_aliases_and_approval(tmp_path: Path) -> None:
    store = ContractStore(tmp_path)
    path = store.save(_contract())

    raw = json.loads(path.read_text(encoding="utf-8"))
    expectation = raw["criteria"][0]["check"]["expect"][0]
    assert expectation["property"] == "color"  # DSL alias, not the field name
    assert "check" not in raw["criteria"][1]  # judged criteria carry no null check

    approved = store.approve("add-task", by="bob")
    reloaded = store.load("add-task")
    assert reloaded.status == "approved"
    assert reloaded.approval == approved.approval
    assert reloaded.content_hash() == _contract().content_hash()


def test_store_writes_gitignore_that_keeps_only_contracts(tmp_path: Path) -> None:
    ContractStore(tmp_path).save(_contract())
    gitignore = (tmp_path / ".contexer" / ".gitignore").read_text(encoding="utf-8")
    assert "/*" in gitignore and "!/contracts/" in gitignore


def test_unknown_contract_lists_the_known_ones(tmp_path: Path) -> None:
    store = ContractStore(tmp_path)
    store.save(_contract("one"))
    with pytest.raises(ContractError, match="known: one"):
        store.load("two")


def test_unique_ids_and_slugs(tmp_path: Path) -> None:
    store = ContractStore(tmp_path)
    assert slugify("Users can complete a task!") == "users-can-complete-task"
    first = store.unique_id("Add a task")
    store.save(_contract(first))
    assert store.unique_id("Add a task") == f"{first}-2"
