"""Tests for tolerant JSON extraction from model replies."""

import pytest

from contexer.llm.structured import parse_json_object


@pytest.mark.parametrize(
    "reply",
    [
        '{"ok": true}',
        '```json\n{"ok": true}\n```',
        'Sure, here you go:\n{"ok": true}\nHope that helps!',
        '<think>Should I use {braces}? Yes.</think>\n{"ok": true}',
        # Observed from openrouter/free: untagged reasoning that quotes JSON fragments first.
        'We need checks like {"kind": "no_errors"} or {name}.\n\n{"ok": true}\nDone.',
    ],
)
def test_recovers_the_payload(reply: str) -> None:
    assert parse_json_object(reply, expect_key="ok") == {"ok": True}


def test_without_expected_key_the_largest_object_wins() -> None:
    reply = 'Fragment {"a": 1} then the payload {"criteria": [1, 2, 3], "summary": "x"}'
    assert parse_json_object(reply) == {"criteria": [1, 2, 3], "summary": "x"}


@pytest.mark.parametrize("reply", ["no json here", "[1, 2, 3]", "{broken"])
def test_rejects_replies_without_an_object(reply: str) -> None:
    with pytest.raises(ValueError):
        parse_json_object(reply)
