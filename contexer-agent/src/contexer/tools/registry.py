"""Schema-first registry and centralized invocation boundary for tools.

The invocation order adapts AgentForge's proven registry approach: lookup,
validate, approve, execute, clean/redact, and return an observation. Contexer
deliberately leaves hooks, dynamic discovery, MCP, and subagents for later.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, TYPE_CHECKING

from pydantic import ValidationError

from contexer.safety.observations import prepare_tool_observation
from contexer.tools.schemas import Tool, ToolResult

if TYPE_CHECKING:
    from contexer.safety.approval import ApprovalDecision, ApprovalManager

logger = logging.getLogger(__name__)

_MAX_ERROR_CHARS = 2_048


def _bound_error_text(error: str, max_chars: int = _MAX_ERROR_CHARS) -> str:
    """Cap errors so a broken tool cannot exhaust the model context."""
    if len(error) <= max_chars:
        return error
    return error[:max_chars] + f"\n... [error message truncated: {len(error) - max_chars:,} chars omitted]"


class ToolRegistry:
    """Owns tool registration, provider schemas, and safe invocation."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool, replacing an existing entry with the same name."""
        self._tools[tool.name] = tool
        logger.debug("Registered tool '%s'", tool.name)

    def unregister(self, name: str) -> Tool | None:
        """Unregister a tool, returning it when it was registered."""
        tool = self._tools.pop(name, None)
        if tool:
            logger.debug("Unregistered tool '%s'", name)
        return tool

    def get(self, name: str) -> Tool | None:
        """Look up one registered tool."""
        return self._tools.get(name)

    def list(self) -> list[Tool]:
        """Return registered tools in registration order."""
        return list(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        """Return provider-neutral function schemas."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": (
                    tool.parameters_schema
                    if tool.parameters_schema is not None
                    else tool.args_schema.model_json_schema()
                ),
            }
            for tool in self._tools.values()
        ]

    def to_tools(self) -> list[dict[str, Any]]:
        """Return OpenAI-compatible function declarations."""
        return [tool.to_tool_declaration() for tool in self._tools.values()]

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Alias retained for provider adapter clarity."""
        return self.to_tools()

    def to_gemini_tools(self) -> list[Any]:
        """Temporary compatibility alias for the existing Gemini adapter seam."""
        return self.to_tools()

    async def invoke(
        self,
        name: str,
        args: dict[str, Any],
        *,
        approval_manager: ApprovalManager | None = None,
        redact_output: bool = True,
        protect_observation: bool = True,
        max_output_chars: int = 20_000,
    ) -> ToolResult:
        """Validate, approve, execute, and prepare a structured result.

        This is the runtime-facing API. Passing an approval manager enables the
        user-facing safety policy; direct library callers can use the
        backwards-compatible :meth:`execute` API below.
        """
        tool = self.get(name)
        if tool is None:
            return ToolResult(
                success=False,
                error=f"Tool '{name}' is not recognized or not registered.",
                output="",
                metadata={"tool_name": name},
            )

        try:
            validated = tool.args_schema.model_validate(args or {})
            dumped_args = validated.model_dump()
            if tool.parameters_schema is not None and isinstance(args, dict):
                dumped_args = {**args, **dumped_args}
        except ValidationError as error:
            detail = "; ".join(f"{item['loc']}: {item['msg']}" for item in error.errors())
            return ToolResult(
                success=False,
                error=f"Invalid arguments for tool '{name}': {_bound_error_text(detail)}",
                output="",
                metadata={"tool_name": name, "validation_error": True},
            )

        if approval_manager and tool.is_mutating():
            from contexer.safety.approval import ApprovalDecision

            confirmation = tool.confirmation(dumped_args)
            decision = approval_manager.decide(
                is_mutating=True,
                confirmation=confirmation,
            )
            if decision is ApprovalDecision.REJECTED:
                return ToolResult(
                    success=False,
                    error="Operation rejected by safety policy.",
                    output="",
                    metadata={"tool_name": name, "approval": decision.value},
                )
            if decision is ApprovalDecision.NEEDS_CONFIRMATION:
                if not await approval_manager.request_confirmation(confirmation):
                    return ToolResult(
                        success=False,
                        error="Operation was not approved.",
                        output="",
                        metadata={"tool_name": name, "approval": "rejected_by_user"},
                    )

        try:
            if inspect.iscoroutinefunction(tool.handler):
                raw_output = str(await tool.handler(**dumped_args))
            else:
                raw_output = str(tool.handler(**dumped_args))
        except Exception as error:
            return ToolResult(
                success=False,
                error=f"executing tool '{name}': {_bound_error_text(str(error))}",
                output="",
                metadata={"tool_name": name},
            )

        is_error = raw_output.startswith(("Error:", "Blocked:"))
        model_output, safety_metadata = prepare_tool_observation(
            raw_output,
            tool_name=tool.name,
            tool_kind=tool.kind.value,
            max_chars=max_output_chars,
            redact=redact_output,
            protect_from_prompt_injection=protect_observation,
        )
        return ToolResult(
            success=not is_error,
            output=model_output,
            error=raw_output if is_error else None,
            metadata={"tool_name": name, **safety_metadata},
        )

    async def execute(self, name: str, args: dict[str, Any]) -> str:
        """Compatibility string API for direct embedded use.

        The Contexer runtime uses :meth:`invoke`, which applies session safety
        and marks results as untrusted before feeding them to an LLM.
        """
        result = await self.invoke(
            name,
            args,
            approval_manager=None,
            protect_observation=False,
        )
        if result.success:
            return result.output
        if result.error and result.error.startswith("executing tool '"):
            return f"Error {result.error}"
        return result.to_model_output()
