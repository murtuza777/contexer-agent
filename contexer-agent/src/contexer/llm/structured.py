"""Helpers for extracting structured data from free-form model replies."""

from __future__ import annotations

import json
import re
from typing import Any

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCED_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json_object(text: str, expect_key: str | None = None) -> dict[str, Any]:
    """Parse the JSON object in a model reply.

    Tolerates reasoning blocks, Markdown code fences, and prose around the
    object — common with free/open models even when asked for "only JSON".
    When the prose itself contains JSON fragments, objects holding
    ``expect_key`` are preferred, then the largest: the payload, not a
    fragment quoted while "thinking out loud".
    Raises ``ValueError`` when no object can be recovered.
    """
    raw = _THINK_BLOCK.sub("", text).strip()
    fenced = _FENCED_BLOCK.search(raw)
    for candidate in ([fenced.group(1).strip()] if fenced else []) + [raw]:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data

    decoder = json.JSONDecoder()
    found: list[tuple[bool, int, dict[str, Any]]] = []
    resume_at = 0
    for match in re.finditer(r"\{", raw):
        start = match.start()
        if start < resume_at:
            continue  # inside an object already decoded
        try:
            obj, end = decoder.raw_decode(raw, start)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            resume_at = end
            found.append((expect_key is not None and expect_key in obj, end - start, obj))
    if not found:
        raise ValueError("no JSON object found in model reply")
    return max(found, key=lambda item: (item[0], item[1]))[2]
