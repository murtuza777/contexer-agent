"""``run_agent``: one function that runs any Contexer agent, with hard limits.

The loop is deliberately plain: call the model, run the tools it asked for,
give the results back, repeat. It ends when the model hands in an answer that
fits the agent's output schema, or when a limit is reached. Code owns the
limits; the model cannot extend them.

The answer is handed in through a ``submit`` tool whose arguments are the
output schema, because tool calling is the one structured channel every
provider has. A model that writes the answer as JSON text instead is accepted
too.

Every model call and tool call is written to the agent's transcript in the
run folder, and what a tool returns is masked before the model sees it (see
``crew/transcript.py``).

An agent's output is its opinion. Nothing here marks anything as proven: that
is decided by replaying checks (see ``verification/``).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Optional, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ValidationError

from contexer.crew.transcript import Masker, Transcript, tracing_callbacks
from contexer.llm.chat import clean_error, describe_model, tool_calling_error
from contexer.llm.structured import parse_json_object

AgentStatus = Literal["ok", "step_limit", "timeout", "invalid_output", "model_error"]

SUBMIT_TOOL = "submit"
# How many times an answer that does not fit the schema is sent back for correction.
MAX_CORRECTIONS = 2
# A tool result longer than this is cut before it goes back to the model.
MAX_TOOL_RESULT_CHARS = 20_000


@dataclass(frozen=True)
class AgentSpec:
    """What an agent is: its instructions, the shape of its answer, and its limits."""

    name: str
    system_prompt: str
    output_schema: type[BaseModel]
    max_steps: int = 30
    timeout: float = 600.0
    max_output_tokens: int = 4096


@dataclass
class AgentResult:
    """How a run ended. ``output`` is set only when ``status`` is ``ok``."""

    status: AgentStatus
    output: Optional[BaseModel] = None
    # Model calls made.
    steps: int = 0
    tool_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    # Only when the provider reports what the calls cost (OpenRouter does); otherwise None.
    cost_usd: Optional[float] = None
    duration_seconds: float = 0.0
    error: str = ""
    # agents/<name>.jsonl in the run folder; None when there is no run folder.
    transcript: Optional[Path] = None
    messages: list[BaseMessage] = field(default_factory=list, repr=False)


Tool = BaseTool | Callable[..., Any]


async def run_agent(
    spec: AgentSpec,
    model: BaseChatModel,
    tools: Sequence[Tool],
    user_input: str,
    *,
    run_dir: Optional[Path],
    secrets: Sequence[str] = (),
) -> AgentResult:
    """Run ``spec`` on ``model`` with ``tools`` until it submits a valid answer or hits a limit.

    * ``step_limit``: ``spec.max_steps`` model calls were made without a valid answer.
    * ``timeout``: ``spec.timeout`` seconds passed.
    * ``invalid_output``: the answer still did not fit the schema after
      ``MAX_CORRECTIONS`` corrections.
    * ``model_error``: the model call failed; ``error`` says why.

    A tool that raises does not end the run: the model receives the error as
    the tool's result and decides what to do next.

    ``secrets`` are values that must not appear anywhere (a test account's
    password, say). They, and every key in the environment, are masked in the
    transcript and in tool results before the model reads them.
    """
    run = _Run(spec, model, tools, Transcript(run_dir, spec.name, Masker(secrets)))
    started = time.monotonic()
    try:
        async with asyncio.timeout(spec.timeout):
            await run.loop(user_input)
    except TimeoutError:
        run.result.status = "timeout"
        run.result.error = f"{spec.name} did not finish within {spec.timeout:g} seconds"
    result = run.result
    result.duration_seconds = time.monotonic() - started
    result.messages = run.messages
    result.transcript = run.transcript.path
    run.transcript.remask()
    run.transcript.write(
        "end",
        status=result.status,
        steps=result.steps,
        tool_calls=result.tool_calls,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        cost_usd=result.cost_usd,
        seconds=round(result.duration_seconds, 3),
        error=result.error,
        output=result.output.model_dump(mode="json") if result.output is not None else None,
    )
    return result


class _Run:
    def __init__(self, spec: AgentSpec, model: BaseChatModel, tools: Sequence[Tool], transcript: Transcript) -> None:
        self.spec = spec
        self.model = model
        self.transcript = transcript
        callbacks = tracing_callbacks()  # Langfuse, only when the user configured it
        self.config: Optional[RunnableConfig] = {"callbacks": callbacks} if callbacks else None
        self.tools: dict[str, BaseTool] = {}
        for item in tools:
            tool = _as_tool(item)
            if tool.name == SUBMIT_TOOL or tool.name in self.tools:
                raise ValueError(f"{spec.name}: the tool name '{tool.name}' is taken")
            self.tools[tool.name] = tool
        submit = StructuredTool.from_function(
            func=_never_called,
            name=SUBMIT_TOOL,
            description="Hand in your final answer. Call this exactly once, when the work is finished.",
            args_schema=spec.output_schema,
        )
        self.bound = model.bind_tools([*self.tools.values(), submit])
        self.messages: list[BaseMessage] = []
        # Until a limit or an answer says otherwise, a run that stops has run out of steps.
        self.result = AgentResult(status="step_limit")
        self.corrections = 0

    async def loop(self, user_input: str) -> None:
        spec, result = self.spec, self.result
        self.messages = [SystemMessage(_system_prompt(spec)), HumanMessage(user_input)]
        self.transcript.write(
            "start",
            model=describe_model(self.model),
            input=user_input,
            tools=[*self.tools, SUBMIT_TOOL],
            max_steps=spec.max_steps,
            timeout=spec.timeout,
            max_output_tokens=spec.max_output_tokens,
        )
        while result.steps < spec.max_steps:
            result.steps += 1
            called = time.monotonic()
            try:
                reply = await self.bound.ainvoke(
                    self.messages, config=self.config, max_tokens=spec.max_output_tokens
                )
            except Exception as exc:
                refused = tool_calling_error(exc, self.model)
                result.status = "model_error"
                result.error = str(refused) if refused else clean_error(exc)
                self.transcript.write(
                    "model", step=result.steps, seconds=_elapsed(called), error=result.error
                )
                return
            if not isinstance(reply, AIMessage):
                reply = AIMessage(content=str(getattr(reply, "content", reply)))
            self.messages.append(reply)
            self._count(reply)
            usage = reply.usage_metadata or {}
            self.transcript.write(
                "model",
                step=result.steps,
                seconds=_elapsed(called),
                tokens_in=int(usage.get("input_tokens") or 0),
                tokens_out=int(usage.get("output_tokens") or 0),
                cost_usd=reported_cost(reply),
                text=str(reply.text),
                tool_calls=[{"name": call["name"], "args": call["args"]} for call in reply.tool_calls],
            )
            if await self._handle(reply):
                return
        result.error = f"{spec.name} used all {spec.max_steps} steps without handing in an answer"

    async def _handle(self, reply: AIMessage) -> bool:
        """Act on one model reply. True when the run is over."""
        if not reply.tool_calls:
            return self._accept(_from_text(reply), on_invalid=lambda problem: HumanMessage(_correction(problem)))
        done = False
        for call in reply.tool_calls:
            call_id = call.get("id") or ""
            if done:  # an answer was already accepted; every call still needs a result
                self.messages.append(ToolMessage("Not run: the answer was already handed in.", tool_call_id=call_id))
                continue
            if call["name"] == SUBMIT_TOOL:
                done = self._accept(
                    call["args"],
                    on_invalid=lambda problem, call_id=call_id: ToolMessage(
                        _correction(problem), tool_call_id=call_id, status="error"
                    ),
                    on_valid=lambda call_id=call_id: ToolMessage("Accepted.", tool_call_id=call_id),
                )
                if self.result.status == "invalid_output":
                    return True
                continue
            self.result.tool_calls += 1
            called = time.monotonic()
            content, status = await self._call_tool(call["name"], call["args"])
            # A page may show a password or a key; the model has no use for it.
            content = self.transcript.masker.text(content)
            self.transcript.write(
                "tool",
                step=self.result.steps,
                name=call["name"],
                args=call["args"],
                status=status,
                result=content,
                seconds=_elapsed(called),
            )
            self.messages.append(ToolMessage(content, tool_call_id=call_id, name=call["name"], status=status))
        return done

    def _accept(
        self,
        candidate: Any,
        *,
        on_invalid: Callable[[str], BaseMessage],
        on_valid: Optional[Callable[[], BaseMessage]] = None,
    ) -> bool:
        """Validate an answer. True when the run is over (accepted, or out of corrections)."""
        try:
            if not isinstance(candidate, dict):
                raise ValueError(
                    f"no answer was handed in. Call the `{SUBMIT_TOOL}` tool with the answer as its arguments"
                )
            output = self.spec.output_schema.model_validate(candidate)
        except (ValidationError, ValueError) as exc:
            problem = _validation_problem(exc)
            if self.corrections >= MAX_CORRECTIONS:
                self.result.status = "invalid_output"
                self.result.error = f"{self.spec.name}'s answer did not fit the expected shape: {problem}"
                return True
            self.corrections += 1
            self.messages.append(on_invalid(problem))
            return False
        if on_valid:
            self.messages.append(on_valid())
        self.result.status = "ok"
        self.result.output = output
        return True

    async def _call_tool(self, name: str, args: dict[str, Any]) -> tuple[str, Literal["success", "error"]]:
        tool = self.tools.get(name)
        if tool is None:
            known = ", ".join([*self.tools, SUBMIT_TOOL])
            return f"Error: there is no tool named '{name}'. The tools are: {known}.", "error"
        try:
            value = await tool.ainvoke(args)
        except ValidationError as exc:  # the arguments did not fit the tool
            return f"Error: bad arguments for '{name}': {_validation_problem(exc)}", "error"
        except Exception as exc:  # the model gets the error; the run goes on
            return f"Error: {type(exc).__name__}: {clean_error(exc)}", "error"
        return _as_text(value), "success"

    def _count(self, reply: AIMessage) -> None:
        usage = reply.usage_metadata or {}
        self.result.tokens_in += int(usage.get("input_tokens") or 0)
        self.result.tokens_out += int(usage.get("output_tokens") or 0)
        cost = reported_cost(reply)
        if cost is not None:
            self.result.cost_usd = (self.result.cost_usd or 0.0) + cost


def reported_cost(reply: AIMessage) -> Optional[float]:
    """What the provider says this call cost in US dollars, when it says (OpenRouter's ``usage.cost``)."""
    metadata = reply.response_metadata or {}
    for usage in (metadata.get("token_usage"), metadata.get("usage")):
        if isinstance(usage, dict) and isinstance(usage.get("cost"), (int, float)) and not isinstance(usage["cost"], bool):
            return float(usage["cost"])
    return None


def _elapsed(since: float) -> float:
    return round(time.monotonic() - since, 3)


def _system_prompt(spec: AgentSpec) -> str:
    return (
        f"{spec.system_prompt.rstrip()}\n\n"
        f"When the work is finished, call the `{SUBMIT_TOOL}` tool once with your final answer as its arguments. "
        f"You have at most {spec.max_steps} steps; each reply you send is one step."
    )


def _from_text(reply: AIMessage) -> Any:
    """The answer as a JSON object written in the reply's text, or None."""
    text = str(reply.text)
    try:
        return parse_json_object(text)
    except ValueError:
        return None


def _correction(problem: str) -> str:
    return f"That answer was not accepted: {problem}. Fix it and call the `{SUBMIT_TOOL}` tool again."


def _validation_problem(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = []
        for error in exc.errors()[:8]:
            where = ".".join(str(p) for p in error["loc"]) or "answer"
            parts.append(f"{where}: {error['msg']}")
        return "; ".join(parts)
    return str(exc)


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + f"\n[cut: {len(text) - MAX_TOOL_RESULT_CHARS} more characters]"
    return text


def _as_tool(item: Tool) -> BaseTool:
    if isinstance(item, BaseTool):
        return item
    if inspect.iscoroutinefunction(item):
        return StructuredTool.from_function(coroutine=item)
    return StructuredTool.from_function(item)


def _never_called(**_: Any) -> str:  # the loop handles `submit` itself
    raise RuntimeError("submit is handled by run_agent")
