"""Tool-call and action loop detector for the Contexer agent.

Adapted from AgentForge (MIT License, Copyright (c) 2026 Mohit Goyal).
Tracks action signatures across turns, detecting both exact consecutive repeats
and cyclic multi-action loops (e.g. A->B->A->B).
"""

from __future__ import annotations

from collections import deque
import json
from typing import Any, Optional


class LoopDetector:
    """Detects repetitive tool loops and cyclic behavioral patterns."""

    def __init__(self, max_exact_repeats: int = 3, max_cycle_length: int = 5) -> None:
        self.max_exact_repeats = max_exact_repeats
        self.max_cycle_length = max_cycle_length
        self._history: deque[str] = deque(maxlen=30)

    def record_action(self, action_type: str, **details: Any) -> None:
        """Record an action into history for cycle analysis."""
        parts = [action_type]

        if action_type == "tool_call":
            parts.append(str(details.get("tool_name", "")))
            args = details.get("args", {})
            if isinstance(args, dict):
                for k in sorted(args.keys()):
                    try:
                        val = json.dumps(args[k], sort_keys=True, default=str)
                    except Exception:
                        val = str(args[k])
                    parts.append(f"{k}={val}")

        elif action_type == "response":
            text = " ".join(str(details.get("text", "")).split())
            parts.append(text[:300])

        signature = "|".join(parts)
        self._history.append(signature)

    def check_for_loop(self) -> Optional[str]:
        """Check if current history indicates a repetitive loop or cycle.

        Returns:
            Warning description string if a loop is detected, else None.
        """
        if len(self._history) < 2:
            return None

        # 1. Exact consecutive action repeats
        if len(self._history) >= self.max_exact_repeats:
            recent = list(self._history)[-self.max_exact_repeats :]
            if len(set(recent)) == 1:
                return f"Same action repeated {self.max_exact_repeats} times consecutively"

        # 2. Cyclic repeating patterns (e.g. A->B->A->B)
        if len(self._history) >= 4:
            history = list(self._history)
            for cycle_len in range(2, min(self.max_cycle_length + 1, len(history) // 2 + 1)):
                recent = history[-cycle_len * 2 :]
                if recent[:cycle_len] == recent[cycle_len:]:
                    return f"Detected repeating cycle of length {cycle_len}"

        return None

    def clear(self) -> None:
        """Reset action history."""
        self._history.clear()
