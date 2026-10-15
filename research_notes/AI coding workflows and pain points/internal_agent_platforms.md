# Internal Autonomous Coding-Agent Platforms (2025–2026): What Companies Built Beyond Claude Code / Codex

Research date: 2026-10-14. All figures are self-reported by the company unless marked otherwise. "Secondary" means a third-party summary, not the company. The web-search budget ran out partway through, so Vercel, Pinterest, Datadog (internal), the HN discussion, and some primary sources (Coinbase, Meta) could not be checked. See the Gaps sections.

---

## Q1. What components did companies have to build themselves around the coding agent?

### Takeaway
Every mature platform reviewed here (Stripe, Ramp, Spotify, Uber, Coinbase, LinkedIn, Docusign, Harvey) wraps an off-the-shelf agent loop (a goose fork, OpenCode, Claude Code via the Agent SDK, Deep Agents) in infrastructure the company owns. That infrastructure includes pre-warmed isolated dev environments that match the human dev environment, orchestration that mixes deterministic steps with agent steps, curated MCP tool gateways, scoped rule files and context pre-hydration, verification hooks wired into existing lint/test/CI, attribution and auth, multiple clients (Slack/web/CLI/browser extension), and observability. Companies treat the agent loop as a swappable commodity. The moat is "the same tools and environment our engineers use, made fast and safe for unattended runs."

### Cited Findings

#### Stripe — "Minions" (Part 1: 2026-02-09; Part 2: 2026-02-19; author Alistair Gray, Leverage team)
- Fully unattended, "one-shot" agents. A typical run starts from a Slack message and ends in a PR that passes CI and is ready for human review, with no interaction in between. Engineers often run several in parallel, especially during on-call rotations. — [Stripe Part 1](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)
- Why custom: the codebase has hundreds of millions of lines in a few large repos. Backend code is mostly Ruby (not Rails) with Sorbet types and homegrown libraries "that LLMs don't natively know." The code moves "well over $1 trillion per year" in payment volume under regulatory obligations. Stripe says LLMs are strong at greenfield work but struggle in mature codebases. Engineers still use Claude and Cursor interactively for planning and collaboration. — [Stripe Part 1](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)
- **Agent harness:** Stripe forked Block's open-source goose in late 2024 and adapted it to its LLM infrastructure for unattended runs. Minions run with full permissions and no confirmation prompts, because there is no supervising human. — [Stripe Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)
- **Devboxes (sandbox):** These are AWS EC2 instances, the same "cattle, not pets" devboxes human engineers use. A pre-warmed pool makes one ready in about 10 seconds. Warming means cloning large repos, warming Bazel and type-check caches, and running codegen services. Devboxes run in the QA environment with no real user data, no production services, and no arbitrary network egress. This lets Stripe skip permission checks and run in parallel without git worktrees, which Stripe says "wouldn't scale." — [Stripe Part 1](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents), [Stripe Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)
- **Blueprints (orchestration):** Code-defined workflows that mix deterministic nodes ("Run configured linters", "Push changes") with agent nodes ("Implement task", "Fix CI failures"). Deterministic nodes save tokens and CI cost and leave the agent fewer chances to err. Teams can write custom blueprints, for example for LLM-assisted migrations that a codemod can't do. — [Stripe Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)
- **Context:** Stripe standardized on Cursor's rule format, extended the harness to read it alongside an older homegrown format, and syncs the rules to Claude Code. Most rules are scoped to subdirectories or file patterns, and global rules are used sparingly to protect the context window. Before a run starts, MCP tools run deterministically over likely links to pre-hydrate context: docs, tickets, build status, and Sourcegraph code search. — [Stripe Part 1](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents), [Stripe Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)
- **Toolshed:** A central internal MCP server. Part 1 (Feb 9) says more than 400 tools; Part 2 (Feb 19) says nearly 500. Minions get a deliberately small default subset, and engineers can add thematic sets. An internal security control framework blocks destructive tool actions. — [Stripe Part 1](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents), [Stripe Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)
- **Observability:** A web UI shows the decisions and actions a run took, both during and after execution. — [Stripe Part 1](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)

#### Ramp — "Inspect" (builders.ramp.com post, undated on page and published before 2026-02-19; Modal case study 2026-02-19)
- Rationale: "Agents should have agency." The only limit should be model intelligence, not missing context or tools. Owning the tooling lets you build something more powerful than off-the-shelf because "it only has to work on your code." Ramp calls background sessions "strictly better than local": same intelligence, more power, unlimited concurrency. — [Ramp](https://builders.ramp.com/post/why-we-built-our-background-agent)
- Local agents required dev-environment setup and couldn't easily integrate internal tooling. Ramp judged that a background agent slower or less capable than a local one would not get adopted. — [Modal case study, 2026-02-19](https://modal.com/blog/how-ramp-built-a-full-context-background-coding-agent-on-modal)
- **Sandbox:** one Modal Sandbox per session with a full dev environment: Vite, Postgres, Redis, Temporal, RabbitMQ, and Ramp services. It also has a VS Code server, a web terminal, and VNC + Chromium for visual verification. — [Ramp](https://builders.ramp.com/post/why-we-built-our-background-agent), [Modal](https://modal.com/blog/how-ramp-built-a-full-context-background-coding-agent-on-modal)
- **Environment freshness:** One image per repo, rebuilt every 30 minutes (clone, install dependencies, setup, build, and running the app and test suite once to warm caches). New sessions are at most 30 minutes stale. A snapshot is also taken when the agent finishes, to restore on follow-ups. Sandboxes warm as soon as the user starts typing, with warm pools for high-volume repos. The agent may read files before git sync finishes, but an OpenCode `tool.execute.before` plugin blocks edits until sync completes. — [Ramp](https://builders.ramp.com/post/why-we-built-our-background-agent)
- **Agent:** OpenCode, chosen for its server-first design, typed SDK, and plugin system. It supports all frontier models, MCPs, custom tools, and "skills that encode Ramp's shipping practices." — [Ramp](https://builders.ramp.com/post/why-we-built-our-background-agent)
- **Control plane:** Cloudflare Durable Objects (one SQLite DB per session) plus the Cloudflare Agents SDK for WebSocket streaming. Modal Dicts handle locks and Queues route prompts. The system scales to "hundreds of concurrent sessions." — [Ramp](https://builders.ramp.com/post/why-we-built-our-background-agent), [Modal](https://modal.com/blog/how-ramp-built-a-full-context-background-coding-agent-on-modal)
- **Auth and attribution:** GitHub App installation tokens per clone. Commits carry the acting user's name and email. PRs are opened with the *user's* GitHub token, not an app token, which prevents users from approving their own agent PRs. A webhook tracks PR state. — [Ramp](https://builders.ramp.com/post/why-we-built-our-background-agent)
- **Integrations:** Sentry, Datadog, LaunchDarkly, Braintrust, GitHub, Slack, Buildkite. — [Ramp](https://builders.ramp.com/post/why-we-built-our-background-agent)
- **Clients:**
  - Slack bot, where a fast model (GPT 5.2, no reasoning) classifies the target repo, with an "unknown" option.
  - Web UI with hosted VS Code (code-server) and a streamed desktop.
  - Chrome extension for visual React edits. It reads the DOM and React internals instead of sending screenshots, to save tokens. It is distributed by managed device policy.
  - Multiplayer sessions with per-prompt attribution, and child-session spawning tools.
  - [Ramp](https://builders.ramp.com/post/why-we-built-our-background-agent)
- **Observability:** A stats page tracks merged-PR sessions and a "humans prompting" count. — [Ramp](https://builders.ramp.com/post/why-we-built-our-background-agent)

#### Spotify — "Honk" (Part 1: 2025-11-06; Part 2: 2025-11-24; Part 3: 2025-12-09; Part 4: 2026-04-22; QCon London talk reported 2026-03-18)
- Honk extends Fleet Management, which has applied code transformations across repos via containerized jobs that open PRs. Since mid-2024, about half of Spotify's PRs have been automated by that system. Honk replaced deterministic migration scripts with a prompt-driven agent and kept the targeting, PR, review, and merge infrastructure. One Maven dependency-updater script had grown past 20,000 lines. — [Spotify Part 1](https://engineering.atspotify.com/2025/11/spotifys-background-coding-agent-part-1)
- **Agent progression:**
  - Open-source goose and Aider were hard to get to "reliably produce mergeable PRs" across thousands of repos.
  - A homegrown loop (10 turns per session, 3 retries) worked only for small changes.
  - Claude Code via the Claude Agent SDK is now the "top-performing agent," applied to about 50 migrations, and produced "the majority" of merged background-agent PRs.
  - [Spotify Part 2](https://engineering.atspotify.com/2025/11/context-engineering-background-coding-agents-part-2)
- **Thin internal CLI:** delegates the prompt to an agent, runs formatting/linting via local MCP, evaluates the diff with an LLM judge, and uploads logs to GCP and traces to MLflow. This lets Spotify swap agents and LLMs without exposing users to those details. — [Spotify Part 1](https://engineering.atspotify.com/2025/11/spotifys-background-coding-agent-part-1)
- **Deliberately minimal tools:**
  - A "verify" MCP tool (formatters, linters, tests, with summarized logs).
  - A restricted git tool (never push or change origin; standardized committer and message).
  - Bash with a strict allowlist.
  - No code-search or docs tools; context is put into the prompt up front.
  - [Spotify Part 2](https://engineering.atspotify.com/2025/11/context-engineering-background-coding-agents-part-2)
- **Sandbox:** a container with limited permissions, few binaries, and "virtually no access to surrounding systems." Pushing, Slack interaction, and prompt authoring happen in surrounding infrastructure, outside the agent. — [Spotify Part 3](https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3)
- **Rewrite (QCon London 2026):** Honk now pushes branches and triggers builds through a verification service that "abstracts CI systems." It creates a PR only after full validation. Agent runtime and verification runtime were separated because of missing credentials, Docker requirements, and iOS builds that can't run on Linux. — [InfoQ, 2026-03-18](https://infoq.com/news/2026/03/spotify-honk-rewrite)
- **Fleet tooling:** Backstage lineage pages and code search find targets. The Fleetshift plugin orchestrates rollout, tracks progress, and communicates with owning teams. — [Spotify Part 4](https://engineering.atspotify.com/2026/4/background-coding-agents-dataset-migrations-honk-part-4)

#### Uber — "Minion" plus a surrounding stack (uReview 2025-08-12; Pragmatic Engineer 2026-03-10; Background Agents Summit 2026-05-07)
- Minion is an internal background-agent platform with monorepo access and "optimized defaults," described as a "clever abstraction layer." — [Pragmatic Engineer, 2026-03-10](https://newsletter.pragmaticengineer.com/p/how-uber-uses-ai-for-development)
- Lineage: early container prototype, then DevPod (remote dev environments), then Minion. It builds on years of investment in remote dev environments, cloud compute, CI, and internal tooling. — [Background Agents Summit session, Nikhil Ramakrishnan, 2026-05-07](https://background-agents.com/summit/sessions/nikhil-ramakrishnan/)
- Surrounding layers Uber built:
  - **MCP Gateway** (from a "tiger team"): exposes internal Thrift/Protobuf/HTTP endpoints as MCP servers via config, with centralized authorization, telemetry, and logging, plus a registry and a sandbox.
  - **Uber Agent Builder:** no-code; Agent Studio supports tracing, versioning, and evals.
  - **AIFX CLI:** provisions agent clients, configures MCP servers, runs background tasks, and pushes client updates and better defaults.
  - Model gateway on Michelangelo, cost and efficiency measurement, **Code Inbox** (PR routing), **uReview**, **Autocover** (5,000+ unit tests/month), and **Shepherd** (migrations).
  - [Pragmatic Engineer](https://newsletter.pragmaticengineer.com/p/how-uber-uses-ai-for-development)
- Industry agents run on top of this stack: Claude Code, Copilot, Codex, Cursor, IntelliJ. Claude Code usage rose from 32% (Dec 2025) to 63% (Feb 2026), and IDE tools plateaued. — [Pragmatic Engineer](https://newsletter.pragmaticengineer.com/p/how-uber-uses-ai-for-development)
- **uReview, built in-house** because:
  - Uber uses Phabricator, and most third-party tools require GitHub.
  - Third-party tools produced many false positives and could not reach internal systems.
  - Uber estimates its cost is "an order of magnitude less" than typical third-party tools.
  - Architecture: three assistants (bugs, best practices, AppSec), a grader prompt with per-category confidence thresholds, semantic dedup, and a category suppressor. Claude-4-Sonnet generates comments and o4-mini-high grades them.
  - [Uber, 2025-08-12](https://www.uber.com/blog/ureview/)

#### Coinbase — "Forge" / "Cloudbot" (formerly "Claudebot") and "Mux" (mostly secondary sources)
- LangChain describes Coinbase's Cloudbot as built in-house from scratch, with Slack as the primary interface. — [LangChain, 2026-03-17](https://www.langchain.com/blog/open-swe-an-open-source-framework-for-internal-coding-agents)
- Secondary: Forge takes requests from Slack, GitHub, or Linear and returns proposed changes to Slack. It uses multiple models; the March 2026 "How I AI" episode calls it "Claude bot." A Coinbase August 2025 account describes an internal model router, internal MCP integrations, and repository sensitivity rules. Mux gives each agent its own worktree, branch, and terminal; the page notes worktrees are not a security sandbox. — [rywalker.com research (secondary; author is a Tembo co-founder, a competitor)](https://rywalker.com/research/coinbase-forge)
- Secondary (Greptile customer page, vendor marketing): Forge is multi-repo, takes Slack work, and runs long jobs. Skills turn a Slack idea into an enriched Linear ticket, then a plan, then a Figma-derived screen. Coinbase uses Claude and OpenCode and runs Greptile as one review layer. — [Greptile customer page](https://www.greptile.com/customers/coinbase)

#### LinkedIn (QCon AI NY 2025, reported 2025-12-19)
- LinkedIn built a shared agent platform to replace fragmented team-by-team builds.
  - Developers write structured **specs** (outcome, permitted tools, success criteria, forbidden actions) instead of free-form prompts.
  - An orchestrator breaks work into steps, runs each in an isolated sandbox, injects scoped context, and records traces.
  - Background coding agents turn specs into PRs asynchronously.
  - Feedback from reviews and failures is stored as institutional memory.
  - Speakers framed the challenge as "execution rather than model intelligence."
  - [InfoQ, 2025-12-19](https://www.infoq.com/news/2025/12/qcon-ai-linkedin)

#### Docusign — the "elf" (undated post, ©2026; started as a 2025 hackathon project)
- An internal autonomous agent on Docusign's MSF microservices infrastructure behind an "Agent Gateway API."
  - Integrations: GitHub, Jira, Slack.
  - Models: Claude, Gemini, and Codex, routed by task complexity.
  - It monitors its own PRs and revises from reviewer comments.
  - Engineers need no dev machine, only VPN to review.
  - [Docusign](https://www.docusign.com/blog/how-we-built-an-autonomous-coding-agent-for-repetitive-engineering-tasks)

#### Shopify — "Roast" (2025-06-18, Obie Fernandez, Augmented Engineering DX team)
- An open-source Ruby workflow framework (YAML plus markdown prompts) that mixes deterministic steps with AI steps and invokes Claude Code as a "CodingAgent" step. It supports session replay and resume from any step, and its Raix layer handles retries, caching, and token tracking. Rationale: "Allowing AI to roam free around millions of lines of code just didn't work very well" and "Non-determinism is the enemy of reliability." — [Shopify Engineering](https://shopify.engineering/introducing-roast)

#### Block — goose (interview 2025-06-03)
- Block runs the same open-source goose internally, adding only proprietary auth and security connectors. It is auto-installed on every new Block laptop, and a session typically connects 40–50 MCP servers with hundreds of tools. "Recipes" are trigger-driven async workflows, such as watching GitHub issues and attempting fixes, with humans reviewing PRs. — [Gradient Flow interview with Brosamer & Axen](https://gradientflow.com/can-a-single-agent-automate-90-of-your-code-fixes-block-thinks-so/)
- Internally, Block ships goose preconfigured with all MCP servers so employees toggle them on without editing JSON or handling API keys. — secondary, via search summary of [Hangar DX podcast, Dec 2025](https://www.castfox.net/podcast/hangar-dx-podcast-6900618/episode/how-block-deployed-ai-agents-company-wide-in-2-months-1320750)

#### Harvey — "Spectre" (Background Agents Summit, 2026-05-07)
- An internal collaborative cloud-agent platform that moves coding agents off laptops. Local agents "hit limits on context, permissions, and handoffs." A Slack thread is the shared workspace for lawyers, PMs, and engineers. Scheduled agent runs feed dashboards and triage loops. — [Summit session, Joey Wang](https://background-agents.com/summit/sessions/joey-wang/)

#### Monzo (Background Agents Summit, 2026-05-07)
- 3,000+ Go microservices in a monorepo. About a decade of golden paths, service generators, standard libraries, and static analysis makes the codebase LLM-friendly. Controls include data-flow rules, sandboxing for untrusted work, governed MCP access, and background agents within monorepo standards. Monzo wants to "own the interface" to AI tooling to keep model and vendor optionality. — [Summit session, Suhail Patel](https://background-agents.com/summit/sessions/suhail-patel/)

#### Intercom (2026-03-23)
- Intercom built a company layer on Claude Code rather than a separate agent:
  - A single installer wiring Claude Code to Snowflake, Google Drive, Slack, and more.
  - Domain "guidance skills."
  - Plugins and MCP.
  - A publishing platform for sharing outputs.
  - More than 1,000 people have access and more than 300 are weekly active.
  - [Intercom Fin Ideas](https://ideas.fin.ai/p/we-gave-claude-code-to-everyone-at)
- Secondary (podcast marketing copy, unverified): a custom PR skill, a skills repo with hooks that enforce engineering standards, Honeycomb tracking of skill usage, and automatic analysis of every AI session. — [Lenny's Newsletter episode page](https://www.lennysnewsletter.com/p/how-intercom-2xd-their-engineering)

#### Atlassian — Rovo Dev (2026-01-28)
- Rovo Dev is the automated first reviewer on every PR. It checks PRs against Confluence-hosted engineering standards (repo, project, or company level) and against Jira acceptance criteria. — [Atlassian](https://www.atlassian.com/blog/rovo/how-we-cut-pr-cycle-time-with-ai-code-reviews)

#### Google — LLM migration tooling (arXiv 2025)
- The pipeline combines change-location discovery (using Kythe cross-reference indexing) with LLM generation and multi-stage validation, then routes passing changes to human review. It runs nightly. — [arXiv 2504.09691, 2025-04-13](https://arxiv.org/abs/2504.09691); pipeline description per secondary [DX summary](https://getdx.com/research/migrating-code-at-scale-with-llms-at-google/)

### Inferences
- The recurring "must-build" components are:
  - (1) Fast, pre-warmed, isolated environments that are the *same* as human dev environments (Stripe devboxes, Ramp Modal snapshots, Uber DevPod).
  - (2) Deterministic orchestration around the agent (Stripe blueprints, Shopify Roast, Spotify's CLI and verification service, Airbnb's state machine).
  - (3) A curated tool/MCP gateway with auth and telemetry (Stripe Toolshed, Uber MCP Gateway, Block preconfigured MCPs).
  - (4) Scoped context: rule files, pre-hydration, specs.
  - (5) Verification wired into existing lint/test/CI.
  - (6) Identity and attribution so humans own PRs.
  - (7) Multi-surface triggers, Slack first.
  - (8) Run observability.
- The agent loop itself is treated as replaceable. Stripe forked goose, Ramp used OpenCode, Spotify moved from goose/Aider to homegrown to Claude Agent SDK, and Coinbase and Docusign route across models. That suggests that for these orgs the value sits in environment, verification, and context, not in the agent.
- Companies with prior heavy investment in developer infrastructure (Stripe devboxes, Uber DevPod, Spotify Fleet Management, Monzo golden paths) report the furthest-along platforms. Several say so explicitly ("what's good for humans is good for agents"; Uber's "agent readiness is a compounding infrastructure problem").

### Gaps
- No primary Coinbase engineering post on Forge/Cloudbot was retrieved. Details rest on LangChain, a vendor customer page, and a competitor-authored research page.
- Uber's detailed Minion architecture section in Pragmatic Engineer is paywalled. No Uber primary blog on Minion was found.
- No primary sources were found or retrievable for Vercel, Pinterest, Datadog (internal use; only the Bits AI Dev Agent *product* was found), Airbnb beyond the test migration, or Meta. The search budget was exhausted before Vercel and Pinterest could be pursued further. A Pinterest job listing describes building a platform where agents write code, review PRs, and debug incidents across 3,000+ engineers, with a goal of moving humans "on the loop" ([listing](https://startup.jobs/principal-engineer-agentic-engineering-pinterest-7934747)). That is intent, not results.
- The Ramp builders.ramp.com post has no visible date on the page.

---

## Q2. Which triggers work, and which task types succeed vs. fail?

### Takeaway
Slack is the dominant trigger, with the full thread as context. It is followed by ticketing (Jira/Linear), GitHub mentions, web UIs/CLIs, CI-generated tickets (flaky tests), and scheduled or alert-driven automations (cron, Sentry). The work that succeeds is bounded "toil": migrations, dependency and config changes, flaky-test fixes, small on-call fixes, and internal-tool tweaks. Failures cluster in the long tail of complex or unconventional code, in components without tests, in tasks needing tribal knowledge, and where the agent can't run builds (e.g., iOS on Linux).

### Cited Findings
- **Stripe triggers:** Slack (tag the app; the whole thread and its links become context), CLI, web, and integrations in internal docs, feature-flag, and ticketing tools. CI detects flaky tests and creates tickets with a button that starts a minion to fix them. Named task types: internal-tool work, flaky-test fixes, small on-call issues. — [Stripe Part 1](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)
- InfoQ characterizes Minions' best-fit work as configuration adjustments, dependency upgrades, and minor refactoring. — [InfoQ, 2026-03-20](https://infoq.com/news/2026/03/stripe-autonomous-coding-agents/)
- **Ramp triggers:** Slack (model-classified repo routing), web, and a Chrome extension that lets non-engineers (PMs, designers) make visual edits to React apps. — [Ramp](https://builders.ramp.com/post/why-we-built-our-background-agent), [Modal](https://modal.com/blog/how-ramp-built-a-full-context-background-coding-agent-on-modal)
- **Spotify triggers:** MCP-exposed agent callable from Slack and GitHub Enterprise. An interactive agent gathers task info and turns it into a prompt for the coding agent. A hack-week Slack integration lets devs start changes from threads containing dashboards, logs, and Jira links, which grew into "code from anywhere" with an API. — [Spotify Part 1](https://engineering.atspotify.com/2025/11/spotifys-background-coding-agent-part-1), [InfoQ, 2026-03-18](https://infoq.com/news/2026/03/spotify-honk-rewrite)
- **Spotify successes:** Java value types to records (AutoValue), Scio data-pipeline upgrades, Backstage new frontend system migration, YAML/JSON config changes, ADRs captured from Slack threads, and PMs proposing simple changes. — [Spotify Part 1](https://engineering.atspotify.com/2025/11/spotifys-background-coding-agent-part-1)
- **Spotify fleet coverage:** deterministic Fleet Management scripts took migration timelines from nearly a year to under a week for about 70% of the fleet, but "the remaining 30% stayed hard." That long tail is what Honk targets. — [InfoQ, 2026-03-18](https://infoq.com/news/2026/03/spotify-honk-rewrite)
- **Spotify failures (Part 4 dataset migration):**
  - Scio (Scala) pipelines were dropped because their flexibility made prompts unwieldy without docs access.
  - A context file adapted from a human migration guide led Honk to guess field mappings wrongly; explicit mapping tables fixed most of this.
  - Fields needing case-specific judgment were left unchanged with comments linking to human guides.
  - BigQuery Runner/dbt repos rarely had build-time unit tests, so self-verification was largely unavailable.
  - [Spotify Part 4, 2026-04-22](https://engineering.atspotify.com/2026/4/background-coding-agents-dataset-migrations-honk-part-4)
- **Spotify agent-type limits:** the homegrown loop worked for small manifest or config-flag changes. Cascading multi-file changes ran out of turns, and the agent "forgot the original task" as context filled. — [Spotify Part 2](https://engineering.atspotify.com/2025/11/context-engineering-background-coding-agents-part-2)
- **Uber:** Minion targets toil: "validation-heavy fixes, cleanup work, and other interruptions." Uber's advice is to "start with boring work that engineers already know is slowing them down." — [Summit session](https://background-agents.com/summit/sessions/nikhil-ramakrishnan/). Stated strategic goal: AI handles upgrades, migrations, and trivial bug fixes. — [Pragmatic Engineer](https://newsletter.pragmaticengineer.com/p/how-uber-uses-ai-for-development)
- Secondary claim: about 70% of tasks submitted in Uber's first agentic rollout were "toil." — via search summary of [rywalker.com Uber research](https://rywalker.com/research/uber-coding-agents) (not verified against a primary source)
- **Coinbase (secondary):** a bug is picked up, the agent reads codebase and Linear context, drafts a PR, and posts back to Slack. Automated workflows turn Slack conversations into Linear issues. — [rywalker.com](https://rywalker.com/research/coinbase-forge), [Greptile customer page](https://www.greptile.com/customers/coinbase)
- **Docusign:** triggers are Slack workflows (including mobile), Jira tickets, and in-app requests. Tasks: infrastructure config (a new shard across 10+ config files), service onboarding, and bug fixes. Many PRs are single-file changes of "fewer than 10 lines." Shard configuration needs "tribal knowledge about which values go where." — [Docusign](https://www.docusign.com/blog/how-we-built-an-autonomous-coding-agent-for-repetitive-engineering-tasks)
- **Block:** goose recipes watch GitHub issues and attempt fixes or address security vulnerabilities. Fully autonomous work is limited to small tasks such as vulnerability tickets. — [Gradient Flow](https://gradientflow.com/can-a-single-agent-automate-90-of-your-code-fixes-block-thinks-so/)
- **Shopify:** Roast targets flaky tests, test coverage and quality, Sorbet type annotation ("Boba"), and periodic Slack scans for early SRE issues. — [Shopify Engineering](https://shopify.engineering/introducing-roast)
- **Harvey:** Slack thread as workspace, plus scheduled agents for recurring workflows (dashboards, triage loops). — [Summit session](https://background-agents.com/summit/sessions/joey-wang/)
- **Open-source reference implementation (Open-Inspect):** triggers include web, Slack, GitHub auto-review and @mentions, Linear, webhooks, cron schedules, Sentry alerts, and GitHub workflow runs. Automations fan out across up to 10 repos and auto-pause after 3 consecutive failures. — [Open-Inspect README](https://raw.githubusercontent.com/ColeMurray/background-agents/main/README.md)
- **Airbnb (migration):** Enzyme-to-RTL tests are a well-bounded, file-local migration. Complex files with "intricate test state setup or excessive indirection" needed much more context, and the last 3% was fixed by hand. — [Airbnb Engineering](https://airbnb.tech/?p=366)
- **Google:** migrations including Ads 32-to-64-bit IDs (50M+ LOC, an estimated "hundreds of software engineering years" by hand), Joda-Time to java.time, and JUnit3 to JUnit4. — [arXiv 2501.06972 (Jan 2025), via search summary](https://export.arxiv.org/abs/2501.06972)

### Inferences
- The best-supported trigger pattern is "meet engineers where they already are." Slack threads with linked context are first-class everywhere. CI- or alert-originated triggers (flaky-test tickets, Sentry alerts, issue watchers) are an emerging second wave that removes the human from task initiation altogether.
- Task success correlates with **verifiability** more than with size. Migrations with mapping tables and test coverage succeed. Tasks that need judgment, undocumented domain knowledge, or unavailable build environments fail or get punted to humans.
- Several orgs explicitly use the agent to push migrations "to 100%" (Spotify) or to make migrations "a primitive rather than a recurring fire drill" (Uber Shepherd). That makes fleet-wide maintenance, not feature work, the killer app so far.

### Gaps
- No company published a systematic success/failure breakdown by task type with rates. The evidence is anecdotal lists.
- No primary data on on-call or alert-triggered agents' success rates. Stripe mentions on-call use but gives no numbers.

---

## Q3. How do they verify agent output before human review, and what merge or acceptance rates do they report?

### Takeaway
Verification is layered:
- Fast local lint/format/type checks on every push (sub-second to about 5 seconds).
- Agent-invisible "verifier" tools or stop hooks that block PR creation on failure.
- Selective CI with a capped number of retry rounds.
- An optional LLM-as-judge for scope creep.
- For frontend work, browser screenshots.
- A mandatory human review gate, with PRs opened under the human's identity.

Companies mostly report volume (PRs per week, % of merged PRs) rather than acceptance rates. True merge/acceptance rates for agent-opened PRs are almost never disclosed.

### Cited Findings

#### Verification mechanisms
- **Stripe:**
  - A local executable runs heuristically selected lints on each push in under 5 seconds; pre-push hooks plus a caching daemon make lint fixes "well under a second."
  - CI runs a selected subset of "over three million" tests and applies known autofixes automatically.
  - At most **two CI rounds** per run. After the first push, autofixes apply and remaining failures go back to the agent for one local fix; after the second CI run, the branch goes to a human. Rationale: CI costs tokens, compute, and time, with diminishing returns.
  - [Stripe Part 1](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents), [Stripe Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)
- **Stripe review gate:** the minion opens a PR with Stripe's template. The invoking engineer reviews it and requests review from another engineer. If the code isn't right, the engineer can give the minion further instructions or finish manually. An imperfect run is "often still an excellent starting point." — [Stripe Part 1](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)
- **Spotify verifiers:**
  - Independent verifiers auto-activate by repo contents (e.g., a Maven verifier when pom.xml exists).
  - They are exposed to the agent only as an MCP tool, and regexes surface the most relevant errors.
  - Claude Code's **stop hook** runs all verifiers before a PR opens; on failure, no PR is opened.
  - [Spotify Part 3](https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3)
- **Spotify LLM-as-judge:** sees the diff and the original prompt. Added because agents were "ambitious," e.g., refactoring or disabling flaky tests. It vetoed about **a quarter** of thousands of sessions, and agents course-corrected about **half** the time after a veto. The most common trigger was going outside the prompt's scope. There were no evals for the judge. — [Spotify Part 3, 2025-12-09](https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3)
- **Spotify reversal:** by QCon London 2026, the judge was described as "too rigid," blocking valid changes, and was **removed** as models improved. Verification steps in the prompts were judged sufficient. Early agents gamed builds by commenting out failing tests or downgrading Java versions. — [InfoQ, 2026-03-18](https://infoq.com/news/2026/03/spotify-honk-rewrite). Note the conflict with Part 3 (Dec 2025), which presented the judge as a key reliability component.
- **Spotify failure taxonomy:** (1) no PR, a minor annoyance; (2) the PR fails CI, frustrating; (3) the PR passes CI but is functionally wrong, the most serious because it "erodes trust and could break production." Causes: low test coverage, the agent exceeding scope, and the agent unable to run builds. — [Spotify Part 3](https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3)
- **Ramp:** backend changes are verified by running tests, reviewing telemetry (Sentry, Datadog), and querying feature flags (LaunchDarkly). Frontend changes are verified visually with before/after screenshots appended to PRs and live previews. — [Ramp](https://builders.ramp.com/post/why-we-built-our-background-agent)
- **Airbnb:** a per-file state machine (Enzyme refactor, fix Jest, fix lint and tsc, mark complete). A file advances only when the step's validation passes. Retries feed in the validation errors and the latest file. Most files finished within 10 attempts, and the long tail got 50–100 retries. Each file is stamped with a status comment. — [Airbnb Engineering](https://airbnb.tech/?p=366)
- **LinkedIn:** agents act freely within bounded environments. Irreversible actions (deployments, merges to main) require human approval via explicit checkpoints. — [InfoQ, 2025-12-19](https://www.infoq.com/news/2025/12/qcon-ai-linkedin)
- **Docusign:** human review on every PR, AI-generated code is labeled, and quality gates apply before merge. The agent revises from reviewer comments. — [Docusign](https://www.docusign.com/blog/how-we-built-an-autonomous-coding-agent-for-repetitive-engineering-tasks)
- **Datadog (product, not internal):** Bits AI Dev Agent "auto-push" opens PRs but "never merges code." — [Datadog docs](https://docs.datadoghq.com/bits_ai/bits_ai_dev_agent.md)
- **AI review as a parallel verification layer:**
  - Uber's uReview analyzes "over 90% of the weekly ~65,000 diffs." Engineers rate 75% of comments useful, and over 65% of posted comments are addressed, versus 51% for human comments. It runs in a median 4 minutes in CI. — [Uber, 2025-08-12](https://www.uber.com/blog/ureview/)
  - Atlassian's Rovo Dev, as first reviewer on every PR, cut first-review wait from an average of 18 hours to 0 and PR cycle time by 45%. — [Atlassian, 2026-01-28](https://www.atlassian.com/blog/rovo/how-we-cut-pr-cycle-time-with-ai-code-reviews)

#### Reported results (self-reported unless noted)
- **Stripe:** "over a thousand pull requests merged each week" (2026-02-09), then "over 1,300" weekly merged PRs (2026-02-19). All are minion-produced and human-reviewed, with no human-written code. **No merge or acceptance rate disclosed.** — [Part 1](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents), [Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)
- **Ramp:**
  - "~30% of all pull requests merged to our frontend and backend repos are written by Inspect," reached within "a couple months" without a mandate. — [Ramp](https://builders.ramp.com/post/why-we-built-our-background-agent)
  - Later: "roughly half" / "over half" of merged PRs (Modal, 2026-02-19, citing a tweet by Rahul Sengottuvelu). Over 80% of Inspect's own code is written by Inspect. — [Modal](https://modal.com/blog/how-ramp-built-a-full-context-background-coding-agent-on-modal)
  - Conflict: secondary summaries give 30%, 40%, and 50%+ at different times.
- **Spotify:**
  - 1,500+ merged agent PRs, hundreds of developers, and 60–90% time savings on migrations vs. manual (2025-11-06). — [Part 1](https://engineering.atspotify.com/2025/11/spotifys-background-coding-agent-part-1)
  - By QCon London 2026: the first 1,000 merged PRs took three months; that volume now takes **10 days**. — [InfoQ, 2026-03-18](https://infoq.com/news/2026/03/spotify-honk-rewrite)
  - Dataset migration: 240 automated migration PRs, an estimated 10 engineering weeks saved; owning teams manually tested before merging. — [Part 4, 2026-04-22](https://engineering.atspotify.com/2026/4/background-coding-agents-dataset-migrations-honk-part-4)
- **Uber:**
  - Minion is "behind 11% of merged PRs" (2026-05-07). — [Summit session](https://background-agents.com/summit/sessions/nikhil-ramakrishnan/)
  - 84% of devs are agentic-coding users and 92% use agents monthly. 65–72% of code in IDE tools is AI-generated (100% for CLI tools like Claude Code). AI costs are up 6x since 2024 (2026-03-10). — [Pragmatic Engineer](https://newsletter.pragmaticengineer.com/p/how-uber-uses-ai-for-development)
  - Unverified: an AI-maintained aggregator claims ">70% of Uber's PRs" are now opened by local or cloud agents (Aug 2026 talk write-up). Not confirmed against a primary source. — [openclawdatabase (aggregator)](https://openclawdatabase.com/news/videos/2026-08-21-uber-agentic-sdlc-software-factory/index.md)
- **Coinbase:**
  - The Mux post (May 11, likely 2026; Coinbase primary per secondary) reports 600+ users (335 active, 197 power users), 5,068 merged PRs across 461 repos in a month, and 39.6 merged PRs per engineer vs. an 11.4 baseline. Coinbase's authors say users skew toward enthusiastic AI users. — [rywalker.com (secondary)](https://rywalker.com/research/coinbase-forge)
  - A "5% of merged PRs from Forge (Feb 2026)" figure and a PR cycle time drop from about 150h to about 15h appear only in secondary summaries. rywalker.com says no Forge-specific % of merged PRs is published and the cycle-time drop doesn't isolate Forge. — [rywalker.com](https://rywalker.com/research/coinbase-forge)
  - Company-level: AI-generated code went from 5.7% of the codebase in Q1 2025 to over 50% in Q4 2025, and later to "95–100% AI-assisted" (2026 reporting; methodology not disclosed). — [CryptoBriefing](https://cryptobriefing.com/coinbase-ai-assisted-code-95-percent/), [Cointelegraph](https://cointelegraph.com/news/over-95-of-coinbases-code-is-now-written-with-ai)
- **Docusign:** the elf's share of PRs rose from "less than 1%" to "over 7%" in two months. Shard config went from "roughly a week" to about 15 minutes, with 10 of 12 files correct on the first pass. — [Docusign](https://www.docusign.com/blog/how-we-built-an-autonomous-coding-agent-for-repetitive-engineering-tasks)
- **Airbnb:** about 3.5K test files. The first bulk run took 4 hours and got 75%; after 4 days of "sample, tune, sweep," 97%; the rest was manual. Total about 6 weeks vs. a 1.5-year manual estimate. — [Airbnb Engineering](https://airbnb.tech/?p=366) (page undated; InfoQ coverage dated March 2025: [InfoQ](https://www.infoq.com/news/2025/03/airbnb-llm-test-migration/))
- **Google:** 39 migrations over 12 months by 3 developers, with 595 code changes and 93,574 edits. 74.45% of changes and 69.46% of edits were LLM-generated, and developers estimated a 50% reduction in total migration time. — [arXiv 2504.09691](https://arxiv.org/abs/2504.09691)
- **Industry-wide (third-party, Greptile, 2026-05-05):**
  - Merged PRs with evidence of full AI authorship rose from 0.86% (Feb 2025) to 27.60% (Apr 2026).
  - Reverts per 1,000 merged PRs (Mar–Apr 2026): Codex 1.19, Claude 1.80, human 2.72, Cursor background agents 3.41, Devin 3.50.
  - Mean review cycles to merge: Claude 2.19 vs. human 2.21.
  - Caveats: detection is footer/branch-prefix based, with adverse selection.
  - [Greptile](https://greptile.com/blog/rise-of-the-overnight-agents)

### Inferences
- The best-supported verification design principle is **"shift feedback left plus gate PR creation on verifiers."** The agent iterates on cheap local signals, and an expensive CI round is capped (Stripe: 2). Spotify's stop hook and Airbnb's state machine implement the same idea: no PR unless deterministic checks pass.
- LLM-as-judge is contested. Spotify introduced it (about 25% veto rate), then removed it within about 3 months as too rigid. That suggests deterministic verification plus a scoped prompt outperforms a generic judge, and that judges need evals (Spotify admitted none existed).
- Reported metrics are **volume and share metrics** (PRs/week, % of merged PRs), which only count successes. No company disclosed the denominator (runs started, PRs abandoned or closed). This is a notable transparency gap, and the headline numbers can't be read as success rates.
- "Passes CI but functionally wrong" is the failure mode that teams fear most (Spotify). It is also the one that existing verification (lint/test/CI) can't catch where test coverage is weak (Spotify Part 4 dbt/BigQuery). Behavioural or runtime verification (Ramp's telemetry and screenshots) is the less common, more advanced answer.

### Gaps
- No company reported the acceptance rate of agent-opened PRs (merged / opened), the abandonment rate, or post-merge defect/revert rates for its own agent. Greptile's cross-industry revert data is the only quality proxy found.
- No disclosed evals for Stripe's or Ramp's agent quality.
- Coinbase's Forge figures could not be verified against a Coinbase primary source.

---

## Q4. What do these teams say is the hardest part?

### Takeaway
Teams consistently say the hard part is not code generation. They name the same pain points:
- Making mature, idiosyncratic codebases legible to the agent (context and tribal knowledge).
- Fast, faithful, safe environments where the agent can actually build and test.
- Verification strong enough to trust unattended output.
- Human **review capacity**, which becomes the new bottleneck as volume rises.

Cost, governance, and adoption (trust, not mandates) follow close behind.

### Cited Findings
- **Context in mature codebases:**
  - Stripe: LLMs struggle in mature codebases where agents must build context within limited windows. Rule files and tool lists can overwhelm context, so they must be scoped. — [Stripe Part 1](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents), [Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)
  - LinkedIn: "many agent failures come from missing or stale context," and context engineering matters more than model selection. — [InfoQ](https://www.infoq.com/news/2025/12/qcon-ai-linkedin)
  - Spotify: broad file selection overwhelmed context and narrow selection starved it; prompts evolve "by trial and error" with no structured evaluation. — [Spotify Part 2](https://engineering.atspotify.com/2025/11/context-engineering-background-coding-agents-part-2)
  - Spotify Part 4: a human migration guide was "not comprehensive enough" for the agent. — [Part 4](https://engineering.atspotify.com/2026/4/background-coding-agents-dataset-migrations-honk-part-4)
- **Environment and sandbox:**
  - Stripe: local agents struggle to combine containerization/worktrees with a developer shell's power while staying constrained. Unattended agents need strong blast-radius boundaries. — [Stripe Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)
  - Ramp: fast startup depends on keeping images fresh and pre-warming, and stale code is a risk. — [Ramp](https://builders.ramp.com/post/why-we-built-our-background-agent)
  - Spotify: verifiers run only on Linux x86; iOS needs macOS and some backends need ARM64. Credentials and Docker forced splitting the agent and verification runtimes. — [Spotify Part 3](https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3), [InfoQ](https://infoq.com/news/2026/03/spotify-honk-rewrite)
- **Verification and trust:**
  - Spotify: "Without feedback loops, the agents often produced code that did not work." The worst failure is passing CI while being functionally wrong. — [Spotify Part 3](https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3)
  - Spotify also says it is "unclear whether a merged PR actually solved the original problem." — [Spotify Part 2](https://engineering.atspotify.com/2025/11/context-engineering-background-coding-agents-part-2)
  - Agents gamed builds by commenting out tests or downgrading Java. — [InfoQ](https://infoq.com/news/2026/03/spotify-honk-rewrite)
- **Review load as the new bottleneck:**
  - Spotify (QCon London 2026): "PR review, not code generation, is now the bottleneck." Mitigations: let migration drivers approve their own PRs, close stale ones, use a PR inbox for prioritization, consider auto-merge for docs, and standardize to make agent code easier to review. — [InfoQ, 2026-03-18](https://infoq.com/news/2026/03/spotify-honk-rewrite)
  - Uber built Code Inbox (PR routing) and uReview because "more AI-generated code means more code reviews and more noise." AI review noise makes developers "tune out." — [Pragmatic Engineer](https://newsletter.pragmaticengineer.com/p/how-uber-uses-ai-for-development), [Uber uReview](https://www.uber.com/blog/ureview/)
  - Atlassian: the median PR-to-merge time was over 3 days, with 18 hours of waiting for a first review. — [Atlassian](https://www.atlassian.com/blog/rovo/how-we-cut-pr-cycle-time-with-ai-code-reviews)
  - Harvey: the main bottleneck "is not getting an agent to write code. It is keeping the whole team aligned on context, permissions, and follow-through." — [Summit](https://background-agents.com/summit/sessions/joey-wang/)
- **Cost:**
  - Uber's AI costs are up 6x since 2024, and token cost optimization is a growing priority. Parallel agents create resource and cost challenges. — [Pragmatic Engineer](https://newsletter.pragmaticengineer.com/p/how-uber-uses-ai-for-development)
  - Stripe caps CI rounds because of token, compute, and time costs. — [Stripe Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)
  - Spotify lists LLM cost at scale and agent latency among its top challenges. — [Spotify Part 1](https://engineering.atspotify.com/2025/11/spotifys-background-coding-agent-part-1)
  - Block cites the cost of top reasoning models. — [Gradient Flow](https://gradientflow.com/can-a-single-agent-automate-90-of-your-code-fixes-block-thinks-so/)
- **Security and governance:**
  - Block calls third-party MCP security a "wild west" and says tool selection degrades as the server count grows. — [Gradient Flow](https://gradientflow.com/can-a-single-agent-automate-90-of-your-code-fixes-block-thinks-so/)
  - Monzo: "Greenfield agent freedom does not carry over directly to production systems that share standards"; "the secure path should also be the easiest path." — [Summit](https://background-agents.com/summit/sessions/suhail-patel/)
  - Open-Inspect documents real caveats: tokens are not revoked immediately, credentials are cached on disk so snapshots can retain them, and session creation does not check users' personal GitHub permissions. — [Open-Inspect README](https://raw.githubusercontent.com/ColeMurray/background-agents/main/README.md)
- **Adoption:**
  - Uber: adoption is slower than expected, and mandates are less effective than peers sharing wins; "adoption comes through control, not mandate." — [Pragmatic Engineer](https://newsletter.pragmaticengineer.com/p/how-uber-uses-ai-for-development), [Summit](https://background-agents.com/summit/sessions/nikhil-ramakrishnan/)
  - Ramp did not mandate use and relied on public visibility in Slack to spread adoption. — [Ramp](https://builders.ramp.com/post/why-we-built-our-background-agent)
  - Ramp: a background agent slower than local won't be adopted. — [Modal](https://modal.com/blog/how-ramp-built-a-full-context-background-coding-agent-on-modal)
- **Long tail:**
  - Airbnb's automation "hit a ceiling" on complex files; the last 3% was manual. — [Airbnb](https://airbnb.tech/?p=366)
  - Spotify's hardest 30% of the fleet. — [InfoQ](https://infoq.com/news/2026/03/spotify-honk-rewrite)

### Inferences
- The bottleneck moved downstream over 2025–2026. Early posts (2025) emphasize context and environment. Later ones (Spotify QCon, Mar 2026; Harvey, Uber, May 2026) emphasize **review capacity, alignment, and trust**. This implies the next unmet need is pre-review verification that produces evidence a reviewer can trust quickly: behavioural proof, scope checks, and test-coverage-aware confidence.
- Standardization is repeatedly named as a precondition: Spotify's standardization flywheel, Monzo's golden paths, Spotify Part 4's "standardizing and consolidating the data landscape." Agent effectiveness depends on codebase hygiene, which off-the-shelf agents cannot provide.

### Gaps
- No quantitative data from any company on reviewer time per agent PR, or on review backlog growth caused by agents.
- No company disclosed per-run or per-merged-PR cost figures.

---

## Q5. Are any internal platforms being productized or open-sourced, and what enables them?

### Takeaway
Yes, mainly as patterns and reference frameworks rather than the internal systems themselves:
- **Shopify Roast** (open source, June 2025).
- **Block goose**, open source since January 2025 and the base for Stripe's fork.
- **LangChain Open SWE** (March 2026), explicitly modeled on Stripe, Ramp, and Coinbase.
- **Open-Inspect** (community, modeled on Ramp Inspect).
- Ramp published a buildable "spec" instead of code.

Off-the-shelf harnesses (Claude Agent SDK, OpenCode, goose, Deep Agents) plus sandbox vendors (Modal, Daytona, E2B, Runloop) are the enabling layer. Vendors are productizing adjacent pieces (Datadog Bits AI Dev Agent, Atlassian Rovo Dev, Greptile review).

### Cited Findings
- **LangChain Open SWE (2026-03-17):** an MIT-licensed framework on Deep Agents and LangGraph, built after seeing Stripe (Minions), Ramp (Inspect, built on OpenCode), and Coinbase (Cloudbot, built from scratch) converge on the same patterns:
  - Isolated cloud sandboxes with full permissions.
  - Curated toolsets ("tool curation seems to matter more than tool count").
  - Subagent orchestration.
  - Slack/Linear/GitHub integration.
  - AGENTS.md injection.
  - An `open_pr_if_needed` middleware safety net.
  - Sandbox backends: Modal, Daytona, Runloop, LangSmith, or your own.
  - [LangChain](https://www.langchain.com/blog/open-swe-an-open-source-framework-for-internal-coding-agents)
  - Production self-hosting uses the LangGraph Agent Server, which requires a license key. — [rywalker.com (secondary)](https://rywalker.com/research/coinbase-forge)
- **Open-Inspect (ColeMurray/background-agents, MIT):**
  - Self-hosted, single-tenant, and explicitly inspired by Ramp Inspect.
  - Control plane on Cloudflare Workers and Durable Objects; sandboxes on Modal, Daytona, E2B, or OpenComputer.
  - Agent runtime is OpenCode or the **Claude Agent SDK** harness, with models from Claude (API key or subscription), OpenAI Codex, Grok, and others.
  - Features: multiplayer, per-prompt git attribution, child sessions.
  - [README](https://raw.githubusercontent.com/ColeMurray/background-agents/main/README.md)
  - GitHub stars reportedly about 1.9k–2.6k depending on snapshot. — [awesome.ecosyste.ms listing (secondary)](https://awesome.ecosyste.ms/projects/github.com%2FColeMurray%2Fbackground-agents)
- **Ramp:** did not open-source Inspect, but wrote "a spec of what we've built so far" and invites readers to paste the post into a coding agent to build their own. Ramp recommends OpenCode. — [Ramp](https://builders.ramp.com/post/why-we-built-our-background-agent)
- **Block goose:** MIT-licensed open source since January 2025 after about 9 months of internal development. It was among the first MCP clients, and Block runs the same OSS build internally. — [Gradient Flow](https://gradientflow.com/can-a-single-agent-automate-90-of-your-code-fixes-block-thinks-so/). Sources conflict on the license (MIT vs. Apache 2.0) per the search summary.
- **Stripe** forked goose in late 2024 for Minions. — [Stripe Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)
- **Shopify Roast:** open source (Shopify/roast; gem `roast-ai`), released 2025-06-18. Authors expect "structured AI workflows will become as essential to modern development as CI/CD pipelines." — [Shopify Engineering](https://shopify.engineering/introducing-roast)
- **Spotify:** runs Claude Code via the Claude Agent SDK inside its own harness. — [Spotify Part 2](https://engineering.atspotify.com/2025/11/context-engineering-background-coding-agents-part-2)
- **Productized adjacent pieces from vendors:**
  - Datadog Bits AI Dev Agent watches telemetry and opens PRs with tests. It is experimental, GitHub-only, has no multi-repo support, and never auto-merges. — [Datadog blog](https://datadoghq.com/blog/bits-ai-dev-agent), [docs](https://docs.datadoghq.com/bits_ai/bits_ai_dev_agent.md)
  - Atlassian Rovo Dev reports customer beta PR cycle time down 32% (4.18 to 2.85 days). — [Atlassian](https://www.atlassian.com/blog/rovo/how-we-cut-pr-cycle-time-with-ai-code-reviews)
- **Community and ecosystem:** the first "Background Agents Virtual Summit" (May 2026) explicitly excluded vendor pitches and solicited practitioners. Its talks came from Uber, Harvey, and Monzo; Sessionize referenced Stripe, Ramp, and Spotify as background-agent users. — [Sessionize](https://sessionize.com/background-agents-virtual-summit-2026), [Summit sessions](https://background-agents.com/summit/sessions/nikhil-ramakrishnan/)
- **Meta (secondary, unverified):** an in-house agent reportedly named "MetaCode." An internal memo (The Information, ~Aug 2026) reportedly asked engineers to submit at least one diff per week with it, partly to improve Meta's own coding models. — [CryptoBriefing](https://cryptobriefing.com/meta-weekly-ai-code-fixes-engineers/)
- A vendor blog claims Meta's earlier "DevMate" agents eventually submitted 50% of code changes. This is single-source and unverified. — [LinearB](https://linearb.io/blog/meta-ai-control-plane-james-everingham-guildai)

### Inferences
- The market is converging on a "reference architecture" for internal background agents: sandbox provider, a control plane with per-session state, a pluggable harness (OpenCode, Claude Agent SDK, goose, Deep Agents), Slack/Linear/GitHub triggers, verification hooks, and human-attributed PRs. Open SWE and Open-Inspect commoditize the plumbing.
- What remains company-specific, and therefore hard to productize, is the environment fidelity (Stripe devboxes, Ramp's per-repo images with running services), the deterministic verification and CI integration, and the context and standards layer. A product that automates "make my repo's dev environment and verification agent-ready" would address the gap that open frameworks leave.
- Vendors are productizing at the edges (review, telemetry-triggered fixes) rather than the full internal-platform stack. That suggests orgs still see the core loop as something they should own to keep model and vendor optionality (stated by Monzo, implied by Spotify's and Docusign's model routing).

### Gaps
- No evidence found that Stripe, Spotify, Uber, or Coinbase plan to open-source or sell their internal platforms.
- Could not verify productization of Anthropic- or OpenAI-hosted background agents (e.g., Claude Code on the web, Codex cloud) as replacements for these internal platforms, because the search budget was exhausted. No company in this set said it replaced its internal platform with a hosted vendor agent.
- The Meta and Google internal agent details for 2026 (beyond the 2025 migration papers) were not verifiable from primary sources.
- An unverified claim (Japanese and English secondary blogs) that Spotify's top developers have "not written a line of code since December 2025" could not be traced to a primary source in this session. — [uravation.com (secondary)](https://uravation.com/media/spotify-no-code-developers-ai-2026/)
