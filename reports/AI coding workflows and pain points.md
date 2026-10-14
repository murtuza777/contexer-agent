# Coding agents outrun the people who verify them

As of October 2026, professional engineers and vibe coders have both largely solved *producing* code with agents, and both are stuck on *proving* it works. In both segments the binding constraint is verification: evidence that a change does what the person asked, did not break what already worked, and is safe. Nobody independent of the agent that wrote the code supplies that evidence. Professional teams now run the middle of the loop unattended (the agent executes in a sandbox, tests itself and gets a first AI review), but humans still gate both ends, and the end that is breaking is review. On AI-heavy teams, agent PRs wait **4.6–5.3x longer for review pickup** and are accepted far less often than human PRs (vendor telemetry). Independent maintainer reviews by METR found that **roughly half of benchmark-passing agent PRs would not be merged**. Vibe coders prototype in Lovable, Bolt or Replit and move to Cursor or Claude Code when bills or bugs push them. They break on regression loops that burn credits and on access-control holes, such as the Lovable RLS flaw that exposed data in **10.3% of scanned showcase apps**. Money follows a clear pattern. Employers pay **$100–200 per engineer per month** for agents and accept a second, seat-priced line of roughly **$15–40** for review and verification. Founders pay **$25–100 a month** to build, then **$500–50,000** for audits and rescues when something breaks. Almost nobody pays for orchestration UIs; two orchestration startups shut down in early 2026. Incumbents have bundled agents, parallelism, plan mode, sandboxes, PR review and in-loop browser self-testing. Every one of those checks is run and graded by the vendor's own agent, and Anthropic's own reviewer is designed never to block a merge. The highest-ranked wedge for a small team is therefore an **independent acceptance gate**. It consists of executable, user-level checks that the authoring agent cannot edit, enforced at merge or launch, kept as a regression contract, and used to drive a bounded repair loop across Claude Code and Codex. Contexer is a real head start on that engine. It already compiles goals into checks, returns real-Chromium verdicts labelled by how they were reached, and drives repair from failed checks. It is not yet a head start on the parts buyers pay for: real app stacks, Claude Code support, persistent contracts, security proofs, and a PR or launch-gate surface.

## Most of the hard numbers come from vendors that sell the fix

The evidence base is lopsided, so this report labels its sources:

| Label | Meaning |
|---|---|
| **[IND]** | Independent research, editorially independent surveys, or a practitioner's first-hand account |
| **[DORA]** | Google's DORA program. Its methods are serious, but Google sells AI coding tools |
| **[VEN]** | A vendor whose product the finding helps sell |
| **[SELF]** | A company describing its own tool or its own internal use |
| **[2ND]** | A figure seen only in secondary coverage |

Most large-sample telemetry on review time, PR size, defects and incidents comes from companies that sell measurement, review, security or testing products: Faros, LinearB, DX, Sonar, CodeRabbit, New Relic, Veracode, GitGuardian, Escape and Qodo. Most vibe-coder statistics come from an app builder describing its own users or from a rescue agency advertising its services. The most detailed workflow accounts come from companies describing their internal platforms. Those accounts report volume (PRs merged per week, share of merged PRs) but never the denominator of runs started or PRs abandoned, so none of them is a success rate.

Independent evidence exists but is smaller. It includes:

- METR's trials and maintainer reviews
- Carnegie Mellon's difference-in-differences study of Cursor adopters
- MIT's EvilGenie reward-hacking benchmark
- academic studies covering tens of thousands of agent PRs
- the self-selected Stack Overflow and Pragmatic Engineer surveys

The conclusions below rest on findings where independent and vendor evidence point the same way; the directions are more certain than the magnitudes. Coverage also has gaps. Reddit threads could not be retrieved, so vibe-coder evidence leans on Hacker News, Product Hunt, Substack and press. Coverage of Devin, Factory, Jules and Kiro is thinner than coverage of Claude Code, Codex, Cursor and Copilot.

## Professional engineers automated the middle of the loop and moved the bottleneck to review

### A working day runs on rules files, plan mode and capped background runs

Claude Code is the professional default. Among regular agent users in the Pragmatic Engineer survey (906 respondents, median 11–15 years of experience), **71% use Claude Code, 46% Copilot and 39% Cursor**, and **70% juggle 2–4 tools** **[IND, self-selected]** ([Pragmatic Engineer](https://newsletter.pragmaticengineer.com/p/ai-tooling-2026)). Stack Overflow's 2026 survey of 30,903 developers found **66% use coding assistants or agents**; among agent users, Claude Code (66%) and Copilot (59%) lead **[IND]** ([Stack Overflow](https://survey.stackoverflow.co/2026/ai)). The typical setup is a terminal running Claude Code to drive the work, with an IDE open to review the agent's changes ([Pragmatic Engineer](https://newsletter.pragmaticengineer.com/p/ai-tooling-2026)).

The individual power-user loop is plan, execute, verify, compound. Sessions start in plan mode and switch to auto-accept once the plan is solid. A shared CLAUDE.md or AGENTS.md gains a rule every time the agent makes a mistake. That is how the Claude Code team works, per secondary summaries of Boris Cherny's thread **[2ND]** ([Slashdot](https://developers.slashdot.org/story/26/01/06/2239243/creator-of-claude-code-reveals-his-workflow)). It is also what Mitchell Hashimoto calls "harness engineering", which he says fixed most bad agent behaviour in Ghostty **[IND]** ([mitchellh.com](https://mitchellh.com/writing/my-ai-adoption-journey)). Every's "compound engineering" puts **roughly 80% of the effort into planning and review** rather than generation ([Every](https://every.to/source-code/compound-engineering-how-every-codes-with-agents)).

How formal the spec is varies by person:

- Harper Reed and Addy Osmani write spec.md, then a plan, then small tested chunks ([harper.blog](https://harper.blog/2025/02/16/my-llm-codegen-workflow-atm/); [Osmani](https://addyo.substack.com/p/my-llm-coding-workflow-going-into)).
- Peter Steinberger dropped upfront specs for one-to-two-sentence prompts plus a screenshot ([steipete.me](https://steipete.me/posts/just-talk-to-it)).
- Formal spec-driven tools (Spec Kit, Kiro, BMAD) show up mainly in greenfield work. Comparisons criticise them for "review overload", and a common rule of thumb is to skip them for anything under a few hundred lines **[2ND]** ([Particula](https://particula.tech/blog/spec-driven-development-tools-spec-kit-vs-kiro-vs-tessl)).
- Inside companies, the spec is usually a Slack thread or ticket handed to a background agent ([Stripe](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)).

Verification habits have converged on one principle: "give an agent a way to verify its work" ([mitchellh.com](https://mitchellh.com/writing/my-ai-adoption-journey)). In practice that means red/green TDD, which Simon Willison uses daily ([Willison guide](https://simonwillison.net/guides/agentic-engineering-patterns/)). It also means browser loops through chrome-devtools-mcp or Playwright ([steipete.me](https://steipete.me/posts/just-talk-to-it); [Every](https://every.to/source-code/compound-engineering-how-every-codes-with-agents)). Kent Beck reports a running fight to stop agents deleting or disabling tests so that they "pass" ([kentbeck.com](https://kentbeck.com/summaries/augmented-coding-beyond-the-vibes/)). When a run degrades, the accepted move is to discard it and restart with fresh context, not to keep patching. Geoffrey Huntley's "Ralph" loop is built on that idea ([ghuntley.com](https://ghuntley.com/ralph/)).

Running several agents in parallel is mainstream, but human attention, not compute, is the limit:

- Steinberger runs 3–8 Codex agents in one folder ([steipete.me](https://steipete.me/posts/just-talk-to-it)).
- Cherny runs five local Claude Code sessions plus 5–10 on the web **[2ND]**.
- OpenAI's own study of its staff found **28.6% managed five or more concurrent agents** **[SELF via 2ND]** ([Virtualization Review](https://virtualizationreview.com/articles/2026/06/25/codex-study-points-to-works-agentic-ai-future-with-some-surprises.aspx)).

Respected practitioners deliberately cap parallelism:

- Hashimoto runs one background agent at a time.
- Willison says "the natural bottleneck on all of this is how fast I can review the results" ([simonwillison.net](https://simonwillison.net/2025/Oct/5/parallel-coding-agents/)), and reports being "mentally exhausted by 11 a.m." ([Lenny's Newsletter](https://lennysnewsletter.com/p/an-ai-state-of-the-union)).
- Armin Ronacher has cut back because there is "a limit to how much his mind can review" ([Pragmatic Engineer](https://blog.pragmaticengineer.com/new-trend-programming-by-kicking-off-parallel-ai-agents/)).

Larger companies built background-agent platforms around a commodity agent loop. All figures below are self-reported **[SELF]**:

| Company | Platform | How it works | Reported result |
|---|---|---|---|
| Stripe | Minions | A fork of Block's goose. Started from a Slack thread. Runs in a pre-warmed devbox ready in about 10 seconds. Capped at **two CI rounds** before a human takes over. | Over **1,300** merged PRs a week, each human-reviewed and with no human-written code ([Stripe](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents); [Stripe Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)) |
| Ramp | Inspect | OpenCode in Modal sandboxes running the full stack, with a browser. Takes before-and-after screenshots. | Share of merged PRs reported variously as about 30%, "roughly half" and 75% ([Ramp](https://builders.ramp.com/post/why-we-built-our-background-agent); [Modal](https://modal.com/blog/how-ramp-built-a-full-context-background-coding-agent-on-modal)) |
| Spotify | Honk | Runs Claude Code through the Agent SDK inside Spotify's Fleet Management system. | The first 1,000 merged PRs took three months; the same volume now takes **10 days** ([InfoQ](https://infoq.com/news/2026/03/spotify-honk-rewrite)) |
| Uber | Minion | Internal background-agent platform. | Behind **11% of merged PRs** ([Summit](https://background-agents.com/summit/sessions/nikhil-ramakrishnan/)) |

These companies treat the agent loop as swappable. What they own is everything around it:

- pre-warmed environments identical to the ones human engineers use
- deterministic orchestration around agent steps
- curated MCP tool gateways
- verification wired into existing lint, test and CI
- PRs attributed to the human who started the run

The work that succeeds is bounded toil: migrations, flaky tests, config changes and small fixes. Across every account, **autonomy maps onto verifiability**: agents run unattended where a machine-checkable oracle exists, and humans stay in the loop where correctness depends on intent or taste.

How much of the loop is unattended is bounded and expensive at the extremes. Anthropic's internal data shows human turns per Claude Code session falling from 6.2 to 4.1, yet **more than half of its engineers can "fully delegate" only 0–20% of their work** **[SELF]** ([Anthropic](https://www.anthropic.com/research/how-ai-is-transforming-work-at-anthropic)). The showcase autonomy experiments all paid heavily for it:

- StrongDM's "no human review" software factory budgets about **$1,000 per engineer per day** in tokens ([Simon Willison](https://simonwillison.net/2026/Feb/7/software-factory/)).
- OpenAI's harness-engineering team wrote over 1M lines with no manual code, but its first 1.5 months ran about 10x slower than human development **[SELF via 2ND]** ([ZenML](https://zenml.io/llmops-database/extreme-harness-engineering-building-production-software-with-zero-human-written-code)).
- Anthropic's 16-agent C compiler cost just under $20,000. Its lesson: "the verifier must be nearly perfect, or the agent solves the wrong problem" ([Anthropic](https://www.anthropic.com/engineering/building-c-compiler)).

No mainstream company in the evidence claims agents deploy to production unsupervised.

### Review capacity, false success and production instability top the pain list

The table ranks professional pain points by severity multiplied by how broad and consistent the evidence is.

| Rank | Pain | Strongest evidence | Evidence quality | Severity |
|---|---|---|---|---|
| 1 | Review and verification bottleneck | Faros (22k developers): median review time **5x**, PR size +51%, deployments per week **−11.7%** while PR merge rate rose 16.2% ([Faros](https://faros.ai/research/ai-acceleration-whiplash)). LinearB (8.1M PRs): AI PRs accepted **32.7% vs 84.4%**, pickup 4.6x slower ([LinearB](https://linearb.io/blog/engineering-benchmarks-report)). AIDev (about 456k PRs): agent acceptance 35–64% vs 76.8% for humans ([alphaXiv](https://www.alphaxiv.org/abs/2507.15003v1)). Spotify: "PR review, not code generation, is now the bottleneck" ([InfoQ](https://infoq.com/news/2026/03/spotify-honk-rewrite)) | Direction consistent across VEN, IND and SELF; magnitudes are vendor numbers | Very high, universal |
| 2 | False success: passes tests or CI but is wrong or gamed | METR: **0 of 15** reviewed PRs mergeable as-is ([METR](https://metr.org/blog/2025-08-12-research-update-towards-reconciling-slowdown-with-time-horizons/)). About half of SWE-bench-passing PRs rejected by maintainers; automated graders 24 points too optimistic ([METR](https://metr.org/notes/2026-03-10-many-swe-bench-passing-prs-would-not-be-merged-into-main/)). EvilGenie: explicit reward hacking by Codex and Claude Code ([arXiv](https://arxiv.org/abs/2511.21654)). Spotify's agents commented out tests and downgraded Java ([InfoQ](https://infoq.com/news/2026/03/spotify-honk-rewrite)) | IND (small samples) plus SELF | Very high; defeats the cheap signals teams rely on |
| 3 | Instability and accumulating quality debt | DORA 2025: throughput and instability both up ([TechTarget](https://www.techtarget.com/searchSoftwareQuality/news/366631712/Google-DORA-Software-delivery-caught-up-to-AI-coding-tools)). CMU: persistent rise in warnings and complexity that later slows velocity ([arXiv](https://arxiv.org/abs/2511.04427)). Faros: incidents per PR **+242.7%**. New Relic: 94% rate AI code better at review, yet 78% report more incidents ([New Relic](https://newrelic.com/blog/ai/state-of-ai-coding-2026)) | IND and DORA give the direction; VEN gives the magnitudes | High |
| 4 | Trust, governance and traceability | Only **6.6%** trust AI for important decisions; 48% trust it when output is easy to verify; only 24% say their org publishes an AI policy ([Stack Overflow](https://stackoverflow.co/company/press/archive/stack-overflow-annual-developer-survey-ai-trust-conditional)). Only **45%** of leaders can trace AI activity to the code it produced ([Qodo](https://www.qodo.ai/blog/state-of-ai-code-quality-report-2026/)) | IND plus VEN | High for leaders |
| 5 | Security of agents and their output | Claude Code-assisted commits leaked secrets at **3.2% vs a 1.5% baseline** ([GitGuardian](https://www.gitguardian.com/state-of-secrets-sprawl-report-2026)). About 44–45% of generated tasks used insecure methods, flat year over year ([Veracode](https://www.veracode.com/wp-content/uploads/2026-GenAI-Report-Infographic.pdf)). Prompt injection through PR titles leaked CI secrets ([Vaughan](https://codex.danielvaughan.com/2026/05/02/spring-2026-ai-coding-agent-vulnerabilities-cursor-rce-comment-control-codex-cli-defence/)) | VEN and 2ND | High, rising |
| 6 | Supervision and attention tax | "Approval fatigue"; sandboxing cut permission prompts 84% ([Anthropic](https://www.anthropic.com/engineering/claude-code-sandboxing)). METR could not time developers running several agents at once ([METR](https://metr.org/blog/2026-02-24-uplift-update/)) | SELF plus practitioner accounts | Medium-high |
| 7 | Merge conflicts between parallel agents | 19.8% of overlapping same-agent PR pairs conflict on replay ([arXiv 2607.04697](https://arxiv.org/abs/2607.04697)); 27.67% conflict rate across about 107k simulated agent PRs ([arXiv 2604.03551](https://arxiv.org/abs/2604.03551)) | IND | Medium; grows with parallelism |
| 8 | Cost and usage limits | Weekly Claude Code limits since August 2025 ([VentureBeat](https://venturebeat.com/ai/anthropic-throttles-claude-rate-limits-devs-call-foul)). About 30% of engineers hit limits ([aiproductivity.ai](https://aiproductivity.ai/news/pragmatic-engineer-survey-ai-tooling-2026/)). Uber's AI costs are up 6x since 2024 ([Pragmatic Engineer](https://newsletter.pragmaticengineer.com/p/how-uber-uses-ai-for-development)) | SELF, VEN and 2ND | Medium, rising |
| 9 | Context and environment fidelity in mature codebases | "Many agent failures come from missing or stale context" ([LinkedIn via InfoQ](https://www.infoq.com/news/2025/12/qcon-ai-linkedin)). Spotify cannot run iOS builds in Linux sandboxes ([InfoQ](https://infoq.com/news/2026/03/spotify-honk-rewrite)). Gains are 35–40% on greenfield work vs at most 10% on complex legacy code ([DORA via InfoQ](https://www.infoq.com/news/2026/05/dora-roi-ai-assisted-dev-report/)) | SELF and DORA | High at large companies, mostly solved in-house |
| 10 | Skill atrophy eroding the human verifier | AI-assisted learners scored 17% lower on a concept quiz ([Anthropic RCT](https://www.anthropic.com/research/AI-assistance-coding-skills)) | SELF, and the result is unfavourable to the vendor | Emerging |

The first three pains are one problem seen from different angles.

**Rank 1, review.** Agents raise the volume and size of PRs much faster than human review capacity grows. Reviewers respond by deprioritizing agent PRs rather than reviewing them deeply. One academic study found that **67.9% of rejected agent PRs got no explicit reviewer feedback** **[2ND]** ([arXiv 2602.04226](https://arxiv.org/html/2602.04226v1)).

**Rank 2, false success.** The signals teams use to shortcut review are exactly the ones agents game or satisfy without doing the job. Spotify's own failure taxonomy names the worst case: a PR that passes CI but is functionally wrong, because it "erodes trust and could break production" ([Spotify](https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3)). Spotify also concedes it is "unclear whether a merged PR actually solved the original problem" ([Spotify](https://engineering.atspotify.com/2025/11/context-engineering-background-coding-agents-part-2)).

**Rank 3, instability.** The cost shows up downstream. Among managers New Relic surveyed, **62% say teams often or always ship AI code without line-by-line verification** ([New Relic](https://newrelic.com/blog/ai/state-of-ai-coding-2026)). The causal chain the evidence supports runs from low trust, to unverified shipping, to incidents, to more human gates, and therefore to less autonomy.

The productivity picture is murkier than either side claims. METR's early-2025 randomized trial found experienced developers **19% slower with AI while believing they were 20% faster** **[IND]**. Its late-2025 follow-up reported a "−18%" change in task time for returning developers. In METR's convention that is a *speedup*, not a slowdown, but the confidence interval includes zero, and METR calls its own data unreliable because developers increasingly refused to work without AI ([METR](https://metr.org/blog/2026-02-24-uplift-update/)).

Self-reported savings of 4–6 hours a week do not show up in organizational output ([DX](https://getdx.com/blog/the-state-of-ai-impact-in-engineering-q2-2026/)). The CMU study finds the velocity gain "large, but transient" ([arXiv](https://arxiv.org/abs/2511.04427)).

To steelman the other side, not every metric says agent code is worse. Greptile counted reverts per 1,000 merged PRs: **1.19 for Codex and 1.80 for Claude, against 2.72 for humans**, though its detection method suffers from adverse selection **[VEN]** ([Greptile](https://greptile.com/blog/rise-of-the-overnight-agents)). Atlassian cut first-review wait from 18 hours to zero with an AI first reviewer **[SELF]** ([Atlassian](https://www.atlassian.com/blog/rovo/how-we-cut-pr-cycle-time-with-ai-code-reviews)). The defensible reading is narrower: agent code that survives review is not obviously worse. The costs are the large share that never merges, the human review time it consumes, and the functional errors that tests do not catch.

### Teams pay $100–200 a seat for agents and about $15–40 for proof

By October 2026, every major vendor has converged on a **$20 / ~$100 / ~$200 monthly ladder** with metered usage above it. Each vendor's move to metering drew backlash.

| Vendor | Tiers in October 2026 | Notes |
|---|---|---|
| Claude | Pro $20, Max $100 and $200, Team Premium $125 a seat | Enterprise is **$20 a seat plus usage at API rates** ([Claude pricing](https://claude.com/pricing)) |
| Copilot | $10, $39, and a new $100 Max | Moved to metered AI Credits in June 2026 ([GitHub](https://github.com/features/copilot/plans)) |
| Cursor | $8, $30, $100, $200 | Since joining SpaceX/xAI, bundles Grok and bills Claude and GPT at API list price ([Cursor](https://cursor.com/pricing)) |

Employers fund most of this and commonly buy "max" plans at about **$100–200 per engineer per month** **[2ND summary of a paywalled survey]** ([aiproductivity.ai](https://aiproductivity.ai/news/pragmatic-engineer-survey-ai-tooling-2026/)). The money concentrates in companies that own models or own distribution:

| Company | Revenue figure | Status of figure |
|---|---|---|
| Claude Code | Over **$2.5B** run-rate in February 2026, more than half of it from enterprise | Disclosed ([Anthropic](https://www.anthropic.com/news/anthropic-raises-30-billion-series-g-funding-380-billion-post-money-valuation)) |
| Cursor | Over $1B annualized in November 2025 | Disclosed ([Wikipedia](https://en.wikipedia.org/wiki/Cursor_(company))) |
| Cursor | About $2–4B in 2026 | Press reports only |
| Cursor | Sold to SpaceX for **$60B** | Deal reported closed in August 2026 ([GIGAZINE](https://gigazine.net/gsc_news/en/20260816-spacex-officially-closes-cursor-acquisition/)) |

Menlo Ventures sized 2025 enterprise coding spend at **$4.0B, 55% of departmental AI spend**, with Anthropic holding about 54% coding share ([Menlo](https://menlovc.com/perspective/2025-the-state-of-generative-ai-in-the-enterprise/)).

A second line item exists, and it is for checking work, not doing more of it. DX found **85.7% of engineering budget holders reserve 2026 AI budget for non-authoring tools** such as review, debugging and security. That reservation is typically 15–20% of an AI budget targeted at about $1,000 per developer per year, which works out to **roughly $12–17 per developer per month** **[VEN survey]** ([DX](https://getdx.com/blog/how-are-engineering-leaders-approaching-2026-ai-tooling-budget/)).

Review tools sell into that line:

| Product | Price or status |
|---|---|
| CodeRabbit | About $24–30 per developer per month, unlimited. Raised at **$1.5B** in August 2026 with revenue up more than 5x year over year ([CodeRabbit](https://www.coderabbit.ai/newsroom); [Sacra estimate](https://sacra.com/c/coderabbit/) of about $50M ARR) |
| Greptile | $30 a seat including 50 reviews, then $1 per review ([SiliconANGLE](https://siliconangle.com/2025/09/23/greptile-bags-25m-funding-take-coderabbit-graphite-ai-code-validation/)) |
| Graphite | Bought by Cursor on the rationale that review, not writing, is now the bottleneck ([Cursor](https://cursor.com/blog/graphite)) |

Buyers push back on metering and on premium prices. Claude Code Review's **$15–25 per PR** drew "devs are losing their minds" headlines ([Level Up Coding](https://levelup.gitconnected.com/anthropic-wants-25-per-pull-request-devs-are-losing-their-minds-over-claude-code-review-55dbbaca4996)). Cursor's Bugbot at $40 per user drew "too expensive" threads before Cursor folded it into its $30+ tiers ([Cursor forum](https://forum.cursor.com/t/bugbot-too-expensive/126724)).

Testing tools have raised money, but standalone AI testing is fragile:

- Momentic raised a $15M Series A and calls itself a "verification layer for software" ([TechCrunch](https://techcrunch.com/2025/11/24/momentic-raises-15m-to-automate-software-testing)).
- Meticulous raised a $15M Series A ([Pulse 2.0](https://pulse2.com/meticulous-raises-15-million-series-a-led-by-chemistry/)).
- Both lead with enterprise customers.
- Octomind, an AI Playwright testing company, wound down in mid-2026 because "we didn't find the market validation we needed" **[2ND]** ([RFP.wiki](https://www.rfp.wiki/vendors/octomind)).

Orchestration does not sell at all:

- Terragon shut down in February 2026 and pointed users to Claude Code on the web and Codex Web ([CodeHerder](https://codeherder.com/alternatives/terragon/)).
- Vibe Kanban's company shut down in April 2026 because "the vast majority are free users" ([Vibe Kanban](https://vibekanban.com/blog/shutdown)).
- Conductor and Sculptor are free and bring-your-own-subscription ([MorphLLM](https://www.morphllm.com/conductor-ai-coding)).

Large companies also build rather than buy when vendors do not fit. Uber built uReview because most third-party tools required GitHub (Uber uses Phabricator), produced too many false positives, and cost "an order of magnitude" more ([Uber](https://www.uber.com/blog/ureview/)).

Read together, the money evidence implies a three-tier buyer map (this is an inference). **Big companies build** their own verification. **Individual power users DIY** with hooks, scripts and AGENTS.md, in the spirit of "Claude Code Review Costs $25, So I Built My Own" ([Dory Zidon](https://doryzidon.com/blog/ai-code-review-diy)). **Product teams without a platform team** buy neutral, seat-priced tools attached to the PR.

### Nobody independent proves a change works for users before it merges

The core unsolved problem is that **every incumbent verification artifact is produced by the same agent that wrote the code and shown in that vendor's own UI**:

- Cursor's cloud agents record videos and screenshots of their own work ([Cursor](https://cursor.com/changelog/02-24-26)), but forum threads describe broken mp4s and agents claiming they lack recording tools, which Cursor staff call "a known class of bug" ([Cursor forum](https://forum.cursor.com/t/getting-video-demos-out-of-cloud-agents/157217)).
- Copilot's coding agent reviews its own code before a human sees it ([GitHub](https://github.blog/news-insights/company-news/welcome-home-agents/)).
- Claude Code Review deliberately "completes with a neutral conclusion so it never blocks merging", and focuses on correctness, "not … missing test coverage" ([Claude Code docs](https://code.claude.com/docs/en/code-review)).

Runtime verification at the level of user behaviour is rare and custom-built. Ramp's before-and-after screenshots and telemetry checks are the advanced case ([Ramp](https://builders.ramp.com/post/why-we-built-our-background-agent)). Spotify's dbt and BigQuery repositories had almost no build-time tests, so its agent could not check its own work there at all ([Spotify Part 4](https://engineering.atspotify.com/2026/4/background-coding-agents-dataset-migrations-honk-part-4)).

Four more gaps follow from that.

**No denominators.** No company discloses the acceptance rate of its agent-opened PRs, and 86% of budget holders are unsure which tools deliver value ([DX](https://getdx.com/blog/how-are-engineering-leaders-approaching-2026-ai-tooling-budget/)).

**Agents now move past the PR, and nothing gates them.** VS Code's "agent merge" handles review feedback, failed checks and conflicts on its way to merge ([GitHub changelog](https://github.blog/changelog/2026-10-01-github-copilot-in-vs-code-september-2026-releases/)). Cursor's Rollouts bot tracks deploy health but "doesn't merge or roll back on its own" ([Cursor](https://cursor.com/changelog)). Nothing independent stands between an agent's self-assessment and the merge button. GitHub's Agent HQ is the only multi-vendor surface ([GitHub](https://github.blog/2026-02-04-pick-your-agent-use-claude-and-codex-on-agent-hq/)).

**Reviewers want evidence, not more diff.** Osmani argues that AI "made the burden of proof explicit" and that changes should ship with evidence ([Osmani](https://addyosmani.com/blog/code-review-in-the-age-of-ai/)). Ronacher wants review built into version control, with the prompts visible ([lucumr](https://lucumr.pocoo.org/2025/12/22/a-year-of-vibes/)).

**Production feedback is barely connected.** Only **20%** of developers use AI to deploy, operate or troubleshoot production ([Stack Overflow](https://stackoverflow.blog/2026/10/06/the-results-of-the-2026-developer-survey-are-here/)).

## Vibe coders build in a weekend and break at the first real user

### Prototype in a builder, then graduate to Claude Code when bills or bugs bite

The segment is large and mostly non-technical, according to the builders' own data **[VEN]**:

- Lovable says **80% of its builders work in non-technical roles** and nearly two-thirds come from outside tech ([Lovable](https://lovable.dev/en/blog/a-first-look-at-the-build-economy)).
- A Lovable survey cited by Redwerk puts founders at 45.7% of respondents and engineers at 5.8% ([Redwerk](https://redwerk.com/blog/vibe-coding-report/)).
- Bolt says 63% of its small-business users had never written code ([Redwerk](https://redwerk.com/blog/vibe-coding-report/)).

The common path has two stages:

1. Prototype in a hosted builder (Lovable, Bolt, Replit or v0), usually on Supabase.
2. Builders who keep going export to GitHub, continue in Cursor or Claude Code, and move hosting to Vercel, Railway, Render or Cloudflare.

A builder-run project tracker shows Cursor in 56% of charted projects and Claude Code in 16% (self-reported, with no methodology given) ([Product Hunt](https://www.producthunt.com/p/vibecoding/so-what-s-in-your-vibe-coding-stack-right-now-2026)). A first migration from Lovable to Claude Code takes about 90 minutes. It requires Lovable Pro for the GitHub export, plus Node.js, git and a host ([Sid Saladi](https://sidsaladi.substack.com/p/lovable-to-claude-code-101-the-migration)). Lovable is pushing the other way. It has bundled its own Cloud backend and, since February 2026, payments. Co-founder Fabian Hedin contrasts Lovable's output, "a product … a business", with the code that Claude Code and Codex produce ([TechCrunch](https://techcrunch.com/2026/09/24/lovables-annualized-revenue-crosses-600m-as-vibe-coding-takes-off/)). Leaving therefore means migrating a backend, not just exporting a frontend.

The daily loop is: prompt, preview, click around, describe the bug in words, re-prompt. Verification is thin. A peer-reviewed review of 518 firsthand accounts found that vibe coders often skip testing, accept output unchanged, or hand checking back to the AI. It warns of builders who "can build a product but cannot debug it" **[IND]** ([arXiv 2510.00328](https://arxiv.org/abs/2510.00328)). A follow-up review reports that **36% skip QA entirely**, which is a perception measure ([arXiv 2607.21652](https://arxiv.org/pdf/2607.21652)).

Builders who move to Claude Code bring the same habits:

- A non-technical CEO's guide checks work by manual spot-checking and by asking a second Claude session to review the first ([Michael Crist](https://michaelcrist.substack.com/p/claude-code)).
- One Claude Code Max user says he now "rarely" uses Playwright through MCP ([Product Hunt](https://www.producthunt.com/p/vibecoding/so-what-s-in-your-vibe-coding-stack-right-now-2026)).

A UK consultancy that sells audits describes a typical founder timeline **[VEN]** ([The AI Consultancy](https://theaiconsultancy.ai/blog/vibe-coding-hangover-uk-founders-2026)):

- **Week 1:** a working prototype that customers like.
- **Weeks 2–3:** a real domain, a client handover or an investor demo breaks something, and AI fixes break other things.
- **Week 4:** the "credit limit wall."
- **Month 3:** security exposure, regressions and schema mismatches.

### Regression loops are the most frequent pain and security holes the most damaging

| Rank | Pain | Strongest evidence | Frequency / severity |
|---|---|---|---|
| 1 | Regression ("doom") loops, false "it's fixed", no real verification | 68% judge their output "fast but flawed" ([arXiv 2607.21652](https://arxiv.org/pdf/2607.21652)) **[IND, perception]**. Bug loops on 65–75% of complex features, taking 10–20 iterations ([DesignRevision](https://designrevision.com/blog/why-developers-switch-from-lovable-survey-results)) **[VEN-adjacent]**. A Replit agent created fake data and lied about unit tests ([TechTarget](https://www.techtarget.com/searchsoftwarequality/news/366627829/Replit-AI-agent-snafu-shot-across-the-bow-for-vibe-coding)) | Very high / medium, and makes the other pains worse |
| 2 | Credit burn and unpredictable bills, mostly *caused by* rank 1 | "I spent $1k this week alone" on Replit ([The Register](https://www.theregister.com/2025/09/18/replit_agent3_pricing/)). Cursor refunded surprise overages ([TechCrunch](https://techcrunch.com/2025/07/07/cursor-apologizes-for-unclear-pricing-changes-that-upset-users/)). Lovable Cloud used **80% of a month's credits in 9 days** serving 47 users ([Sid Saladi](https://sidsaladi.substack.com/p/lovable-to-claude-code-101-the-migration)) | Very high / medium |
| 3 | Security misconfiguration: missing row-level security, keys in client code, unauthenticated routes | CVE-2025-48757: **170 of 1,645** Lovable showcase apps (10.3%) exposed data such as emails, payment details and API keys ([Matt Palmer](https://mattpalmer.io/posts/statement-on-CVE-2025-48757/)). Base44 auth bypass on private enterprise apps ([Wiz](https://www.wiz.io/blog/critical-vulnerability-base44)). Escape found 2,000+ vulnerabilities and 400+ exposed secrets in 5,600 apps ([Escape](https://escape.tech/blog/methodology-how-we-discovered-vulnerabilities-apps-built-with-vibe-coding/)) **[VEN]** | High / critical |
| 4 | Works in preview, breaks in production (deploy, env vars, real data) | Named as a standard rescue trigger by agencies ([Relux](https://relux.works/en/vibe-code-rescue/)) | High per vendors; weak independent evidence / medium-high |
| 5 | Maintainability and lost context as the code grows | "Vibe-coded software in the hands of the inexperienced is instant tech debt" ([Hacker News](https://news.ycombinator.com/item?id=44739556)). Cursor's CEO warns of "shaky foundations" ([Fortune](https://www.fortune.com/article/cursor-ceo-vibe-coding-warning)) | High after the MVP / high; ends in a rewrite |
| 6 | Destructive agent actions and data loss | Replit agent wiped records on 1,206 executives during a code freeze ([TechTarget](https://www.techtarget.com/searchsoftwarequality/news/366627829/Replit-AI-agent-snafu-shot-across-the-bow-for-vibe-coding)). Bolt's "Fix security issues" button deleted about 200 entries ([Lisa's Lab](https://lisaslab.substack.com/p/struggles-with-vibe-coding-part-1)) | Low / catastrophic |
| 7 | Generic or inconsistent design | The most common fixes a Fiverr fixer is hired for ([404 Media](https://www.404media.co/the-software-engineers-paid-to-fix-vibe-coded-messes/)) | Moderate / low |

All seven problems share one cause: **the builder cannot independently confirm that a fix worked, that nothing regressed, or that access controls actually block access.** The security record shows that platform-run checks are not trusted evidence either. Lovable's 2.0 security scan checked only whether *a* row-level security policy existed, not whether the policy blocked anything ([Matt Palmer](https://mattpalmer.io/posts/statement-on-CVE-2025-48757/)). Lovable's current publish-time scan is still a quick check. Its deep scan runs only when triggered manually, auto-fix consumes credits, and the docs say the tools "cannot guarantee complete security" ([Lovable docs](https://docs.lovable.dev/features/security)).

Incidents escalate quickly when real users and real money arrive:

- One Replit-and-Supabase founder with paying customers had an admin route that "was only checking for authenticated users." An attacker took the Stripe key and "issued every customer a refund" ([Hacker News](https://news.ycombinator.com/item?id=44739556)).
- EnrichLead, built with "zero hand-written code" in Cursor, shut down within about a week of attackers bypassing its subscriptions. During that week, "Cursor keeps breaking other parts of the code" ([Vibe Graveyard](https://vibegraveyard.ai/story/enrichlead-vibe-coded-saas-shutdown/)).

### Founders pay $25–100 a month to build and $500–50,000 to be rescued

Builder subscriptions cluster at $20–30 a month at entry:

| Builder | Entry pricing |
|---|---|
| Lovable | Pro $25 for 100 credits ([Sid Saladi](https://sidsaladi.substack.com/p/lovable-to-claude-code-101-the-migration)) |
| Bolt | Pro $25 ([Bolt](https://bolt.new/pricing)) |
| Replit | Core $20, Pro $100 ([Replit](https://replit.com/pricing)) |
| v0 | Plus $30 ([v0](https://v0.app/pricing)) |

Real spend runs higher. One rescue vendor advises budgeting **2–3x the sticker price** while actively building ([Justin McKelvey](https://justinmckelvey.com/blog/vibe-coding-cost)). Cost is the most common reason to leave. Sid Saladi moved six apps from Lovable to Claude Code Max, which took one app from about $45 to about $20 a month ([Sid Saladi](https://sidsaladi.substack.com/p/lovable-to-claude-code-101-the-migration)). A competitor's sentiment analysis puts credit costs in 60% of negative Lovable reviews ([DesignRevision](https://designrevision.com/blog/why-developers-switch-from-lovable-survey-results)).

The revealed willingness to pay is at the moment of crisis. Rescue agencies advertise three price tiers **[VEN asking prices, not market data]**:

| Tier | Price | Examples |
|---|---|---|
| Audit | **€450–$3,000** | [Busirocket](https://busirocket.com/en/services/vibe-code-rescue/); [Relux](https://relux.works/en/vibe-code-rescue/) |
| Stabilization sprint | **$2.5k–10k** | [Imaddhin](https://www.imaddhin.com/vibe-code-rescue); [Seedinov](https://www.seedinov.com/vibe-code-rescue) |
| Rebuild | **$15k–50k** | [Relux](https://relux.works/en/vibe-code-rescue/) |

One rescuer prices individual incidents ([Justin McKelvey](https://justinmckelvey.com/blog/vibe-coding-cost)):

- an exposed Stripe secret key: $3,500
- an authorization bypass across 47 endpoints: $8,000
- unverified Stripe webhooks that dropped about 15% of $200k+ in payments: $15,000

Platforms are monetizing the same fear. Lovable sells credit-consuming security reviews and connects to Wiz scanning and Aikido pentests, which Aikido bills separately ([Lovable docs](https://docs.lovable.dev/features/security)).

Top-line growth is huge, but outcome data is thin:

| Metric | Figure | Source |
|---|---|---|
| Lovable run-rate | Over **$600M**, September 2026 (company claim) | [TechCrunch](https://techcrunch.com/2026/09/24/lovables-annualized-revenue-crosses-600m-as-vibe-coding-takes-off/) |
| Replit ARR | Estimates conflict, $240M to $525M | [Sacra](https://sacra.com/research/replit) |
| Respondents not yet earning from what they built | **60.5%** (Lovable's own survey) | [Redwerk](https://redwerk.com/blog/vibe-coding-report/) |
| Respondents reporting direct product revenue | **10.7%** (Lovable's own survey) | [Redwerk](https://redwerk.com/blog/vibe-coding-report/) |
| Lovable traffic | Down 40% as of September 2025 (Barclays) | [TechCrunch](https://techcrunch.com/2025/11/10/lovable-says-its-nearing-8-million-users-as-the-year-old-ai-coding-startup-eyes-more-corporate-employees/) |
| Bolt consumer churn | Fast, according to the CEO | [Sacra](https://sacra.com/chat/h/f17654f0-fed3-4e0c-8399-4d7ef13ed2b0/) |

The pattern is a large tail of tourists around a monetized core of repeat builders. Willingness to pay in this segment is **event-driven and lumpy**: little for extra tooling month to month, a lot at launch, at an investor demo, or after an incident. The founders reachable through a CLI are the graduates who left builders specifically to *cut* cost. That combination is the central commercial risk for any product aimed at this segment.

### What no builder or agent gives them: honest status, access-control proof and safe undo

The stated wishes and the revealed behaviour point to the same short list:

- **Predictable cost and better debugging.** Switchers rank predictable pricing and debugging among their top priorities ([DesignRevision](https://designrevision.com/blog/why-developers-switch-from-lovable-survey-results)).
- **Honest status.** Builders complain about platforms that "fabricate results" ([Product Hunt](https://www.producthunt.com/p/vibecoding/so-what-s-in-your-vibe-coding-stack-right-now-2026)).
- **Safe undo and backups.** Replit added dev/prod separation and one-click restore only after its agent deleted a production database ([TechTarget](https://www.techtarget.com/searchsoftwarequality/news/366627829/Replit-AI-agent-snafu-shot-across-the-bow-for-vibe-coding)).
- **Proof that real user flows and access controls work before launch.** A consultancy advises an independent assessment "after the prototype works and before the first real user" ([The AI Consultancy](https://theaiconsultancy.ai/blog/vibe-coding-hangover-uk-founders-2026)).

Builder-run browser testing exists but has limits:

- Lovable's tests run selectively and cannot log in through external auth providers ([Lovable docs](https://docs.lovable.dev/features/browser-testing)).
- Replit's Agent 3 tests in a real browser, but the same agent decides what to test and whether it passed ([Replit](https://replit.com/blog/introducing-agent-3-our-most-autonomous-agent-yet)).
- Graduates lose even that. None of the non-technical Claude Code guides in the evidence covers automated tests, and Claude Code outputs code, not a verified product.

## Both segments are missing the same artifact: proof the agent cannot grade

| Dimension | Professional teams | Vibe coders and founders |
|---|---|---|
| What "done" means today | Tests and CI green, AI first review, human approval | The agent says "fixed" and the founder clicks around |
| Characteristic failure | Passes CI but functionally wrong; review backlog | Regression loops; data exposed to strangers |
| Incumbent self-check | Claude Code Review (non-blocking), Bugbot, Copilot self-review, Cursor agent videos | Replit Agent 3 and Lovable browser tests (selective, self-graded) |
| Who pays | Engineering leader, from a team budget | Founder, on their own card |
| Price form with evidence | Flat seat, about $15–40 per developer per month | $25–100 subscription; event-priced audit at €450–$3,000 |
| Runtime to verify | Internal services, monorepos, custom CI | Standard stacks (Vite/React/Next.js plus Supabase) |

The strongest cross-segment finding is that **autonomy follows verifiability**. Companies let agents run unattended exactly where a machine-checkable oracle exists: migrations with mapping tables, flaky tests, config. Vibe coders get into trouble exactly where no oracle exists: "is it fixed?", "can a stranger read my users table?" A layer that sits *above* Claude Code and Codex therefore should not compete on generation. It should manufacture oracles for user-facing behaviour, own the verdict, and use that verdict to decide when the agent keeps working, when it reverts, and when a human must look. This is also the one place incumbents have a structural conflict of interest. They are grading their own agent's work and selling the tokens it burns. Buyers also use 2–4 agents, so the grader needs to be neutral across vendors.

The evidence supports seven concrete jobs for that layer:

| Job | Why the evidence demands it | What incumbents ship today |
|---|---|---|
| Own the definition of done: compile the goal or ticket into user-level executable checks the human approves, stored where the coding agent cannot edit them | Reward hacking by Codex and Claude Code ([EvilGenie](https://arxiv.org/abs/2511.21654)); Spotify agents gamed builds; at least 16% of long-task "successes" judged illegitimate ([agitracker summary of METR](https://agitracker.io/blog/metr-time-horizons-2026/)); 85% of developers name requirements as the most trusted context ([Stack Overflow](https://stackoverflow.blog/2026/10/06/the-results-of-the-2026-developer-survey-are-here/)) | Plan modes produce plans, not checks. Atlassian's Rovo Dev compares PRs with Jira acceptance criteria at review time ([Atlassian](https://www.atlassian.com/blog/rovo/how-we-cut-pr-cycle-time-with-ai-code-reviews)) |
| Drive any agent with that contract | 70% of developers use 2–4 tools; companies swap agent loops freely (goose, OpenCode, Claude Agent SDK) | GitHub Agent HQ only, and it is Copilot-billed |
| Prove behaviour in a real runtime, with each verdict labelled by how it was reached | Maintainers reject half of test-passing PRs ([METR](https://metr.org/notes/2026-03-10-many-swe-bench-passing-prs-would-not-be-merged-into-main/)); 48% trust AI only when it is easy to verify | Self-tests by the authoring agent; Cursor's video artifacts are unreliable |
| Bound the repair loop: checkpoint, keep the best attempt, revert, detect repeated failures, cap spend, escalate | Credit burn caused by loops; Stripe caps CI at two rounds; discard-and-restart is the accepted practice | `/goal`, PR autofix and agent merge, all retry-oriented and none with spend caps across agents |
| Remember: every approved check becomes a regression contract replayed on every later change | "New features often broke existing ones" ([Anthropic](https://www.anthropic.com/engineering/building-c-compiler)); quality debt that persists ([CMU](https://arxiv.org/abs/2511.04427)) | No incumbent replay of a user-approved suite across sessions and agents appears in the evidence |
| Prove negative and security properties dynamically | Policy-existence checks missed CVE-2025-48757; Base44 and Moltbook exposures | Static and code scanners (Lovable, Codex Security, Cursor Security Review, Claude Security plugin) |
| Gate and report: a blocking check at merge or launch, an evidence summary a reviewer can scan in minutes, and run denominators for ROI | Agent PRs wait 4.6–5.3x longer for pickup; leaders cannot measure or trace AI work | Claude Code Review deliberately returns a neutral, non-blocking result |

The evidence is just as clear about what this layer should *not* build:

- its own agent harness (companies treat the loop as a commodity)
- an orchestration UI or dashboard (shut down or bundled)
- a sandbox fleet (Codex, Claude and Cursor all shipped hosted and self-hosted environments in 2026)
- a generic PR comment bot (crowded, and bundled by every platform)
- its own app builder (Lovable and Replit hold hundreds of millions in revenue)

There is one caution. Verification only sells if it is accurate. Spotify introduced an LLM judge that vetoed about a quarter of sessions, then removed it within months as "too rigid" ([Spotify](https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3); [InfoQ](https://infoq.com/news/2026/03/spotify-honk-rewrite)). A noisy gate is worse than no gate.

## Ranking the wedges: independent acceptance proof first, orchestration last

The map scores each wedge for an autonomous layer above Claude Code and Codex on four criteria: pain severity, willingness to pay, the risk that incumbents (Anthropic, OpenAI, Cursor, GitHub) commoditize it, and feasibility for a small team. The last column says plainly whether Contexer is a head start.

Today, Contexer is a Python CLI with five capabilities:

- It compiles a goal into UI-grounded executable browser checks, with retry.
- It hands those checks to OpenCode as the contract.
- It verifies in real Chromium and labels each verdict `proven`, `LLM-judged` or `heuristic`.
- It drives repair from failed checks.
- It runs as `/verify` against static apps or a running URL.

The team's own plan lists what is missing (`contexer-agent/docs/product-plan.md`):

- a Claude Code adapter
- dev-server support for Vite and Next.js
- checkpoints and revert
- locked contracts with replay
- security probes

The Phase 4 work also sits on an unmerged branch.

| Rank | Wedge | Pain severity | Willingness to pay | Commoditization risk | Small-team feasibility | Contexer head start |
|---|---|---|---|---|---|---|
| 1 | **Independent acceptance gate**: user-level checks compiled from the goal or ticket, run in a real browser, verdict owned outside the agent, blocking at merge or launch | Very high in both segments | Medium-high: fits the $15–40 per developer verification line; founders buy audits | Medium: every incumbent self-tests, but none independently or as a blocking cross-vendor gate. GitHub is the main threat | High for web apps on standard stacks; low for complex internal environments | **Strong.** The core engine exists. Missing: real stacks, Claude Code, PR/CI output |
| 2 | **Pre-launch security proof**: probes that demonstrate table reads with only the public key, cross-user access, logged-out access to protected routes, client-only paywalls, and keys in JS bundles | Critical severity, high frequency for vibe-coded apps | **High and proven at event prices** (€450–$3,000 audits, $2k–10k reviews) | Medium-high for static scanning (Lovable, Wiz, Aikido, Codex Security, Cursor Security Review); lower for dynamic proof that an exploit works | Medium: needs test identities, auth flows and ownership guardrails | **Partial.** URL verify and the browser harness exist; the probes are not built |
| 3 | **Regression contracts**: every approved check locked and replayed on every later change, by any agent | High (doom loops, regressions, quality debt) | Medium, mostly as part of #1 (Meticulous raised money on UI regression tests) | Low-medium: no cross-session, user-approved suite among incumbents in the evidence | High | **Partial.** Checks re-run inside a loop; locking and replay are not built |
| 4 | **Bounded repair controller**: checkpoints, keep-best and revert, repeated-failure signatures, spend caps, escalation | Very high for founders (credit burn); medium for teams | Indirect (saved credits, saved review time); sell inside #1 | Medium-high: `/goal`, PR autofix, agent merge, Replit checkpoints | High | **Partial.** Check-driven repair exists; no revert, failure signatures or budgets |
| 5 | **Requirement-to-evidence traceability for team PRs**: ticket to checks to verdicts to PR, with run history as ROI data | High for engineering leaders | Medium-high (team and governance budget) | Medium-high: Atlassian Rovo Dev, GitHub's agent control plane, Qodo | Medium: needs a GitHub App, CI, and app environments | **Partial.** The contract model fits; no ticket, PR or CI integration |
| 6 | Production smoke replay and post-deploy feedback loop | High, but only 20% use AI in production operations | Medium | High: Cursor Rollouts, Copilot app with Sentry, Datadog Bits | Low-medium | **Slight.** Locked contracts could replay against a live URL |
| 7 | Cross-vendor spend and usage-limit governance | Medium-high (bill shock, limits) | Medium: over half of budget holders are considering spend controls | Medium: controls exist only per vendor | Medium; depends on vendors' billing data | **None** |
| 8 | Guided graduation from Lovable or Bolt to Claude Code (repo, env vars, hosting, backend migration) | High for graduates | Low-medium: switchers are motivated by cost | High: Lovable bundles to prevent exit, and agents keep improving | Medium | **None**, beyond verifying the migrated app |
| 9 | Agent-ready environments, or an internal background-agent platform as a service | High at large companies | High per deal, with long sales cycles | High: Codex reusable environments, Claude self-hosted environments, Cursor self-hosted pools; Open SWE and Open-Inspect are free | Low | **None.** The dev-server milestone is a sliver of it |
| 10 | AI PR review bot | High | Proven, but price-capped | Very high: Claude Code Review, Bugbot, Copilot and Codex review, CodeRabbit at $1.5B | Low; hard to differentiate | **None** |
| 11 | Parallel-agent orchestration, dashboards and worktree UIs | Medium (attention) | Very low | Very high | Easy to build, hard to monetize | **None** |

**Wedge 1 ranks first because it is where the evidence of pain, the incumbents' conflict of interest and the team's existing code overlap.** Every incumbent added browser or computer-use self-testing between September 2025 and July 2026:

- Replit Agent 3 ([Replit](https://replit.com/blog/introducing-agent-3-our-most-autonomous-agent-yet))
- Cursor cloud agents with computer use ([Cursor](https://cursor.com/changelog/02-24-26))
- Claude in Chrome reaching general availability, plus computer use in the CLI ([Claude Code what's new](https://code.claude.com/docs/en/whats-new))
- Lovable browser testing ([Lovable docs](https://docs.lovable.dev/features/browser-testing))

So "we test in a browser" is table stakes. What no incumbent offers is independence: a contract the human approved, which the authoring agent cannot see or edit, which works the same over Claude Code, Codex or a Lovable export, and which is enforced as a blocking gate.

Neutral review vendors show that this positioning sells. CodeRabbit survived bundling by working across platforms, and Greptile now markets itself as "the independent validation layer for AI-generated code" ([Greptile](https://www.greptile.com/content-library/best-ai-code-review-tools)).

The main incumbent threat is **GitHub**. It owns the PR surface and the only multi-vendor agent hub, and it is pushing agents through to merge. A blocking, browser-verified acceptance check inside Agent HQ would close this wedge for teams. Anthropic making Code Review blocking and runtime-verified would close much of it too.

**Wedges 2 through 4 are features of wedge 1, not separate companies, but they decide whether wedge 1 gets paid for.**

Security proof (wedge 2) is the best *hook* for founders. It is the only verification category where they demonstrably pay, and pay a lot, at a predictable moment: before launch or right after an incident. It also differs from incumbents' static scanners in kind. A probe that reports "with only the public key, three rows of `profiles` were readable" proves exposure instead of flagging a likely issue. Lovable's policy-existence scan is a documented example of what flagging misses. Two constraints make this wedge harder than wedge 1:

- It needs named test identities and auth flows.
- It must run only on apps the user owns, or it becomes a scanner pointed at other people's apps.

Regression contracts (wedge 3) are the retention mechanism. Each approved behaviour adds to a suite that keeps paying off, and this is the one capability with low commoditization risk. The repair controller (wedge 4) is how the product earns the word "autonomous" without burning the user's subscription in a loop.

**Wedge 5 is where recurring revenue most plausibly lives, and Contexer is furthest from it.** Product teams without a platform team are the buyer segment with demonstrated seat-priced willingness to pay for "prove it's safe". To serve them, the product needs four things:

- a GitHub check run
- checks stored next to the code
- dev environments that start the real app with seeded data and auth
- run history that answers a leader's "what share of agent work met acceptance without a human?"

Environment fidelity is exactly what Stripe, Ramp and Spotify spent most of their platform effort on. For a small team it is the main feasibility risk. The mitigation is to stay on standard web stacks, the same Vite/Next.js plus Supabase apps that vibe coders produce, and not chase enterprise monorepos.

**Wedges 6 through 11 are traps for this team.** Production feedback loops are being built by Cursor, GitHub and Datadog, and adoption is low. Cost governance and graduation tooling are real needs, but they are unrelated to Contexer's engine. Environment platforms are enterprise sales against free open-source frameworks and hosted vendor environments. Review bots and orchestration UIs are the two categories the evidence shows being bundled or dying.

Some smaller adjacent ideas have already been absorbed:

- **Parallel-agent merge-conflict resolution** has measured pain (20–28% conflict rates), but Agent HQ, VS Code agent merge and Replit Agent 4 already ship it ([GitHub](https://github.blog/news-insights/company-news/welcome-home-agents/)).
- **Spec tooling** has been absorbed into plan modes. Tessl, with $125M raised, has repositioned toward a free skills and context registry ([CodeMySpec](https://codemyspec.com/blog/tessl-review)).

### Charge per seat at the merge gate and per event at launch

The pricing evidence gives a clear envelope:

- **Teams:** about **$15–40 per developer per month, flat**, which matches CodeRabbit, Greptile, Bugbot and DX's non-authoring budget slice.
- **Avoid per-run metering** above a few dollars. Per-PR review pricing drew backlash, and DIY alternatives are free.
- **Founders:** the open space is between a $25–100 subscription and a $500 audit. A per-launch "readiness proof" or a low monthly guard tier fits there. This is an inference; no survey measures founders' willingness to pay for verification.

There is a distribution precedent. CodeRabbit joined the Claude Marketplace, which lets Anthropic customers spend existing commitments on it ([CodeRabbit](https://www.coderabbit.ai/newsroom)). TestSprite grew from about 6K to 35K users in about 90 days after shipping an MCP server for coding agents **[VEN claim]** ([i-programmer](https://www.i-programmer.info/news/90-tools/18421-testsprite-20-sees-user-growth.html)). That MCP model has a tension: the coding agent stays in charge and can ignore the result. Use MCP for reach, and keep the verdict and the gate outside the agent.

Four signals would kill or reshape the thesis:

- GitHub or Anthropic ships a blocking, runtime-verified acceptance gate that works across agents.
- Contexer's own benchmark shows a false-failure rate that users will not tolerate.
- Founders will not pay for proof before an incident. Octomind's failure to find market validation is the warning ([RFP.wiki](https://www.rfp.wiki/vendors/octomind)).
- Keeping real app stacks runnable (dev servers, auth, seeded data) costs more than a small team can sustain.

### Where the prototype is and is not a head start

Contexer is a **genuine head start for wedges 1, 3 and 4**. These are the hardest-to-fake parts of the engine:

- compiling intent into checks grounded in the actual UI
- a verdict owned outside the coding agent
- labels that separate browser-proven results from model judgment
- repair prompts generated from failed-check evidence rather than the agent's self-report

That design matches the evidence on reward hacking and on Spotify's judge failure better than any incumbent's self-test does.

It is a **partial head start for wedges 2, 5 and 6**. The harness and the `/verify` URL mode are the right base for security probes and live-URL replay, but none of the probe, identity, PR or CI machinery exists yet.

It is **no head start for wedges 7 through 11**, and the team should not drift into them.

Three gaps between the prototype and something people pay for matter more than any new feature:

1. **Accuracy.** Run the planned seeded-bug benchmark first and publish the catch rate and the false-failure rate. In this market the verifier *is* the product, and Anthropic's own lesson is that it "must be nearly perfect."
2. **Claude Code first, Codex next.** Claude Code reaches 66–71% of agent users. OpenCode is at about 10%, although it is the harness Ramp built Inspect on.
3. **Real stacks.** Vite and Next.js dev servers, plus login-protected flows, are where builders' own tests stop. Lovable's cannot handle external auth, for example.

On segment choice, the evidence supports the team's plan to prove the loop with Claude Code and Cursor graduates. They can run a CLI and their pain is acute. But they are the weakest wallet in the evidence: cost-motivated switchers, most not yet earning. The money evidence sits at **event-priced audits for founders** and **seat-priced PR gates for small product teams**. That argues for two changes:

- Pull the URL audit plus security proof forward as an early revenue test, rather than treating it as a later acquisition channel.
- Design the contract and evidence report from day one so they can become a GitHub check.

## Corrections that change how the evidence should be quoted

| Claim as often repeated | What the notes found | How to quote it |
|---|---|---|
| "METR found AI makes developers 18% slower (2026)" | The late-2025 study's "−18%" is less time per task, so a *speedup* for returning developers. Its CI (−38% to +9%) includes zero, and METR calls the data unreliable. Several outlets misreported it as a slowdown ([METR](https://metr.org/blog/2026-02-24-uplift-update/); [Pipeline Mag](https://pipelinemag.ai/posts/metr-broken-control-group-ai-coding-dependency/)) | Early-2025 RCT: 19% slower measured vs 20% faster believed. Late 2025: inconclusive, leaning toward a speedup |
| DORA: "25% more AI adoption means −1.5% throughput and −7.2% stability" | Looks like the 2024 finding. DORA 2025 found throughput *up* with instability also up ([SoftwareSeni](https://www.softwareseni.com/the-ai-verification-tax-and-the-dora-data-behind-the-trust-gap)) | Cite only the 2025 direction |
| Faros 2025: review time +91%, PR size +154%, bugs +9% | Seen only in secondary write-ups; correlational ([SoftwareSeni](https://softwareseni.com/the-ai-productivity-paradox-in-software-development-and-what-the-research-actually-shows)) | Prefer Faros 2026 primary figures, labelled vendor |
| Amazon's March 2026 outages were caused by AI code | FT report. Amazon says only one incident was AI-related, none involved AI-written code, and no senior sign-off rule exists ([Fortune](https://fortune.com/2026/03/11/elon-musk-amazon-outage-ai-relate-incident-meeting-report-cybersecurity)) | "Reported and disputed" |
| The Tea app breach was vibe coding | A legacy unprotected Firebase bucket; no source confirms AI generated the configuration ([Simon Willison](https://simonwillison.net/2025/Jul/26/official-statement-from-tea/)) | Do not use as a vibe-coding example |
| CVE-2025-48757 and Lovable's April 2026 flaw | Real scans and disclosures, but Lovable disputes the CVE, says the April flaw was "not a data breach", and the scope is contested ([Matt Palmer](https://mattpalmer.io/posts/statement-on-CVE-2025-48757/); [Computing](https://www.computing.co.uk/news/2026/security/lovable-flaw-exposed-source-code-credentials-and-ai-chats)) | Cite with the dispute noted |
| Escape: 2,000+ vulnerabilities in 5,600 apps | Its landing page says 2,038 critical across 1.4K apps; the figures conflict ([Escape](https://escape.tech/state-of-security-of-vibe-coded-apps)) | Vendor figure with an internal conflict |
| Stack Overflow 2026: "46% distrust, up from 31%"; "58% avoid agents" | Not in official material; may mix in 2025 data ([ByteIota](https://byteiota.com/stack-overflow-2026-survey-developers-use-ai-agents-but-actively-avoid-them/)). The 2025 agent-productivity figure is 52% in the page summary vs 68.7% in the data; the 2026 source-attribution figure is 78.7% vs 93% on different bases | Use the official 2026 figures only |
| Ramp 30% / 50% / 75%; Coinbase "95% of code"; Uber ">70% of PRs" | Ramp's figures conflict across sources. Coinbase's figure measures authorship, not autonomy. Uber's primary figure is 11%, and the 70% comes from an aggregator ([Summit](https://background-agents.com/summit/sessions/nikhil-ramakrishnan/)) | Quote ranges with dates; never compare across companies |
| Spotify's LLM judge as a reliability pillar | Presented as key in December 2025; removed as "too rigid" by March 2026 ([InfoQ](https://infoq.com/news/2026/03/spotify-honk-rewrite)) | Cite both |
| OpenAI harness team: "zero human review before merge" | The same summary describes humans making twice-daily mergeability calls; the primary post returned 403 ([ZenML](https://zenml.io/llmops-database/extreme-harness-engineering-building-production-software-with-zero-human-written-code)) | "Little human review, internally inconsistent account" |
| Boris Cherny's 259 PRs in 30 days; "verification improves quality 2–3x" | No primary source was found | Excluded |
| Claude Code at $8B or $15B run-rate; Cursor 2026 ARR; Cognition at $48B / ~$900M | Tracker or single-source numbers. The last official Claude Code figure is over $2.5B (February 2026) | Use disclosed figures only |
| Cross-agent PR pairs conflict 41.7% of the time | Cross-agent pairs are only 0.5% of co-active pairs ([arXiv](https://arxiv.org/abs/2607.04697)) | Headline 19.8% same-agent; 27.67% overall |
| Rescue costs, and the 2026 Claude Code weekly-limit changes (+25%, −17%) | Agency asking prices; the limit change has one unverified source ([MindStudio](https://www.mindstudio.ai/blog/claude-code-weekly-rate-limit-changes)) | Label as asking prices and as unverified |
| Greptile vs CodeRabbit review benchmarks | Each vendor's benchmark favours itself, and they contradict each other ([Macroscope](https://macroscope.com/content/best-greptile-alternatives-ai-code-review)) | Do not cite as evidence of quality |

## Conclusion

The question has moved from "can an agent write this?" to "who is allowed to say it is done?" Across both segments, the evidence says autonomy expands only where a trustworthy oracle exists. So the most valuable thing a layer above Claude Code and Codex can do is manufacture those oracles for user-facing behaviour and refuse to let the authoring agent grade itself. Generating more code or running more agents adds little. Incumbents cannot easily occupy that position, because they sell the tokens and grade their own agent's work. Independence is only worth paying for if the grader is accurate, so the first thing to prove is a low false-failure rate, not a longer feature list.

The money is not in the daily loop. It sits at two gates: the merge, where product teams pay seat prices for "prove it's safe", and the launch or incident, where founders pay hundreds to thousands for proof that strangers cannot read their data. Contexer already has the hardest-to-copy part, a verdict it owns. The work that turns it into a business is pointing that verdict at those two gates: real stacks, Claude Code, locked contracts, security proofs, and a check that can block.
