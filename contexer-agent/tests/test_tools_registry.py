"""Unit tests for the Contexer ToolRegistry."""

import asyncio
from typing import Any

from pydantic import BaseModel, Field
import pytest

from contexer.tools.registry import ToolRegistry
from contexer.tools.schemas import Tool


class SimpleArgs(BaseModel):
    name: str = Field(..., description="A person's name")
    count: int = Field(default=1, description="Repeat count")


def simple_sync_handler(name: str, count: int = 1) -> str:
    return f"Hello, {name}!" * count


async def simple_async_handler(name: str, count: int = 1) -> str:
    await asyncio.sleep(0.001)
    return f"Async Hello, {name}!" * count


class TestToolRegistry:
    """Registry operations: register, lookup, unregister, schemas, execution."""

    def test_register_and_lookup(self) -> None:
        registry = ToolRegistry()
        tool = Tool(
            name="greet",
            description="Greet someone",
            args_schema=SimpleArgs,
            handler=simple_sync_handler,
        )
        registry.register(tool)

        retrieved = registry.get("greet")
        assert retrieved is not None
        assert retrieved.name == "greet"
        assert retrieved.description == "Greet someone"

    def test_lookup_nonexistent_returns_none(self) -> None:
        registry = ToolRegistry()
        assert registry.get("missing_tool") is None

    def test_unregister(self) -> None:
        registry = ToolRegistry()
        tool = Tool(
            name="greet",
            description="Greet someone",
            args_schema=SimpleArgs,
            handler=simple_sync_handler,
        )
        registry.register(tool)
        assert registry.get("greet") is not None

        removed = registry.unregister("greet")
        assert removed == tool
        assert registry.get("greet") is None

        # Unregistering again returns None
        assert registry.unregister("greet") is None

    def test_list_tools(self) -> None:
        registry = ToolRegistry()
        assert registry.list() == []

        t1 = Tool(name="t1", description="d1", args_schema=SimpleArgs, handler=simple_sync_handler)
        t2 = Tool(name="t2", description="d2", args_schema=SimpleArgs, handler=simple_sync_handler)
        registry.register(t1)
        registry.register(t2)

        tool_list = registry.list()
        assert len(tool_list) == 2
        assert {t.name for t in tool_list} == {"t1", "t2"}

    def test_schemas_generation(self) -> None:
        registry = ToolRegistry()
        tool = Tool(
            name="greet",
            description="Greet someone",
            args_schema=SimpleArgs,
            handler=simple_sync_handler,
        )
        registry.register(tool)

        schemas = registry.schemas()
        assert len(schemas) == 1
        assert schemas[0]["name"] == "greet"
        assert schemas[0]["description"] == "Greet someone"
        assert "properties" in schemas[0]["parameters"]
        assert "name" in schemas[0]["parameters"]["properties"]

    def test_to_tools_openai_format(self) -> None:
        registry = ToolRegistry()
        assert registry.to_tools() == []

        tool = Tool(
            name="greet",
            description="Greet someone",
            args_schema=SimpleArgs,
            handler=simple_sync_handler,
        )
        registry.register(tool)

        tools = registry.to_tools()
        assert len(tools) == 1
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "greet"
        assert tools[0]["function"]["description"] == "Greet someone"
        assert "properties" in tools[0]["function"]["parameters"]
        # Also verify backwards/alias methods
        assert registry.to_openai_tools() == tools
        assert registry.to_gemini_tools() == tools

    def test_execute_sync_tool_success(self) -> None:
        registry = ToolRegistry()
        tool = Tool(
            name="greet",
            description="Greet someone",
            args_schema=SimpleArgs,
            handler=simple_sync_handler,
        )
        registry.register(tool)

        result = asyncio.run(registry.execute("greet", {"name": "Alice", "count": 2}))
        assert result == "Hello, Alice!Hello, Alice!"

    def test_execute_async_tool_success(self) -> None:
        registry = ToolRegistry()
        tool = Tool(
            name="async_greet",
            description="Greet someone async",
            args_schema=SimpleArgs,
            handler=simple_async_handler,
        )
        registry.register(tool)

        result = asyncio.run(registry.execute("async_greet", {"name": "Bob"}))
        assert result == "Async Hello, Bob!"

    def test_execute_unregistered_tool(self) -> None:
        registry = ToolRegistry()
        result = asyncio.run(registry.execute("missing", {}))
        assert "Error: Tool 'missing' is not recognized" in result

    def test_execute_invalid_arguments(self) -> None:
        registry = ToolRegistry()
        tool = Tool(
            name="greet",
            description="Greet someone",
            args_schema=SimpleArgs,
            handler=simple_sync_handler,
        )
        registry.register(tool)

        # Missing required argument 'name'
        result = asyncio.run(registry.execute("greet", {"count": 5}))
        assert "Error: Invalid arguments for tool 'greet'" in result

    def test_execute_handler_exception(self) -> None:
        def buggy_handler(name: str, count: int = 1) -> str:
            raise ValueError("Something broke in handler")

        registry = ToolRegistry()
        tool = Tool(
            name="buggy",
            description="A buggy tool",
            args_schema=SimpleArgs,
            handler=buggy_handler,
        )
        registry.register(tool)

        result = asyncio.run(registry.execute("buggy", {"name": "Test"}))
        assert "Error executing tool 'buggy': Something broke in handler" in result

    def test_execute_handler_exception_bounded(self) -> None:
        def huge_error_handler(name: str, count: int = 1) -> str:
            raise RuntimeError("X" * 5000)

        registry = ToolRegistry()
        tool = Tool(
            name="huge_err",
            description="Tool that raises gigantic error",
            args_schema=SimpleArgs,
            handler=huge_error_handler,
        )
        registry.register(tool)

        result = asyncio.run(registry.execute("huge_err", {"name": "Test"}))
        assert "error message truncated" in result
        assert len(result) < 3000


class TestDefaultRegistryAcceptanceTools:
    """Acceptance tests for all default registered tools and their dispatch."""

    @pytest.fixture
    def workspace(self, tmp_path):
        from pathlib import Path
        import subprocess
        import shutil

        ws = tmp_path / "accept_ws"
        ws.mkdir()
        (ws / "README.md").write_text("# Contexer Acceptance Test\n", encoding="utf-8")
        (ws / "main.py").write_text("print('hello')\n", encoding="utf-8")

        git_bin = shutil.which("git")
        if git_bin:
            subprocess.run([git_bin, "init", "-b", "main"], cwd=ws, capture_output=True)
            subprocess.run([git_bin, "config", "user.name", "Test"], cwd=ws, capture_output=True)
            subprocess.run([git_bin, "config", "user.email", "test@test.com"], cwd=ws, capture_output=True)
            subprocess.run([git_bin, "add", "."], cwd=ws, capture_output=True)
            subprocess.run([git_bin, "commit", "-m", "init"], cwd=ws, capture_output=True)

        return ws

    def test_all_required_tools_registered(self, workspace):
        from contexer.tools import create_default_registry

        registry = create_default_registry(workspace)
        tool_names = {t.name for t in registry.list()}
        expected = {
            "list_directory",
            "read_file",
            "write_file",
            "search_files",
            "file_exists",
            "execute_command",
            "git_status",
            "git_diff",
            "git_log",
            "git_branch",
        }
        assert expected.issubset(tool_names)

    def test_schema_generation_openai_format(self, workspace):
        from contexer.tools import create_default_registry

        registry = create_default_registry(workspace)
        tools = registry.to_tools()
        assert len(tools) >= 10
        for t in tools:
            assert t["type"] == "function"
            assert "name" in t["function"]
            assert "description" in t["function"]
            assert "parameters" in t["function"]

    def test_acceptance_dispatch_flow(self, workspace):
        from contexer.tools import create_default_registry
        import sys

        registry = create_default_registry(workspace)

        # 1. list_directory
        res1 = asyncio.run(registry.execute("list_directory", {"path": "."}))
        assert "README.md" in res1

        # 2. read_file
        res2 = asyncio.run(registry.execute("read_file", {"path": "README.md"}))
        assert "Contexer Acceptance Test" in res2

        # 3. execute_command
        cmd = f'"{sys.executable}" --version'
        res3 = asyncio.run(registry.execute("execute_command", {"command": cmd}))
        assert "Exit code: 0" in res3

        # 4. git_status
        res4 = asyncio.run(registry.execute("git_status", {}))
        assert "main" in res4 or "Git error" in res4

        # 5. git_diff
        res5 = asyncio.run(registry.execute("git_diff", {}))
        assert isinstance(res5, str)

        # 6. file_exists
        res6 = asyncio.run(registry.execute("file_exists", {"path": "README.md"}))
        assert "File exists: 'README.md'" in res6
