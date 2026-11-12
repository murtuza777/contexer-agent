# Phase 0: Foundations

Goal: everything an agent needs to run, be tested without a model, and be
measured. No agent ships in this phase. See [architecture.md](architecture.md).

Phase is done when: all five tickets pass, the existing test suite is green,
and `contexer bench --suite tester` runs end to end with a stub agent.

---

## T0.1 Architecture record and doc corrections

**Goal.** One current source of truth; old plans clearly marked.

**Scope.**
- `docs/agentic/` (this folder) linked from both READMEs.
- A "superseded by docs/agentic" note at the top of each file in
  `docs/multi-agent/`.
- Fix known errors: "509 tests" in `multi-agent/build-plan.md` and
  `langgraph-port.md`; PyPI status stated the same way in `README.md`,
  `docs/try-it.md`, `CHANGELOG.md`, `multi-agent/brd.md`; the stale package
  docstring in `src/contexer/__init__.py`; stale REPL and `workflow/loop.py`
  mentions in `docs/roadmap.md`.

**Acceptance.**
- No doc claims a test count that differs from `pytest --collect-only`.
- No doc mentions the interactive shell as existing.
- The link checker reports 0 broken links.

**Verify.** Run the link checker and grep for `509`, `REPL`, `workflow/loop`.

---

## T0.2 Chat models with tool calling

**Goal.** Any provider in our catalog can drive a tool-using agent.

**Scope.**
- Add `langgraph`, `langchain-core`, `langchain-openai`, `langchain-anthropic`
  with pinned versions.
- `src/contexer/llm/chat.py`: `chat_model(provider, model) -> BaseChatModel`,
  built from `llm/catalog.py` and the same key and precedence rules as
  `llm/factory.py`. OpenAI-compatible providers go through one class with a
  base URL; Anthropic uses its own.
- `supports_tools(provider, model)` probe, used by `contexer doctor`.

**Out of scope.** Removing the existing `LLMProvider` classes (the classic
engine still uses them).

**Acceptance.**
- A unit test builds a model for every catalog provider without a network call.
- A live check (skipped without a key) makes one tool call and reads the
  result on Anthropic, OpenAI and one OpenRouter model.
- A model that cannot call tools produces a clear error naming the model.

**Verify.** `pytest tests/test_llm_chat.py`; the live check with a paid key.

---

## T0.3 `run_agent`

**Goal.** One function runs any Contexer agent with hard limits.

**Scope.** `src/contexer/crew/base.py`:

```python
async def run_agent(spec: AgentSpec, model, tools, user_input, *, run_dir) -> AgentResult
```

- `AgentSpec`: name, system prompt, output schema (pydantic), max steps,
  timeout, max output tokens.
- Loop: model call → tool calls → results → repeat, until the model returns
  the output schema or a limit is reached.
- Invalid output is returned to the model for at most 2 corrections.
- `AgentResult`: output, status (`ok`, `step_limit`, `timeout`,
  `invalid_output`, `model_error`), steps, tokens in and out, cost when the
  provider reports prices.
- `tests/fakes.py`: a scripted chat model that returns queued replies.

**Acceptance.**
- Tests cover: success, step limit, timeout, invalid-then-valid output, a tool
  that raises, a model error.
- A tool exception reaches the model as an error result; it does not end the run.
- No test needs a network or a key.

**Verify.** `pytest tests/test_crew_base.py`.

---

## T0.4 Transcripts and optional tracing

**Goal.** Every agent step can be inspected after a run.

**Scope.**
- `agents/<name>.jsonl` in the run folder: one line per model call and tool
  call, with timing and token counts.
- Secrets masked using the existing redaction in `verification/checks.py`.
- Langfuse callback enabled only when `LANGFUSE_*` variables are set; the
  package is an optional extra.

**Acceptance.**
- A test run with a secret in a tool result shows the masked value in the
  transcript.
- With no Langfuse variables, nothing is imported and nothing leaves the machine.

**Verify.** `pytest tests/test_transcripts.py`.

---

## T0.5 Tester benchmark

**Goal.** A number for "does the Tester find real bugs" before the Tester exists.

**Scope.**
- `contexer bench --suite tester`: for each fixture app and each seeded bug,
  give the agent the app's goal text (not the contract), run it, replay its
  findings.
- Metrics: bugs found and confirmed; confirmed false alarms on the clean app
  and the benign variants; unconfirmed findings; steps and cost per app.
- A stub agent (returns no findings) so the suite runs without a model.
- Results written next to `bench/RESULTS.md`.

**Acceptance.**
- With the stub agent the suite completes and reports 0 found, 0 false alarms.
- The existing suite (`contexer bench`) is unchanged and still passes.

**Verify.** `contexer bench --suite tester --agent stub`.
