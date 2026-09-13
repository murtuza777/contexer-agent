"""Tests for context management, token estimation, tool output pruning, and loop detection."""

from __future__ import annotations

from contexer.context.loop_detector import LoopDetector
from contexer.context.manager import ContextManager, MessageItem


def test_loop_detector_exact_repeats() -> None:
    detector = LoopDetector(max_exact_repeats=3)

    assert detector.check_for_loop() is None

    # Call 1
    detector.record_action("tool_call", tool_name="read_file", args={"path": "README.md"})
    assert detector.check_for_loop() is None

    # Call 2
    detector.record_action("tool_call", tool_name="read_file", args={"path": "README.md"})
    assert detector.check_for_loop() is None

    # Call 3 (reaches threshold)
    detector.record_action("tool_call", tool_name="read_file", args={"path": "README.md"})
    warning = detector.check_for_loop()
    assert warning is not None
    assert "repeated 3 times consecutively" in warning

    # Clear resets
    detector.clear()
    assert detector.check_for_loop() is None


def test_loop_detector_cyclic_patterns() -> None:
    detector = LoopDetector(max_exact_repeats=3, max_cycle_length=4)

    # Sequence: A, B, A, B
    detector.record_action("tool_call", tool_name="tool_a", args={})
    detector.record_action("tool_call", tool_name="tool_b", args={})
    detector.record_action("tool_call", tool_name="tool_a", args={})
    detector.record_action("tool_call", tool_name="tool_b", args={})

    warning = detector.check_for_loop()
    assert warning is not None
    assert "repeating cycle of length 2" in warning


def test_context_manager_lifecycle() -> None:
    ctx = ContextManager(system_prompt="You are Contexer.")

    ctx.add_user_message("Hello")
    assert ctx.size == 1
    assert len(ctx) == 1

    ctx.add_assistant_message(
        content="I will check files.",
        tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "list_directory"}}],
    )
    assert ctx.size == 2

    ctx.add_tool_result("call_1", "file1.py\nfile2.py")
    assert ctx.size == 3

    # Dictionary representation
    messages = ctx.messages()
    assert len(messages) == 3
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert messages[2]["role"] == "tool"

    # Token estimation
    tokens = ctx.estimate_tokens()
    assert tokens > 0

    # Pruning
    # Add a large tool result
    ctx.add_tool_result("call_2", "line " * 200)
    ctx.add_tool_result("call_3", "line " * 200)
    ctx.add_tool_result("call_4", "line " * 200)
    ctx.add_tool_result("call_5", "line " * 200)
    ctx.add_tool_result("call_6", "line " * 200)

    # Prune keeping recent 2 results
    pruned = ctx.prune_tool_outputs(keep_recent_tool_results=2)
    assert pruned >= 1

    # Clear
    ctx.clear()
    assert ctx.size == 0
