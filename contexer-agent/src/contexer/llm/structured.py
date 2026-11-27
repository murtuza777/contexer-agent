"""Helpers for extracting structured data from free-form model replies."""

from __future__ import annotations

import ast
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


# -- a tool call a server returned as text -----------------------------------------------------------

# Keys a model uses for a call's name and for its arguments when it writes the call out.
CALL_NAME_KEYS = ("name", "tool", "tool_name")
CALL_ARGUMENT_KEYS = ("arguments", "args", "parameters", "input", "tool_input")
# gpt-oss (Harmony): its reasoning comes first, on its own channel, when the server passes the raw text on.
_HARMONY_ANALYSIS = re.compile(r"<\|channel\|>analysis<\|message\|>.*?<\|end\|>(?:<\|start\|>assistant)?", re.DOTALL)
# The call syntaxes of the chat templates. Each must end the reply.
_TAGGED_CALLS = (
    # Qwen and other Hermes-style templates: <tool_call>{"name": ..., "arguments": {...}}</tool_call>
    re.compile(r"<tool_call>\s*(?P<body>\{.*\})\s*(?:</tool_call>)?\s*\Z", re.DOTALL),
    # Llama-style: <function=name>{...}</function>
    re.compile(r"<function=(?P<name>[\w.-]+)>\s*(?P<body>\{.*\})\s*(?:</function>)?\s*\Z", re.DOTALL),
    # gpt-oss (Harmony): <|channel|>commentary to=functions.name <|constrain|>json<|message|>{...}<|call|>
    re.compile(r"to=functions\.(?P<name>[\w.-]+)[^{]*?<\|message\|>\s*(?P<body>\{.*\})\s*(?:<\|call\|>)?\s*\Z", re.DOTALL),
)
_CALL_OPENINGS = re.compile(r"<tool_call>|<function=|to=functions\.")
_WHOLE_FENCE = re.compile(r"\A```(?P<kind>[\w-]*)\s*\n(?P<body>.*?)\n?```\Z", re.DOTALL)


def parse_printed_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """The one tool call ``text`` is, as (name, arguments), or None.

    Some servers (Ollama, llama.cpp, vLLM, with Qwen, Gemma or gpt-oss) hand a model's call back as the
    message text. This reads the shapes those templates write and nothing looser, because the same text
    can also be a model quoting an example: a call in a template's own tags may follow other text but
    must end the reply and be the only one; a call written as bare JSON, or in a code fence, must be
    the whole reply. Whether the name is a tool the agent has is for the caller to decide.
    """
    raw = _HARMONY_ANALYSIS.sub("", _THINK_BLOCK.sub("", text)).strip()
    if not raw:
        return None
    if _CALL_OPENINGS.search(raw):
        if len(_CALL_OPENINGS.findall(raw)) != 1:
            return None
        for pattern in _TAGGED_CALLS:
            match = pattern.search(raw)
            if match is None:
                continue
            body = _json(match.group("body"))
            if not isinstance(body, dict):
                return None
            name = match.groupdict().get("name")
            return (name, body) if name else _call_in(body)
        return None
    fenced = _WHOLE_FENCE.match(raw)
    if fenced is not None:
        raw = fenced.group("body").strip()
        if fenced.group("kind") == "tool_code":
            return _python_call(raw)  # Gemma writes the call as Python
    return _call_in(_json(raw))


def _json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


def _call_in(data: Any) -> tuple[str, dict[str, Any]] | None:
    """The call ``data`` describes, in any of the JSON spellings; None when it is not exactly one call."""
    if isinstance(data, list):
        return _call_in(data[0]) if len(data) == 1 else None
    if not isinstance(data, dict):
        return None
    for wrapper in ("tool_calls", "tool_call"):
        if wrapper in data:
            return _call_in(data[wrapper])
    function = data.get("function")
    if isinstance(function, dict):
        return _call_in(function)
    name = function if isinstance(function, str) else next((data[k] for k in CALL_NAME_KEYS if k in data), None)
    key = next((k for k in CALL_ARGUMENT_KEYS if k in data), None)
    if not (isinstance(name, str) and name and key):
        return None
    arguments = data[key]
    if isinstance(arguments, str):  # OpenAI's own spelling carries the arguments as JSON text
        arguments = _json(arguments)
    return (name, arguments) if isinstance(arguments, dict) else None


def _python_call(source: str) -> tuple[str, dict[str, Any]] | None:
    """``name(key=value, ...)`` with literal values, as Gemma writes a call. Nothing is evaluated."""
    try:
        node = ast.parse(source, mode="eval").body
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print" and len(node.args) == 1:
            node = node.args[0]  # print(name(...)), as Gemma's own examples have it
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)) or node.args:
            return None
        arguments = {keyword.arg: ast.literal_eval(keyword.value) for keyword in node.keywords if keyword.arg}
    except (SyntaxError, ValueError):
        return None
    return (node.func.id, arguments) if len(arguments) == len(node.keywords) else None


# -- a tool's arguments in the strict form ------------------------------------------------------------


def strict_parameters(schema: dict[str, Any]) -> dict[str, Any]:
    """``schema`` (a tool's arguments as JSON Schema, with no ``$ref``) in the strict form, as a new schema.

    At every depth an object takes no extra property and requires every field, and a field that was
    optional may be null instead of being left out. A map (an object whose ``additionalProperties`` is
    itself a schema) has no fields to list and is left as it is.
    """
    out = dict(schema)
    for key in ("anyOf", "oneOf", "allOf"):
        if isinstance(out.get(key), list):
            out[key] = [strict_parameters(option) if isinstance(option, dict) else option for option in out[key]]
    if isinstance(out.get("items"), dict):
        out["items"] = strict_parameters(out["items"])
    properties = out.get("properties")
    is_map = isinstance(out.get("additionalProperties"), dict)
    if isinstance(properties, dict) or (out.get("type") == "object" and not is_map):
        properties = properties if isinstance(properties, dict) else {}
        required = out.get("required") or []
        out["properties"] = {
            name: strict_parameters(field) if name in required else _nullable(strict_parameters(field))
            for name, field in properties.items()
        }
        out["required"] = list(properties)
        out["additionalProperties"] = False
    return out


def _allows_null(schema: dict[str, Any]) -> bool:
    kind = schema.get("type")
    if kind == "null" or (isinstance(kind, list) and "null" in kind) or None in schema.get("enum", ()):
        return True
    return any(isinstance(option, dict) and _allows_null(option) for option in schema.get("anyOf") or [])


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    """``schema`` or null, the way pydantic writes an optional field: what describes the field stays on top."""
    if _allows_null(schema):
        return schema
    about = {key: schema[key] for key in ("title", "description", "default") if key in schema}
    inner = {key: value for key, value in schema.items() if key not in about}
    return {"anyOf": [inner, {"type": "null"}], **about}
