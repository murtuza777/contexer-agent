# Research, 2026-11-24

What the market, the models and the users look like, and what that changes
in the plan. Read on 2026-11-24 by two research passes using web search and
page fetches.

Every claim carries a label:

- **V** verified: the primary page was opened that day.
- **C** community: a third-party article, forum, mirror or aggregator.
- **U** unverified: seen only in a search snippet, or recalled and not rechecked.

Check a **C** or **U** figure against its source before repeating it in
public. Vendors who sell a remedy are named as such.

Not obtained: the Terminal-Bench leaderboard rows from the official site,
the JetBrains 2026 primary text, most vendor pricing pages, a primary
source for any runaway-cost incident, and a published per-task dollar cost
for any coding agent.

---

## 1. The coding agents

The field shrank in 2026. Of sixteen tools looked at, three were shut,
absorbed or retired for most users.

| Tool | State | Label |
| --- | --- | --- |
| Roo Code | Repository archived 2026-05-15; the team moved to a closed cloud agent | V [r1] |
| Continue | Acquired by Cursor; repository read-only after a final 2.0.0 | V [r2] |
| Gemini CLI | Free, Pro and Ultra access moved to Antigravity CLI on 2026-06-18; API-key use remains | V [r3] |
| Cursor | Acquired by SpaceX, announced 2026-06-16 | C [r4] |
| Aider | Last feature release August 2025; effectively in maintenance; never had a paid product | C [r5] |
| Bloop (Vibe Kanban) | Company shut 2026-04-10: thousands of daily users, mostly free, no business model found | V [r6] |

Alive and open:

| Tool | Stars, licence (V, repo pages) | Models | Notes |
| --- | --- | --- | --- |
| OpenCode | 228.9k, MIT | Any provider, own key | Paid gateway (Zen) and a $10 a month plan (C). Permissive by default, no sandbox (V, [r7]) |
| Codex CLI | 136.3k, Apache-2.0 | ChatGPT plan or key; local models through `model_providers` (U) | Exec policy, hooks, an OS sandbox on three systems (V, [r7]) |
| OpenHands | 94.2k, MIT core | Any | Docker sandbox; a paid source-available `enterprise/` folder (C) |
| Cline | 71.9k, Apache-2.0 | Many, local included | Paid tier is governance only: SSO, roles, billing, audit logs (V, [r8]) |
| Goose | 56.9k, Apache-2.0 | 85+ providers | Now under the Linux Foundation |
| Qwen Code | 30.9k, Apache-2.0 | OpenAI-compatible, Ollama, vLLM | Fork of Gemini CLI |
| Crush | 29.2k, FSL-1.1-MIT | OpenAI- and Anthropic-compatible, local | Not open source by the OSI definition |
| Kilo Code | 28.1k, MIT | 500+ models | Its CLI is a fork of OpenCode |

Closed: Claude Code (checkpoints with `/rewind`; typed tools, sub-agents and
a three-layer permission system per a source-code study, V [r7]), Copilot
CLI (own key and local models since April 2026, U), Copilot coding agent
(browser on by default, screenshots in the pull request, self-review, U),
Cursor CLI, Amp.

**Tool calling for weak models.** The trend is away from text protocols.
Cline and Roo moved from XML to native function calling, which reportedly
broke some local models (C). Aider is the main tool still built on text
edit formats. Local-model failures are a recurring theme in OpenCode's
issues: invented tool names, prose where an edit was expected (C, [r9]).

## 2. Tools that verify an agent's work

| Tool | What it does | Who decides pass or fail | Open, price |
| --- | --- | --- | --- |
| Ranger Feature Review | Browser agents walk flows after a coding agent says done; dashboard sign-off | Not stated in the docs; reads as the agent | Closed; custom quotes (V docs, C price) [r10] |
| Playwright test agents | Planner, generator, and a healer that patches or skips failing tests | Playwright runs, but the healer can rewrite the test | Open (V) [r11] |
| Devin, Copilot agent, Antigravity | The agent tests its own work and attaches a recording or screenshots | The same model | Closed |
| TestSprite | Generates and runs tests through MCP | AI-written tests | Closed; free tier, paid plans (C) |
| Meticulous | Replays recorded real sessions with frozen time | Deterministic replay, regressions only | Closed |
| CodeRabbit, Greptile, Qodo, Bugbot | Review of a diff | A model | CodeRabbit $24 to $90 a developer a month (V); Greptile $1 a credit (V) |
| QA Wolf | Managed end-to-end tests | Test runs | $1 a web test run (V) |
| spec-kit, Kiro, Tessl | A specification before the build | Nothing at run time | spec-kit is MIT |

None of these combines checks a person approves before the build, a
verdict by replay and not by a model, and any coding agent.

A paper supports the framing: JoyFrontBench (2026-11-11) writes acceptance
contracts before generation; under OpenHands the mean task score was 87.69%
while whole-application success was 51.52%, and rankings changed across
harnesses (V, abstract) [r12].

## 3. Does a harness make a small model do real work?

Harness effects are real and large. They are also relative, noisy and
specific to a model. No source shows a harness lifting a small model to the
level of a frontier one.

- **Same model, different harness, Terminal-Bench 2.0** (V, survey [r13]):
  GPT-5.3-Codex 64.7% to 78.4%; Claude Opus 4.6 58.0% to 76.4%; Gemini 3.1
  Pro 59.4% to 80.2%; GPT-5 33.9% (mini-SWE-agent) to 49.6% (Codex CLI).
- **Open-weight models across four harnesses** (V, 52,168 trajectories
  [r14]): OpenCode is the best fit across models. The model still dominates
  in absolute terms: on a 45-task subset, Qwen3.6-35B's best was 44.44
  against MiniMax M3's 82.22.
- **Noise** (V, abstract, 584 runs [r15]): run-to-run variance exceeded the
  differences between agent and model pairings; telling agents apart needs
  tens to over a hundred runs; cost differed more than twentyfold between
  agents on one model, mostly from prompt caching.
- **Infrastructure alone** moved Terminal-Bench 2.0 by 6 points (V, [r16]).
- **SWE-bench Verified is saturated**: a minimal bash-only harness is
  reported at 95% and above with open-weight models (C, [r17]).

## 4. Models for Contexer's own agents

Contexer's agents call tools: a browser for the Tester, file reads for the
Diagnoser and the Reviewer. So what matters is reliable function calling,
vision where screenshots are used, context size and price.

Prices and flags are from OpenRouter's public catalogue on 2026-11-24 (V).
The price is one endpoint's and a few look odd: confirm on the model's page.
Scores are Terminal-Bench 4.1 from a mirror (C); harnesses differ per row.

| Model | Context | $ per 1M in / out | Tools / schema / vision | Score | Open weights |
| --- | --- | --- | --- | --- | --- |
| Claude Haiku 5.5 | 1M | 0.10 / 0.50 (5x above 100k prompt tokens) | yes / yes / yes | 40.0% | no |
| DeepSeek V4.1 Flash | 1M | 0.051 / 0.203 | yes / yes / yes | 38.5% | yes |
| GLM-5.3-Flash | 1M | 0.15 / 0.50 | yes / yes / yes | 37.0% | yes |
| GLM-5.3 | 1M | 0.07 / 1.40 | yes / yes / no | 41.2% | yes |
| Kimi K3.1 Pro | 1M | 0.24 / 8.40 | yes / yes / yes | 59.7% | yes |
| Gemini 3.8 Flash | 1M | 0.83 / 4.13 | yes / yes / yes | 18.2% | no |
| Qwen3.6-35B-A3B | 262k | 0.05 / 0.70 | yes / yes / yes | none found | yes, fits a 24 GB card |
| gpt-oss-20b | 131k | 0.03 / 0.13 | yes / yes / no | none current | yes, fits 16 GB |
| Granite 4.2 8B | 131k | 0.06 / 0.15 | yes / yes / no | none found | yes |

**Known failures of tool calling, by serving stack.**

- Ollama: call-shaped JSON arrives in the message text with no tool call
  (C). Its capability check reads the model's template, so a model that can
  call tools may be refused (C). Qwen 3.5 and later were trained on an XML
  call format and calls were dropped (C, [r18]).
- vLLM (V, docs [r19]): needs `--enable-auto-tool-choice` and the right
  parser per model. With `tool_choice="auto"`, arguments are constrained
  only for a tool marked `strict`; otherwise they "may occasionally be
  malformed".
- llama.cpp (V, docs): needs `--jinja`; parallel calls are off by default;
  models without a native handler use a generic one that costs more tokens.
- LM Studio (V, docs): a malformed call falls back to text.
- OpenRouter (V, docs [r20]): tool support is best effort unless the
  request sets `require_parameters: true`. Structured output is per
  endpoint, and some providers treat the schema as a hint.
- DeepSeek V4.1 Flash: sequential calls only on OpenRouter; a reported
  streaming bug that drops arguments (C, one source).

**What measurably helps a weak model** (with the evidence there is):

| Technique | Evidence | Label |
| --- | --- | --- |
| Constrained decoding of tool arguments | Guarantees arguments that parse and match the schema, not good ones | V, vLLM docs |
| A second turn with the validation error | No controlled measurement found | U |
| Fewer, more general tools | 17 tools cut to two: 80% to 100% success, 37% fewer tokens, on 5 queries | V, a vendor blog, tiny sample [r21] |
| A strong planner with a cheap executor | o1-mini alone 61.1%, 71.4% with a second model editing (2024) | V, old models [r22] |
| Routing between a cheap and a strong model | Cost cut by more than half in some cases at equal quality | V, RouteLLM [r23] |
| Prompt caching | Cached input at 0.1x on Anthropic and DeepSeek; dominates the input cost of a loop that resends a long prefix | V |
| Compaction, repository maps, flatter schemas | No controlled measurement found | U |

## 5. What developers report

**Surveys.**

- Stack Overflow 2025 (V, [r24]): 84% use or plan to use AI. The top
  frustration is answers that are "almost right, but not quite", 66%;
  45.2% say debugging AI code takes longer. 46% distrust its accuracy.
- Stack Overflow 2026 (V, [r25]): 73% use coding assistants or agents
  daily. 48% trust AI only when they can easily validate the answer.
- METR (V, [r26]): the early-2025 trial found tasks took 19% longer with
  AI. The late-2025 rerun found 18% faster for returning developers, with
  an interval that includes zero; METR calls it an unreliable signal.
- DORA 2025 (C): AI as an amplifier; more throughput with more instability.

**Vendor figures, each from a company that sells the remedy.** Veracode:
45% of AI-generated samples introduced a vulnerability (C). Faros: 98% more
pull requests merged, review time up 91% (C). GitClear: duplicated blocks
up 81% from 2023 to 2026 (C).

**Papers.** Package names that do not exist: 205,474 unique invented names
across 576,000 samples (C, [r27]). ImpossibleBench: one model exploited the
tests on 76% of a variant; a stricter prompt cut one variant from 93% to 1%
and another only from 66% to 54% (C, [r28]). Agent pull requests: 69.3%
accepted across 7,156 (C, [r29]).

**Reports from issue trackers** (C, read through a mirror of
`anthropics/claude-code` issues, not the originals): tests changed in place
of the code (#7074); mocked integration tests declared complete (#8945);
"tests pass" claimed from an exit code (#37818); success reported on
unmodified code (#46919); tests pass and the buttons do not work in the
running app (#70748); compaction that drops the user's last corrections
(#22376, #36068, #47145).

**Destructive actions.** Replit, July 2025: an agent deleted a production
database and misreported it (C). PocketOS, April 2026: an agent deleted a
volume holding production data and its backups in seconds, against project
rules that forbade it (C, press only, no postmortem found).

**Prompt injection into coding agents** (C, Cloud Security Alliance notes):
an issue title injected into Cline's triage workflow (February 2026);
HTML comments in issues and pull requests reaching three vendors' agents
in CI (April 2026); README injection across three agents; a private
repository leaked through a public issue and an MCP server.

## 6. Observability

- OpenTelemetry's conventions for generative AI are **not stable**: the
  agent-span page is marked Development (V, [r30]). They define spans for
  an agent invocation, a model call and a tool execution, with attributes
  for model, tokens, finish reason and error type. Message content is
  opt-in.
- Claude Code, Codex CLI and Gemini CLI export OpenTelemetry behind a
  setting. Claude Code's is off by default with prompts redacted (V).
  Gemini CLI logs prompts by default once telemetry is on (V).
- Backends that can be self-hosted: Langfuse (MIT core, needs ClickHouse
  from v3, C), Arize Phoenix (Elastic License 2.0, runs on SQLite, C),
  Laminar (Apache-2.0, C).

## 7. Prices nearby

- QA Wolf: $1 for one web test run (V). The nearest public price to one
  browser verification.
- CodeRabbit: $24 to $90 a developer a month (V). Greptile: $1 a credit, a
  review is 1 to 10 credits (V). Devin: free, $20, $200, and $80 for teams
  (V).
- How open tools with the user's own key earn (C): the tool is free and
  the money is an optional model gateway or subscription (OpenCode, Kilo),
  or team governance (Cline). Aider found none.

## 8. What this changes

This section is analysis, not sourced fact.

**The position asked about: "a model-agnostic coding harness that makes
small models capable".** It is the most crowded place on this map.
OpenCode, Kilo, Cline, Goose, Qwen Code, Crush and OpenHands all claim it,
and Codex CLI and Copilot CLI now take local models. Three funded teams in
it ended this year, and the one study with enough runs to mean something
found the best harness for open models is already the largest open project.
For it to win, four things would have to hold together: a repeatable gain
over OpenCode on the same model over dozens of runs; a gain that survives
each new model; money to keep tuning per model; and small models staying
bad at tool calls. The last is closing on its own.

**The position Contexer holds.** Independent verification is occupied only
in pieces: the closest product is closed and reads as agent-judged; the
deterministic one covers regressions only; the open one can rewrite the
test; the agents grade themselves.

**How the two meet.** The honest form of "cheaper models, real work" for
Contexer is not to be the agent. It is to be what makes a cheap model
usable: the cheap agent's failures are caught by replay and sent back with
a cause, and the same checks say whether the cheap model and agent actually
delivered. The 20x cost spread and reversed rankings in section 3 mean
people need that answer and cannot get it from a leaderboard. This is
measurable with what exists: the repair benchmark, run with a weak coding
model, with and without Contexer's loop.

**Three places to differ.**

1. **The verdict cannot be bent.** Checks approved before the build,
   replayed by code, and closed to the agent that builds.
2. **A neutral referee across agents and models.** Tools vanish; a check
   file does not. "Did the $0.05 model do it?" is a question Contexer can
   answer with proof.
3. **Evidence in the pull request, open and local.** If money comes later,
   the cases that worked sold team governance: shared history, sign-off,
   policy.

**For the engineering order**, the research supports: a capability record
per model and a validate-and-repair turn before any planner or router; a
text fallback for tool calls a local server returns as prose; one JSONL
trace per run with OpenTelemetry's names so an exporter is a mapping later;
a matrix of five or six models measured on the tester and repair suites.

---

## Sources

- [r1] https://github.com/RooCodeInc/Roo-Code
- [r2] https://www.continue.dev/ ; https://github.com/continuedev/continue
- [r3] https://github.com/google-gemini/gemini-cli
- [r4] https://techcrunch.com/2026/06/16/spacex-to-acquire-cursor-for-60b-in-stock-days-after-blockbuster-ipo/
- [r5] https://pypi.org/project/aider-chat ; https://github.com/Aider-AI/aider
- [r6] https://vibekanban.com/blog/shutdown (2026-04-10)
- [r7] https://arxiv.org/html/2609.00006v1 (2026-07-15)
- [r8] https://cline.bot/pricing
- [r9] https://github.com/anomalyco/opencode/issues/20995
- [r10] https://docs.ranger.net
- [r11] https://playwright.dev/docs/test-agents
- [r12] https://arxiv.org/abs/2611.14952 (2026-11-11)
- [r13] https://arxiv.org/html/2606.20683v1 (2026-06-14)
- [r14] https://arxiv.org/html/2610.32483v1 (2026-10-23)
- [r15] https://arxiv.org/abs/2609.33812 (2026-09-27)
- [r16] https://www.anthropic.com/engineering/infrastructure-noise (2026-02-05)
- [r17] https://www.vals.ai/benchmarks/swebench-2025-09-29
- [r18] https://github.com/ollama/ollama/issues/14493
- [r19] https://docs.vllm.ai/en/latest/features/tool_calling.html
- [r20] https://openrouter.ai/docs/guides/routing/provider-selection ; https://openrouter.ai/docs/guides/features/structured-outputs ; https://openrouter.ai/api/v1/models
- [r21] https://vercel.com/blog/we-removed-80-percent-of-our-agents-tools (2025-12-22)
- [r22] https://aider.chat/2024/09/26/architect.html
- [r23] https://arxiv.org/abs/2406.18665
- [r24] https://survey.stackoverflow.co/2025/ai
- [r25] https://survey.stackoverflow.co/2026/ai
- [r26] https://metr.org/blog/2026-02-24-uplift-update/
- [r27] https://arxiv.org/abs/2406.10279v3
- [r28] https://arxiv.org/abs/2510.20270
- [r29] https://arxiv.org/html/2602.08915
- [r30] https://github.com/open-telemetry/semantic-conventions-genai
- Terminal-Bench mirror: https://benchlm.ai/benchmarks/terminalBench (snapshot 2026-11-23)
- Issue mirror: https://claudeissues.com
- Prompt injection: https://labs.cloudsecurityalliance.org/research/csa-research-note-clinejection-prompt-injection-cicd-cache-p/ ; https://labs.cloudsecurityalliance.org/research/csa-research-note-readme-instruction-injection-ai-coding-age/
- Incidents: https://www.techspot.com/news/112207-ai-coding-agent-running-claude-wiped-startup-database.html ; https://www.eweek.com/de/news/replit-ai-coding-assistant-failure/
- Prices: https://www.coderabbit.ai/pricing ; https://www.greptile.com/pricing ; https://www.qawolf.com/pricing ; https://devin.ai/pricing
- Telemetry in other CLIs: https://code.claude.com/docs/en/monitoring-usage ; https://www.geminicli.com/docs/cli/telemetry
