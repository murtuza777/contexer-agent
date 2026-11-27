"""``run_agent``: one function that runs any Contexer agent, with hard limits.

The loop is deliberately plain: call the model, run the tools it asked for,
give the results back, repeat. It ends when the model hands in an answer that
fits the agent's output schema, or when a limit is reached. Code owns the
limits; the model cannot extend them.

The answer is handed in through a ``submit`` tool whose arguments are the
output schema, because tool calling is the one structured channel every
provider has. A model that writes the answer as JSON text instead is accepted
too, but only when the text is the answer: JSON with none of the answer's
fields, or a tool call written out as text, is sent back.

One exception to that last part: some local servers hand a model's tool call
back as the reply's text. On a model nothing vouches for (its record does not
say, from a catalogue or a measurement, that it calls tools natively), a reply
whose text is exactly one call of one of the agent's own tools is run as that
call and counted (``text_fallback_calls``). ``submit`` is never taken this way,
and neither is a reply that carries the marker of text from the app.

A mistake in a reply (an answer that does not fit, a tool call whose arguments
are not JSON, talk where a call was expected) is answered with a correction.
``MAX_CORRECTIONS`` of them in a row are allowed; a reply without a mistake
starts the count again.

A tool call is checked against the tool's schema before the tool runs. One
that does not fit gets the problem and the required fields as its result, and
the call that then runs is counted as repaired.

When the conversation nears the model's context window, the content of old
tool results (page snapshots, mostly) is replaced by a one-line note. See
``_drop_old_results`` for what is kept.

Every model call and tool call is written to the agent's transcript in the
run folder. The task an agent is given and what a tool returns are masked
before the model sees them (see ``crew/transcript.py``).

An agent's output is its opinion. Nothing here marks anything as proven: that
is decided by replaying checks (see ``verification/``).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ValidationError

from contexer.crew.budget import Budget
from contexer.crew.transcript import Masker, Trace, Transcript, tracing_callbacks
from contexer.crew.untrusted import UNTRUSTED_RULE
from contexer.llm.capabilities import capabilities_of
from contexer.llm.catalog import PROVIDERS, is_azure
from contexer.llm.chat import clean_error, describe_model, tool_calling_error
from contexer.llm.structured import CALL_ARGUMENT_KEYS, parse_json_object, parse_printed_call

AgentStatus = Literal["ok", "step_limit", "timeout", "invalid_output", "model_error", "budget_exhausted"]

SUBMIT_TOOL = "submit"
# How many replies in a row may be sent back for correction. The next mistake ends the run.
MAX_CORRECTIONS = 2
# What a provider reports as the reason a reply ended when it hit the output limit.
_CUT_OFF = frozenset({"length", "max_tokens"})
# The marker around text from the app under test (``crew/untrusted.py``). A reply that carries one is
# repeating a page, and no call is read out of it.
_UNTRUSTED_MARKER = re.compile(r"[<\[]\s*/?\s*untrusted\b", re.IGNORECASE)
# A tool result longer than this is cut before it goes back to the model.
MAX_TOOL_RESULT_CHARS = 20_000
# Tool calls run from one reply. A model that sends hundreds gets an error for the rest.
MAX_TOOL_CALLS_PER_REPLY = 25
# The same call with the same arguments may run this many times in a row; the next one is refused.
MAX_IDENTICAL_CALLS = 3
# When the conversation passes this share of the model's context window, old tool results are dropped.
CONTEXT_SHARE = 0.6
# The window taken for a model whose record does not state one. Most models an agent is run on have at
# least this; one with less and no stated window is not protected.
ASSUMED_CONTEXT_WINDOW = 128_000
# The newest tool results that are never dropped, and the length under which a result is not worth dropping.
KEPT_RESULTS = 3
MIN_DROPPED_CHARS = 400
# Characters per token when a conversation is sized from its text. Low on purpose: page trees are dense,
# and counting too many tokens only drops a result a little early.
_CHARS_PER_TOKEN = 3


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
    output: BaseModel | None = None
    # Model calls made.
    steps: int = 0
    tool_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    # Only when the provider reports what the calls cost (OpenRouter does); otherwise None.
    cost_usd: float | None = None
    duration_seconds: float = 0.0
    error: str = ""
    # Replies that were sent back for correction, over the whole run.
    corrections: int = 0
    # Tool calls that ran without an error right after a call of the same tool was refused for its
    # arguments (not JSON, or not fitting the tool's schema).
    repaired_calls: int = 0
    # Tool calls the server returned as text that were run as calls (only on a model not known to call
    # tools natively).
    text_fallback_calls: int = 0
    # Old tool results whose content was replaced by a note because the conversation neared the model's window.
    dropped_results: int = 0
    # agents/<name>.jsonl in the run folder; None when there is no run folder.
    transcript: Path | None = None
    messages: list[BaseMessage] = field(default_factory=list, repr=False)


Tool = BaseTool | Callable[..., Any]


async def run_agent(
    spec: AgentSpec,
    model: BaseChatModel,
    tools: Sequence[Tool],
    user_input: str,
    *,
    run_dir: Path | None,
    secrets: Sequence[str] = (),
    budget: Budget | None = None,
) -> AgentResult:
    """Run ``spec`` on ``model`` with ``tools`` until it submits a valid answer or hits a limit.

    * ``step_limit``: ``spec.max_steps`` model calls were made without a valid answer.
    * ``timeout``: ``spec.timeout`` seconds passed.
    * ``invalid_output``: the answer still did not fit the schema after
      ``MAX_CORRECTIONS`` corrections in a row.
    * ``model_error``: the model call failed; ``error`` says why.
    * ``budget_exhausted``: the run's ``budget``, shared with its other agents, is used up.

    A tool that raises does not end the run: the model receives the error as
    the tool's result and decides what to do next.

    ``secrets`` are values that must not appear anywhere (a test account's
    password, say). They, and every key in the environment, are masked in the
    transcript, and in ``user_input`` and tool results before the model reads them.
    """
    masker = Masker(secrets)
    run = _Run(spec, model, tools, Transcript(run_dir, spec.name, masker), budget, Trace(run_dir, masker))
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
    run.trace.remask()
    run.transcript.write(
        "end",
        status=result.status,
        steps=result.steps,
        tool_calls=result.tool_calls,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        cost_usd=result.cost_usd,
        seconds=round(result.duration_seconds, 3),
        corrections=result.corrections,
        repaired_calls=result.repaired_calls,
        text_fallback_calls=result.text_fallback_calls,
        dropped_results=result.dropped_results,
        error=result.error,
        output=result.output.model_dump(mode="json") if result.output is not None else None,
    )
    return result


class _Run:
    def __init__(
        self,
        spec: AgentSpec,
        model: BaseChatModel,
        tools: Sequence[Tool],
        transcript: Transcript,
        budget: Budget | None = None,
        trace: Trace | None = None,
    ) -> None:
        self.budget = budget
        self.trace = trace or Trace(None)
        # The last tool call and how many times in a row it was made.
        self._last_call: str | None = None
        self._repeats = 0
        self.spec = spec
        self.model = model
        self.transcript = transcript
        callbacks = tracing_callbacks()  # Langfuse, only when the user configured it
        self.config: RunnableConfig | None = {"callbacks": callbacks} if callbacks else None
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
        # Corrections sent in a row; a reply without a mistake sets it back to 0.
        self.corrections = 0
        # Whether the reply being handled ended at the output limit.
        self._cut_off = False
        # Tools whose last call was refused for its arguments. The next call that runs is a repaired one.
        self._refused: set[str] = set()
        # A call written as text is run only when nothing says this model calls tools natively: on a model
        # the provider's list or a measurement vouches for, text that looks like a call is a mistake.
        record = capabilities_of(model)
        native = record.native_tools
        self._reads_text_calls = not (native.value and native.source != "assumed")
        # Tokens the conversation may hold before old tool results are dropped.
        self._room = int((record.context_window.value or ASSUMED_CONTEXT_WINDOW) * CONTEXT_SHARE)
        # What the provider counted for the last request and its reply, and how many messages that covered.
        self._counted = 0
        self._counted_to = 0

    async def loop(self, user_input: str) -> None:
        spec, result = self.spec, self.result
        # The task carries what the caller gathered from the app (a diff, a failure report, the end of a
        # log), and any of it may hold a password or a key. It is masked like a tool result is.
        user_input = self.transcript.masker.text(user_input)
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
            spent = self.budget.exhausted() if self.budget is not None else ""
            if spent:
                result.status = "budget_exhausted"
                result.error = f"{spec.name} stopped: {spent}"
                return
            result.steps += 1
            self._drop_old_results()
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
                self._trace_model(called, None, type(exc).__name__)
                return
            if not isinstance(reply, AIMessage):
                reply = AIMessage(content=str(getattr(reply, "content", reply)))
            self.messages.append(reply)
            self._count(reply)
            self._counted, self._counted_to = _counted_tokens(reply), len(self.messages)
            finish = _finish_reason(reply)
            self._cut_off = finish in _CUT_OFF
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
                invalid_tool_calls=[
                    {"name": call.get("name") or "", "error": str(call.get("error") or "")[:200]}
                    for call in reply.invalid_tool_calls
                ],
                finish_reason=finish,
            )
            self._trace_model(called, reply)
            if await self._handle(reply):
                return
        result.error = f"{spec.name} used all {spec.max_steps} steps without handing in an answer"

    def _drop_old_results(self) -> None:
        """Before a model call: when the conversation nears the model's window, old tool results become a note.

        Only the content of a long result of a call that worked is replaced, and the message stays under
        its call's id, so the request is still one a provider accepts. The last ``KEPT_RESULTS`` such
        results and the newest result of each tool (the page as it is now) are kept. The task, what the
        model itself said or called, a correction and an error are never touched; the transcript still
        has every result in full.
        """
        size = max(
            _tokens(self.messages),
            # The provider's own count where there is one: it includes the tools' schemas.
            self._counted + _tokens(self.messages[self._counted_to :]) if self._counted else 0,
        )
        if size <= self._room:
            return
        long_results = [
            (index, message)
            for index, message in enumerate(self.messages)
            if isinstance(message, ToolMessage)
            and message.status == "success"
            and len(str(message.content)) > MIN_DROPPED_CHARS
        ]
        newest = {message.name: index for index, message in long_results}
        kept = {index for index, _ in long_results[-KEPT_RESULTS:]} | set(newest.values())
        dropped = 0
        for index, message in long_results:
            if index in kept:
                continue
            note = (
                f"[This result of `{message.name}` ({len(str(message.content)):,} characters) was dropped to keep "
                "the conversation short. Call the tool again if you need it.]"
            )
            self.messages[index] = ToolMessage(
                note, tool_call_id=message.tool_call_id, name=message.name, status=message.status
            )
            dropped += 1
        if dropped:
            self.result.dropped_results += dropped
            self.transcript.write("dropped", step=self.result.steps, results=dropped, tokens=size, room=self._room)

    async def _handle(self, reply: AIMessage) -> bool:
        """Act on one model reply. True when the run is over."""
        sent = self.result.corrections
        done = await self._act(reply)
        if self.result.corrections == sent:
            self.corrections = 0  # a reply without a mistake: the next one starts with every correction left
        return done

    async def _act(self, reply: AIMessage) -> bool:
        from_text = False
        if not reply.tool_calls and not reply.invalid_tool_calls:
            called = self._text_call(reply)
            if called is None:
                return self._text(reply)
            # The conversation now holds the call the way a server that had read it would have sent it,
            # so its result can go back under an id.
            reply = self.messages[-1] = called
            from_text = True
        done = False
        ran = 0
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
            refusal = self._refuse(call, ran)
            if refusal:
                self.transcript.write("tool", step=self.result.steps, name=call["name"], args=call["args"], status="error", result=refusal, seconds=0.0)
                self._trace_tool(call["name"], "failed", 0.0)
                self.messages.append(ToolMessage(refusal, tool_call_id=call_id, name=call["name"], status="error"))
                continue
            ran += 1
            self.result.tool_calls += 1
            self.result.text_fallback_calls += from_text
            called = time.monotonic()
            name = call["name"]
            tool = self.tools.get(name)
            problem = _bad_arguments(tool, call["args"]) if tool is not None else ""
            repaired = False
            if problem:
                # Checked before the tool runs, so an error from inside a tool is never taken for this.
                self._refused.add(name)
                content, status = f"Error: bad arguments for `{name}`, so it was not run: {problem}", "error"
            else:
                mending = name in self._refused
                self._refused.discard(name)
                content, status = await self._call_tool(name, call["args"])
                repaired = mending and status == "success"
                self.result.repaired_calls += repaired
            # A page may show a password or a key; the model has no use for it.
            content = self.transcript.masker.text(content)
            self.transcript.write(
                "tool",
                step=self.result.steps,
                name=call["name"],
                args=call["args"],
                status=status,
                repaired=repaired,
                text_fallback=from_text,
                result=content,
                seconds=_elapsed(called),
            )
            # One status per call: a failure and a repair are said before where the call came from.
            outcome = "failed" if status != "success" else "repaired" if repaired else "text-fallback" if from_text else "ok"
            self._trace_tool(name, outcome, _elapsed(called))
            self.messages.append(ToolMessage(content, tool_call_id=call_id, name=call["name"], status=status))
        # A call whose arguments could not be read still needs a result under its id: the next request is
        # refused by the provider when a call in it has none.
        for call in reply.invalid_tool_calls:
            call_id = call.get("id") or ""
            name = call.get("name") or ""
            if done:
                self.messages.append(ToolMessage("Not run: the answer was already handed in.", tool_call_id=call_id))
                continue
            problem = self.transcript.masker.text(self._unreadable(name, str(call.get("error") or "")))
            self.transcript.write("tool", step=self.result.steps, name=name, args=call.get("args"), status="error", result=problem, seconds=0.0)
            self._trace_tool(name, "failed", 0.0)
            self.messages.append(ToolMessage(f"Error: {problem}", tool_call_id=call_id, name=name, status="error"))
            if name in self.tools:
                self._refused.add(name)
            if self._mistake(problem):
                return True
        return done

    def _text_call(self, reply: AIMessage) -> AIMessage | None:
        """``reply`` with the tool call its text is, when the server returned a call as text; else None.

        Only a call to one of the agent's own tools: the answer is never handed in this way. The call then
        goes through everything a native call does (the limits, the schema check, the masking).
        """
        text = str(reply.text)
        if not self._reads_text_calls or self._cut_off or _UNTRUSTED_MARKER.search(text):
            return None
        found = parse_printed_call(text)
        if found is None or found[0] not in self.tools:
            return None
        name, args = found
        return AIMessage(
            content="",
            tool_calls=[{"name": name, "args": args, "id": f"text_call_{self.result.steps}", "type": "tool_call"}],
            usage_metadata=reply.usage_metadata,
            response_metadata=reply.response_metadata,
            id=reply.id,
        )

    def _text(self, reply: AIMessage) -> bool:
        """A reply with no tool call: the answer as JSON text, or something to send back."""
        found = _from_text(reply)
        rejected = ""
        if not isinstance(found, dict):
            if self._cut_off:
                rejected = (
                    f"Your reply was cut off at the limit of {self.spec.max_output_tokens} output tokens, so it is "
                    f"incomplete and was not accepted. Send a shorter reply: call the `{SUBMIT_TOOL}` tool with a "
                    "shorter answer, or call one tool at a time."
                )
        else:
            fields = _answer_fields(self.spec.output_schema)
            shared = fields & set(found)
            called = _printed_call(found)
            if called and (not shared or called == SUBMIT_TOOL or called in self.tools):
                rejected = (
                    f"That was a tool call written as text (`{called}`), and text is not run: nothing was called. "
                    f"Call `{called}` through the tool-calling interface; do not write the call as JSON in your reply."
                )
            elif not shared:
                rejected = (
                    f"That JSON has none of the answer's fields ({', '.join(sorted(fields))}), so it was not taken "
                    f"as the answer. Call the `{SUBMIT_TOOL}` tool with the answer as its arguments."
                )
        if rejected:
            if self._mistake(rejected):
                return True
            self.messages.append(HumanMessage(rejected))
            return False
        return self._accept(found, on_invalid=lambda problem: HumanMessage(_correction(problem)))

    def _unreadable(self, name: str, error: str) -> str:
        """What the model is told about a tool call whose arguments were not JSON."""
        why = f" ({error[:200]})" if error else ""
        problem = f"the arguments of this `{name}` call were not valid JSON{why}, so it was not run."
        if self._cut_off:
            return (
                f"{problem} The reply was cut off at the limit of {self.spec.max_output_tokens} output tokens: "
                "send a shorter call."
            )
        return f"{problem} Send the call again with valid JSON arguments."

    def _mistake(self, problem: str) -> bool:
        """Count a reply that is sent back. True when the run is over: too many in a row."""
        if self.corrections >= MAX_CORRECTIONS:
            self.result.status = "invalid_output"
            self.result.error = (
                f"{self.spec.name}'s answer did not fit the expected shape after {MAX_CORRECTIONS} corrections "
                f"in a row: {problem}"
            )
            return True
        self.corrections += 1
        self.result.corrections += 1
        return False

    def _refuse(self, call: Any, ran: int) -> str:
        """Why a tool call is not run, or ''. Bounds what one reply, and one stuck model, can do."""
        if ran >= MAX_TOOL_CALLS_PER_REPLY:
            return (
                f"Error: not run. At most {MAX_TOOL_CALLS_PER_REPLY} tool calls are run from one reply; "
                "send the rest in your next reply."
            )
        try:
            signature = f"{call['name']}:{json.dumps(call['args'], sort_keys=True, default=str)}"
        except (TypeError, ValueError):
            signature = f"{call['name']}:{call['args']!r}"
        self._repeats = self._repeats + 1 if signature == self._last_call else 1
        self._last_call = signature
        if self._repeats > MAX_IDENTICAL_CALLS:
            return (
                f"Error: not run. You have made this exact call {MAX_IDENTICAL_CALLS} times in a row. "
                "Repeating it will not change the result: do something different, or hand in what you have."
            )
        return ""

    def _accept(
        self,
        candidate: Any,
        *,
        on_invalid: Callable[[str], BaseMessage],
        on_valid: Callable[[], BaseMessage] | None = None,
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
            if self._mistake(problem):
                return True
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
        except Exception as exc:  # the model gets the error; the run goes on
            return f"Error: {type(exc).__name__}: {clean_error(exc)}", "error"
        return _as_text(value), "success"

    def _trace_model(self, called: float, reply: AIMessage | None, error: str = "") -> None:
        """One model call in the run's trace: who was asked, what it used and what it cost. No text."""
        usage: dict[str, Any] = dict((reply.usage_metadata if reply is not None else None) or {})
        tokens_in, tokens_out = int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
        reported = reported_cost(reply) if reply is not None else None
        cost = reported
        if self.budget is not None and reply is not None:
            cost = self.budget.cost_of(tokens_in, tokens_out, reported)
        metadata = (reply.response_metadata if reply is not None else None) or {}
        answered = metadata.get("model_name") or metadata.get("model")
        finish = _finish_reason(reply) if reply is not None else ""
        line: dict[str, Any] = {
            "gen_ai.operation.name": "chat",
            "gen_ai.agent.name": self.spec.name,
            "gen_ai.provider.name": _provider(self.model),
            "gen_ai.request.model": _model_name(self.model),
            "gen_ai.response.model": answered if isinstance(answered, str) and answered else None,
            "gen_ai.usage.input_tokens": tokens_in,
            "gen_ai.usage.output_tokens": tokens_out,
            # None: the provider did not say. That is not the same as nothing cached.
            "gen_ai.usage.cache_read.input_tokens": (usage.get("input_token_details") or {}).get("cache_read"),
            "gen_ai.response.finish_reasons": [finish] if finish else [],
            "contexer.step": self.result.steps,
            "contexer.seconds": _elapsed(called),
            "contexer.cost_usd": cost,
            "contexer.cost_estimated": cost is not None and reported is None,
        }
        if error:
            line["error.type"] = error
        self.trace.call("model", **line)

    def _trace_tool(self, name: str, status: str, seconds: float) -> None:
        """One tool call in the run's trace: ``ok``, ``repaired``, ``text-fallback`` or ``failed``. No arguments, no result."""
        self.trace.call(
            "tool",
            **{
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.agent.name": self.spec.name,
                "gen_ai.tool.name": name,
                "contexer.tool.status": status,
                "contexer.step": self.result.steps,
                "contexer.seconds": seconds,
            },
        )

    def _count(self, reply: AIMessage) -> None:
        usage = reply.usage_metadata or {}
        self.result.tokens_in += int(usage.get("input_tokens") or 0)
        self.result.tokens_out += int(usage.get("output_tokens") or 0)
        cost = reported_cost(reply)
        if cost is not None:
            self.result.cost_usd = (self.result.cost_usd or 0.0) + cost
        if self.budget is not None:
            self.budget.spend(int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0), cost)


def reported_cost(reply: AIMessage) -> float | None:
    """What the provider says this call cost in US dollars, when it says (OpenRouter's ``usage.cost``)."""
    metadata = reply.response_metadata or {}
    for usage in (metadata.get("token_usage"), metadata.get("usage")):
        if isinstance(usage, dict) and isinstance(usage.get("cost"), (int, float)) and not isinstance(usage["cost"], bool):
            return float(usage["cost"])
    return None


def _model_name(model: Any) -> str | None:
    inner = getattr(model, "bound", model)
    name = getattr(inner, "model_name", None) or getattr(inner, "model", None)
    return name if isinstance(name, str) and name else None


def _provider(model: Any) -> str:
    """The catalog id of the provider a chat model talks to; the endpoint's host when the catalog has none."""
    inner = getattr(model, "bound", model)
    kind = str(getattr(inner, "_llm_type", "") or "")
    if kind.startswith("anthropic"):
        return "anthropic"
    base = str(getattr(inner, "openai_api_base", "") or "")
    if not base:
        return kind or type(inner).__name__
    if is_azure(base):
        return "azure"
    there = urlsplit(base)
    for spec in PROVIDERS:
        known = urlsplit(spec.base_url) if spec.base_url else None
        if known is not None and (known.hostname, known.port) == (there.hostname, there.port):
            return spec.id
    return there.hostname or kind


def _elapsed(since: float) -> float:
    return round(time.monotonic() - since, 3)


def _system_prompt(spec: AgentSpec) -> str:
    return (
        f"{spec.system_prompt.rstrip()}\n\n"
        f"{UNTRUSTED_RULE}\n\n"
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


def _finish_reason(reply: AIMessage) -> str:
    """Why the provider says the reply ended ("stop", "length", "tool_calls"...), or ''."""
    metadata = reply.response_metadata or {}
    for key in ("finish_reason", "stop_reason"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value.lower()
    return ""


def _answer_fields(schema: type[BaseModel]) -> set[str]:
    """Every name a field of the answer may be given under."""
    names: set[str] = set()
    for name, info in schema.model_fields.items():
        names.add(name)
        if isinstance(info.alias, str):
            names.add(info.alias)
    return names


def _printed_call(data: dict[str, Any]) -> str:
    """The tool's name when ``data`` is a tool call written out as text, else ''."""
    listed = data.get("tool_calls")
    if isinstance(listed, list) and listed and isinstance(listed[0], dict):
        return _printed_call(listed[0]) or "a tool"
    function = data.get("function")
    if isinstance(function, dict):
        name = function.get("name")
        return name if isinstance(name, str) and name else ""
    name = function if isinstance(function, str) else data.get("name") or data.get("tool") or data.get("tool_name")
    if isinstance(name, str) and name and any(key in data for key in CALL_ARGUMENT_KEYS):
        return name
    return ""


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


def _bad_arguments(tool: BaseTool, args: Any) -> str:
    """Why ``args`` do not fit the tool's schema, with the fields it requires named; '' when they fit."""
    schema = tool.args_schema
    if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
        return ""  # a tool described by a plain JSON schema: nothing here can check it
    try:
        schema.model_validate(args)
    except ValidationError as exc:
        required = [info.alias or name for name, info in schema.model_fields.items() if info.is_required()]
        needs = f"requires: {', '.join(required)}" if required else "has no required argument"
        return f"{_validation_problem(exc)}. `{tool.name}` {needs}. Send the call again with arguments that fit."
    return ""


def _tokens(messages: Sequence[BaseMessage]) -> int:
    """Roughly how many tokens ``messages`` are, from their text and the calls they carry."""
    chars = 0
    for message in messages:
        chars += len(str(message.content))
        if isinstance(message, AIMessage):
            chars += sum(len(call["name"]) + len(json.dumps(call["args"], default=str)) for call in message.tool_calls)
    return chars // _CHARS_PER_TOKEN


def _counted_tokens(reply: AIMessage) -> int:
    """The tokens the provider counted for the request and this reply together; 0 when it did not say."""
    usage = reply.usage_metadata or {}
    return int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)


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
