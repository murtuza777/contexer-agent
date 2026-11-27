"""Every tool schema a model is sent is strict: no extra properties, every field required, optional ones nullable."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from contexer.crew.base import SUBMIT_TOOL, wire_schema
from contexer.llm.structured import strict_parameters


def _allows_null(schema: dict[str, Any]) -> bool:
    kind = schema.get("type")
    if kind == "null" or (isinstance(kind, list) and "null" in kind):
        return True
    if None in schema.get("enum", ()):
        return True
    return any(_allows_null(option) for option in schema.get("anyOf", []) + schema.get("oneOf", []))


def _problems(schema: dict[str, Any], where: str = "arguments") -> list[str]:
    """What keeps ``schema`` from being strict, at any depth."""
    found: list[str] = []
    if "$ref" in schema or "$defs" in schema:
        found.append(f"{where}: refers to another schema instead of holding it")
    if schema.get("type") == "object" or "properties" in schema:
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is not False:
            found.append(f"{where}: allows extra properties")
        for name in properties:
            if name not in schema.get("required", []):
                found.append(f"{where}.{name}: is not required")
            found += _problems(properties[name], f"{where}.{name}")
    for key in ("anyOf", "oneOf", "allOf"):
        for option in schema.get(key, []):
            found += _problems(option, where)
    if isinstance(schema.get("items"), dict):
        found += _problems(schema["items"], f"{where}[]")
    return found


def _optional_without_null(tool: BaseTool, parameters: dict[str, Any]) -> list[str]:
    """The tool's optional fields (those with a default) that the sent schema does not let be null."""
    schema = tool.args_schema
    assert isinstance(schema, type) and issubclass(schema, BaseModel)
    return [
        f"{tool.name}.{info.alias or name}"
        for name, info in schema.model_fields.items()
        if not info.is_required() and not _allows_null(parameters["properties"][info.alias or name])
    ]


def _as_tool(name: str, schema: type[BaseModel]) -> BaseTool:
    return StructuredTool.from_function(func=lambda **_: "", name=name, description=f"The {name} tool.", args_schema=schema)


def _every_tool(tmp_path: Path) -> list[BaseTool]:
    """Every tool an agent is given, and every agent's answer as the `submit` tool that carries it."""
    from contexer.browser.tools import BrowserSession
    from contexer.crew import reviewer, tester
    from contexer.crew.challenger import Verdicts
    from contexer.crew.diagnoser import RepairBrief, project_tools
    from contexer.crew.intent import IntentDraft, _FixedChecks
    from contexer.crew.planner import TaskBrief
    from contexer.crew.triage import _Choice

    answers = [Verdicts, RepairBrief, IntentDraft, _FixedChecks, TaskBrief, reviewer.Review, tester.TesterSummary, _Choice]
    return [
        *BrowserSession("http://127.0.0.1:1").tools(),
        *project_tools(tmp_path),
        _as_tool("record_finding", tester._RecordFinding),
        _as_tool("reviewer_tool", reviewer._NoArgs),
        *[_as_tool(f"{SUBMIT_TOOL}_{answer.__name__}", answer) for answer in answers],
    ]


def test_every_tool_schema_is_strict(tmp_path: Path) -> None:
    tools = _every_tool(tmp_path)
    assert len(tools) >= 25  # 13 browser tools, 2 project tools, 2 more, 8 answers
    for tool in tools:
        sent = wire_schema(tool)
        assert sent["type"] == "function" and sent["function"]["name"] == tool.name
        assert sent["function"]["description"]
        parameters = sent["function"]["parameters"]
        assert parameters["type"] == "object"
        assert _problems(parameters, tool.name) == []
        assert _optional_without_null(tool, parameters) == []


def test_the_walk_fails_on_an_optional_field_without_a_null_type() -> None:
    class ReadFile(BaseModel):
        path: str
        lines: int = Field(200, description="How many lines to read.")

    tool = _as_tool("read_file", ReadFile)
    as_written = ReadFile.model_json_schema()
    assert _optional_without_null(tool, as_written) == ["read_file.lines"]
    assert "read_file.lines: is not required" in _problems(as_written, "read_file")
    assert "read_file: allows extra properties" in _problems(as_written, "read_file")
    # The same schema, as it is sent.
    assert _optional_without_null(tool, wire_schema(tool)["function"]["parameters"]) == []


class _Row(BaseModel):
    label: str
    note: str = ""
    count: int | None = None


class _Table(BaseModel):
    title: str
    rows: list[_Row] = Field(default_factory=list)
    first: _Row | None = None
    wide: bool = Field(False, description="True for a wide table.")


def test_strict_parameters_at_every_depth() -> None:
    from langchain_core.utils.function_calling import convert_to_openai_tool

    written = convert_to_openai_tool(_as_tool("table", _Table))["function"]["parameters"]
    before = repr(written)
    strict = strict_parameters(written)

    assert repr(written) == before  # the schema it was given is left as it was
    assert _problems(strict) == []
    assert strict["required"] == ["title", "rows", "first", "wide"]
    properties = strict["properties"]
    assert not _allows_null(properties["title"])  # a required field stays what it was
    assert all(_allows_null(properties[name]) for name in ("rows", "first", "wide"))
    assert properties["wide"]["description"] == "True for a wide table."
    row = properties["rows"]["anyOf"][0]["items"]
    assert row["required"] == ["label", "note", "count"] and row["additionalProperties"] is False
    assert not _allows_null(row["properties"]["label"])
    assert _allows_null(row["properties"]["note"])
    # A field that could already be null is not given a second null.
    assert sum(option.get("type") == "null" for option in row["properties"]["count"]["anyOf"]) == 1


@pytest.mark.parametrize("build", ["openai", "anthropic"])
def test_langchain_takes_a_strict_schema_for_both_protocols(build: str, tmp_path: Path) -> None:
    """Binding makes no request. What a live provider says to these schemas is not tested here."""
    from contexer.browser.tools import BrowserSession

    sent = [wire_schema(tool) for tool in BrowserSession("http://127.0.0.1:1").tools()]
    if build == "openai":
        from langchain_openai import ChatOpenAI

        bound: Any = ChatOpenAI(model="some-model", api_key="made-up", base_url="http://127.0.0.1:1/v1").bind_tools(sent)  # type: ignore[arg-type]
        assert [tool["function"]["parameters"] for tool in bound.kwargs["tools"]] == [s["function"]["parameters"] for s in sent]
    else:
        from langchain_anthropic import ChatAnthropic

        bound = ChatAnthropic(model="claude-some-model", api_key="made-up").bind_tools(sent)  # type: ignore[call-arg, arg-type]
        assert [tool["input_schema"] for tool in bound.kwargs["tools"]] == [s["function"]["parameters"] for s in sent]
    assert [tool.get("name") or tool["function"]["name"] for tool in bound.kwargs["tools"]] == [s["function"]["name"] for s in sent]
