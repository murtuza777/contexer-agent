"""Contexer's generic agent harness runtime.

This module adapts AgentForge's agent-loop and session boundaries to Contexer:
the runtime owns provider calls, typed tool execution, observations, streaming,
and safety. It intentionally does not contain Contexer's future intent,
planning, OpenCode, verification, or repair orchestration.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Optional

from contexer.config.settings import ContexerConfig
from contexer.llm.base import LLMError, LLMProvider, ToolCallRequest
from contexer.llm.factory import create_llm_provider
from contexer.llm.prompts import build_system_prompt
from contexer.runtime.events import (
    AgentEndEvent,
    AgentErrorEvent,
    AgentEvent,
    AgentEventType,
    AgentStartEvent,
    CircuitBreakerEvent,
    LoopDetectedEvent,
    MessageEndEvent,
    MessageStartEvent,
    TextCompleteEvent,
    TextDeltaEvent,
    ToolCallCompleteEvent,
    ToolCallStartEvent,
)
from contexer.safety import ApprovalManager
from contexer.state import AgentSession, ContexerSession
from contexer.tools import ToolRegistry, create_default_registry

logger = logging.getLogger(__name__)


class StallGuard:
    """Detect repeated identical actions before a tool loop runs away."""

    def __init__(self, threshold: int = 3) -> None:
        self.threshold = threshold
        self.last_signature: str | None = None
        self.consecutive_count = 0

    def check(self, name: str, args: dict[str, Any]) -> str | None:
        try:
            signature = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
        except (TypeError, ValueError):
            signature = f"{name}:{args}"
        if signature == self.last_signature:
            self.consecutive_count += 1
        else:
            self.last_signature = signature
            self.consecutive_count = 1
        if self.consecutive_count < self.threshold:
            return None
        return (
            f"\n[LOOP WARNING: Tool '{name}' has been called {self.consecutive_count} times consecutively "
            "with identical arguments. Do not repeat this call; choose an alternative tool, "
            "diagnose the issue, or provide your final response to the user.]"
        )


class AgentState(Enum):
    """Runtime lifecycle states; orchestration-specific states remain reserved."""

    IDLE = auto()
    PLANNING = auto()
    AWAITING_APPROVAL = auto()
    EXECUTING = auto()
    OBSERVING = auto()
    VERIFYING = auto()
    DIAGNOSING = auto()
    REPAIRING = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass
class AgentResult:
    """Outcome of a complete user message through the generic harness."""

    state: AgentState = AgentState.IDLE
    response: str = ""
    error: str | None = None
    tool_calls: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


ToolStartCallback = Callable[[str], Any]
ToolEndCallback = Callable[[str, bool], Any]
StreamStartCallback = Callable[[], Any]
ConfirmationCallback = Callable[[Any], Any]


class ContexerAgent:
    """AgentForge-inspired runtime harness, kept separate from Contexer Core.

    A single ``ContexerSession`` owns the conversation transcript, tool registry,
    approval policy, loop detector, circuit breaker, and workspace identity.
    """

    def __init__(
        self,
        config: ContexerConfig | None = None,
        llm: LLMProvider | None = None,
        repo_path: Path | str | None = None,
        tool_registry: ToolRegistry | None = None,
        max_tool_turns: int = 10,
        confirmation_callback: ConfirmationCallback | None = None,
    ) -> None:
        self.config = config or ContexerConfig()
        self.llm = llm or create_llm_provider(self.config)
        self.repo_path = Path(repo_path) if repo_path else Path.cwd()
        registry = tool_registry or create_default_registry(self.repo_path)
        self.session = ContexerSession(
            workspace_root=self.repo_path,
            approval_policy=self.config.approval_policy,
            approval_manager=ApprovalManager(
                self.config.approval_policy,
                workspace_root=self.repo_path,
                confirmation_callback=confirmation_callback,
            ),
            tool_registry=registry,
        )
        self.tool_registry = registry
        self.max_tool_turns = max_tool_turns
        self.state = AgentState.IDLE
        self._github_mcp_client: Any = None

    async def attach_github_mcp(self) -> Any:
        """Connect to official GitHub MCP server and register discovered tools into registry."""
        from contexer.mcp.adapter import attach_github_mcp_to_registry

        res = await attach_github_mcp_to_registry(
            registry=self.tool_registry,
            config=self.config,
            workspace_root=self.repo_path,
        )
        if res.connected and res.client:
            self._github_mcp_client = res.client
        return res

    def set_confirmation_callback(self, callback: ConfirmationCallback | None) -> None:
        """Attach the CLI's Rich approval renderer after it has been created."""
        self.session.approval_manager.confirmation_callback = callback

    def _build_user_turn(self, text: str) -> Any:
        builder = getattr(self.llm, "build_user_message", None)
        if callable(builder):
            return builder(text)
        builder = getattr(self.llm, "build_user_content", None)
        if callable(builder):
            return builder(text)
        return {"role": "user", "content": text}

    def _build_model_turn(
        self, tool_calls: list[ToolCallRequest], content: str | None = None
    ) -> Any:
        builder = getattr(self.llm, "build_assistant_tool_calls_message", None)
        if callable(builder):
            return builder(tool_calls, content)
        builder = getattr(self.llm, "build_model_tool_calls_content", None)
        if callable(builder):
            return builder(tool_calls)
        return {"role": "assistant", "content": content, "tool_calls": tool_calls}

    def _build_tool_turn(
        self, results: list[tuple[str, str, str | None]]
    ) -> Any:
        builder = getattr(self.llm, "build_tool_messages", None)
        if callable(builder):
            return builder(results)
        builder = getattr(self.llm, "build_tool_response_content", None)
        if callable(builder):
            return builder([(name, output) for name, output, _ in results])
        return [
            {
                "role": "tool",
                "name": name,
                "content": output,
                "tool_call_id": call_id or f"call_{name}_{index}",
            }
            for index, (name, output, call_id) in enumerate(results)
        ]

    def gather_repository_context(self) -> str:
        """Collect a small, prompt-safe repository overview for a new turn."""
        ignored_dirs = {
            ".git", ".venv", "venv", "node_modules", "__pycache__",
            ".pytest_cache", ".next", "build", "dist", ".idea", ".vscode",
        }
        lines = [f"Project Root: {self.repo_path.name}"]
        tree: list[str] = []
        try:
            for item in sorted(self.repo_path.iterdir()):
                if item.name in ignored_dirs or item.name.startswith("."):
                    continue
                if item.is_dir():
                    tree.append(f"  {item.name}/")
                    for child in sorted(item.iterdir())[:8]:
                        if child.name not in ignored_dirs and not child.name.startswith("."):
                            tree.append(f"    {child.name}")
                else:
                    tree.append(f"  {item.name}")
        except OSError:
            pass
        if tree:
            lines.extend(("Structure:", *tree[:30]))
        for manifest in ("pyproject.toml", "package.json", "README.md"):
            path = self.repo_path / manifest
            if path.is_file():
                try:
                    preview = path.read_text(encoding="utf-8", errors="replace")[:500].strip()
                    lines.append(f"\nManifest ({manifest} snippet):\n{preview}")
                    break
                except OSError:
                    continue
        return "\n".join(lines)

    def _start_turn(self, message: str) -> tuple[str, list[dict[str, Any]]]:
        self.session.start_turn()
        self.state = AgentState.PLANNING
        system_prompt = build_system_prompt(repository_context=self.gather_repository_context())
        tools = self.tool_registry.to_tools()
        self.session.context.add(self._build_user_turn(message))
        self.state = AgentState.EXECUTING
        return system_prompt, tools

    def _record_tool_round(
        self,
        calls: list[ToolCallRequest],
        results: list[tuple[str, str, str | None]],
        content: str | None = None,
    ) -> None:
        self.session.context.add(self._build_model_turn(calls, content))
        tool_messages = self._build_tool_turn(results)
        if isinstance(tool_messages, list):
            for message in tool_messages:
                self.session.context.add(message)
        else:
            self.session.context.add(tool_messages)

    async def run(self, message: str) -> AsyncIterator[AgentEvent]:
        """Asynchronous event generator executing the agent loop.

        Yields typed AgentEvents throughout the execution lifecycle.
        """
        run_id = self.session.session_id
        yield AgentEvent.agent_start(message, run_id=run_id)

        valid, error_message = self.llm.validate_configuration()
        if not valid:
            self.state = AgentState.FAILED
            err = error_message or "LLM configuration validation failed."
            yield AgentEvent.agent_error(err)
            yield AgentEvent.agent_end(response=err, run_id=run_id)
            return

        model_name = getattr(self.llm, "model_name", "llm_provider")
        if not self.session.circuit_breaker.can_try(model_name):
            self.state = AgentState.FAILED
            breaker_msg = f"Circuit breaker for model '{model_name}' is OPEN. Requests suspended."
            yield AgentEvent.circuit_breaker(model_name, state="open", message=breaker_msg)
            yield AgentEvent.agent_error(breaker_msg)
            yield AgentEvent.agent_end(response=breaker_msg, run_id=run_id)
            return

        system_prompt, tools = self._start_turn(message)
        self.session.loop_detector.clear()
        stall_guard = StallGuard()

        try:
            for _turn in range(self.max_tool_turns):
                if self.session.cancel_requested:
                    yield AgentEvent.text_delta("\n[Cancelled by user]")
                    yield AgentEvent.agent_end(response="[Cancelled]", run_id=run_id)
                    return

                yield AgentEvent.message_start(role="assistant")

                tool_calls: list[ToolCallRequest] = []
                text_chunks: list[str] = []

                try:
                    async for chunk in self.llm.stream(
                        prompt=self.session.context.messages(),
                        system_instruction=system_prompt,
                        tools=tools,
                    ):
                        if self.session.cancel_requested:
                            break
                        if chunk.tool_calls:
                            tool_calls.extend(chunk.tool_calls)
                        elif chunk.text:
                            text_chunks.append(chunk.text)
                            yield AgentEvent.text_delta(chunk.text)
                except LLMError as err:
                    self.session.circuit_breaker.record_failure(model_name)
                    self.state = AgentState.FAILED
                    yield AgentEvent.agent_error(str(err))
                    yield AgentEvent.agent_end(response=str(err), run_id=run_id)
                    return
                except Exception as exc:
                    self.session.circuit_breaker.record_failure(model_name)
                    self.state = AgentState.FAILED
                    err_text = f"Unexpected agent error: {exc}"
                    yield AgentEvent.agent_error(err_text)
                    yield AgentEvent.agent_end(response=err_text, run_id=run_id)
                    return

                self.session.circuit_breaker.record_success(model_name)

                if tool_calls:
                    results: list[tuple[str, str, str | None]] = []
                    for call in tool_calls:
                        if self.session.cancel_requested:
                            break

                        # Loop detection
                        self.session.loop_detector.record_action(
                            "tool_call",
                            tool_name=call.name,
                            args=call.arguments,
                        )
                        loop_warning = self.session.loop_detector.check_for_loop()
                        if loop_warning:
                            yield AgentEvent.loop_detected(loop_warning)

                        yield AgentEvent.tool_call_start(
                            call.call_id or f"call_{call.name}",
                            call.name,
                            call.arguments,
                        )

                        tool = self.tool_registry.get(call.name)
                        if tool is not None and tool.is_mutating():
                            self.state = AgentState.AWAITING_APPROVAL

                        tool_result = await self.tool_registry.invoke(
                            call.name,
                            call.arguments,
                            approval_manager=self.session.approval_manager,
                            redact_output=self.config.redact_tool_output,
                            protect_observation=self.config.protect_tool_observations,
                            max_output_chars=self.config.max_tool_output_chars,
                        )
                        self.state = AgentState.OBSERVING

                        yield AgentEvent.tool_call_complete(
                            call.call_id or f"call_{call.name}",
                            call.name,
                            tool_result,
                        )

                        output = tool_result.to_model_output()
                        stall_warning = stall_guard.check(call.name, call.arguments)
                        if stall_warning:
                            output += stall_warning
                        elif loop_warning:
                            output += f"\n[LOOP WARNING: {loop_warning}. Choose an alternative tool or provide your final response.]"

                        results.append((call.name, output, call.call_id))

                    self._record_tool_round(tool_calls, results)
                    self.session.context_manager.prune_tool_outputs()
                    self.state = AgentState.EXECUTING
                    continue

                # No tool calls: final text response
                full_text = "".join(text_chunks)
                self.session.context.add({"role": "assistant", "content": full_text})
                self.session.loop_detector.record_action("response", text=full_text)

                yield AgentEvent.text_complete(full_text)
                yield AgentEvent.message_end(content=full_text, role="assistant")
                self.state = AgentState.COMPLETED
                self.session.end_turn()
                yield AgentEvent.agent_end(response=full_text, run_id=run_id)
                return

            # Max turns reached
            self.state = AgentState.COMPLETED
            self.session.end_turn()
            max_turn_msg = "Tool execution reached maximum allowed turns."
            yield AgentEvent.agent_end(response=max_turn_msg, run_id=run_id)

        finally:
            self.session.end_turn()

    async def process_message(
        self,
        message: str,
        on_tool_start: ToolStartCallback | None = None,
        on_tool_end: ToolEndCallback | None = None,
    ) -> AgentResult:
        """Run the complete user → LLM → tools → LLM loop without streaming."""
        valid, error_message = self.llm.validate_configuration()
        if not valid:
            self.state = AgentState.FAILED
            return AgentResult(
                state=self.state,
                error=error_message,
                response=error_message or "LLM configuration validation failed.",
            )

        system_prompt, tools = self._start_turn(message)
        executed_names: list[str] = []
        stall_guard = StallGuard()
        self.session.loop_detector.clear()

        try:
            for _ in range(self.max_tool_turns):
                response = await self.llm.generate(
                    prompt=self.session.context.messages(),
                    system_instruction=system_prompt,
                    tools=tools,
                )
                if not response.tool_calls:
                    self.session.context.add({"role": "assistant", "content": response.text})
                    self.state = AgentState.COMPLETED
                    return AgentResult(
                        state=self.state,
                        response=response.text,
                        tool_calls=executed_names,
                        metadata={
                            "model": response.model,
                            "usage": response.usage,
                            "session_id": self.session.session_id,
                        },
                    )
                results: list[tuple[str, str, str | None]] = []
                for call in response.tool_calls:
                    executed_names.append(call.name)
                    if on_tool_start:
                        on_tool_start(call.name)
                    tool = self.tool_registry.get(call.name)
                    if tool is not None and tool.is_mutating():
                        self.state = AgentState.AWAITING_APPROVAL
                    tool_result = await self.tool_registry.invoke(
                        call.name,
                        call.arguments,
                        approval_manager=self.session.approval_manager,
                        redact_output=self.config.redact_tool_output,
                        protect_observation=self.config.protect_tool_observations,
                        max_output_chars=self.config.max_tool_output_chars,
                    )
                    self.state = AgentState.OBSERVING
                    output = tool_result.to_model_output()
                    warning = stall_guard.check(call.name, call.arguments)
                    if warning:
                        output += warning
                    if on_tool_end:
                        on_tool_end(call.name, tool_result.success)
                    results.append((call.name, output, call.call_id))
                self._record_tool_round(response.tool_calls, results, response.text)
                self.session.context_manager.prune_tool_outputs()
            self.state = AgentState.COMPLETED
            return AgentResult(
                state=self.state,
                response="Tool execution reached maximum allowed turns.",
                tool_calls=executed_names,
                metadata={"session_id": self.session.session_id},
            )
        except LLMError as error:
            self.state = AgentState.FAILED
            return AgentResult(
                state=self.state,
                error=str(error),
                response=str(error),
                tool_calls=executed_names,
            )
        except Exception as error:
            self.state = AgentState.FAILED
            message_text = f"Unexpected agent error: {error}"
            return AgentResult(
                state=self.state,
                error=message_text,
                response=message_text,
                tool_calls=executed_names,
            )

    async def stream_message(
        self,
        message: str,
        on_tool_start: ToolStartCallback | None = None,
        on_tool_end: ToolEndCallback | None = None,
        on_stream_start: StreamStartCallback | None = None,
    ) -> AsyncIterator[str]:
        """Stream final model text while continuing through any tool rounds."""
        has_started_stream = False
        has_tools = False

        async for event in self.run(message):
            if event.type == AgentEventType.TOOL_CALL_START:
                has_tools = True
                has_started_stream = False
                if on_tool_start:
                    on_tool_start(event.data.get("name", ""))
            elif event.type == AgentEventType.TOOL_CALL_COMPLETE:
                if on_tool_end:
                    on_tool_end(event.data.get("name", ""), event.data.get("success", False))
            elif event.type == AgentEventType.TEXT_DELTA:
                if not has_started_stream and on_stream_start:
                    on_stream_start()
                    has_started_stream = True
                yield event.data.get("content", "")
            elif event.type == AgentEventType.AGENT_ERROR:
                yield f"\n[Error: {event.data.get('error')}]"

    def interrupt(self) -> None:
        """Signal cooperative cancellation to running operations."""
        self.session.request_cancel()
        self.state = AgentState.IDLE

    def shutdown(self) -> None:
        """End this runtime session cleanly."""
        self.session.request_cancel()
        self.state = AgentState.IDLE
        if self._github_mcp_client is not None:
            try:
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._github_mcp_client.close())
                except RuntimeError:
                    asyncio.run(self._github_mcp_client.close())
            except Exception:
                pass
            self._github_mcp_client = None
