# Money and traction in AI-assisted software development (state as of mid-October 2026)

Labels used throughout: **[Disclosed]** = company or filing statement of a figure; **[Company claim]** = vendor marketing or self-reported metric, unaudited; **[Reported]** = press report citing sources; **[Estimate]** = third-party model (Sacra, Latka, ARR trackers); **[3rd-party/unverified]** = only found on blogs or aggregators, primary not checked. "Run-rate" / "annualized" figures are not booked revenue. Research date: 2026-10-14. Several pricing pages were fetched directly on that date (marked "fetched 2026-10-14").

## Q1. Current price points (late 2026) and recent pricing changes

### Takeaway
By October 2026 essentially every major coding-agent vendor has converged on a **$20 / ~$100 / ~$200 per-month ladder** with **metered credits or tokens and pay-as-you-go overage**. Flat "unlimited" or per-request pricing was dropped over 2025–2026, at Cursor (June 2025), Replit (2025), Augment (Oct 2025), Codex (Apr 2026), GitHub Copilot (Jun 2026) and Devin (spring 2026), and nearly every one of those changes drew a user backlash. Enterprise pricing is moving to "seat fee + usage at API rates".

### Cited Findings

**Anthropic (Claude Pro / Max / Team / Enterprise, Claude Code)**
- Prices on the pricing page (fetched 2026-10-14): Free has no Claude Code. Pro is $20/mo monthly or $17/mo annual ($200 up front). Max 5x is "from $100/mo". Team Standard seat is $25 monthly / $20 annual, and Team Premium seat is $125 monthly / $100 annual, for 2–150 seats. Enterprise is **$20/seat/mo plus usage at API rates**. Claude Code is included on Pro, Max, Team and Enterprise. Limits use a rolling 5-hour window plus **weekly limits**, shared across claude.ai and Claude Code. Pro and Max can turn on "usage credits" at API rates after hitting a limit. Max includes $100–200/mo of API credits, and Team includes up to $500/mo of pooled API credits. — [Claude pricing](https://claude.com/pricing)
- The Max 20x tier is $200/mo. The weekly rate limits for Pro ($20) and Max ($100/$200) took effect **Aug 28, 2025** to curb Claude Code power users. — [TechCrunch, 2025-07-28](https://techcrunch.com/2025/07/28/anthropic-unveils-new-rate-limits-to-curb-claude-code-power-users)
- 2026 limit changes [3rd-party/unverified]:
  - A temporary +50% Claude Code weekly boost ran **May 13 – Sep 13, 2026**. It was replaced on **Sep 14, 2026** by a permanent +25% over the pre-boost baseline, which is a net cut of about 17% versus the boosted level for Pro, Max, Team and seat-based Enterprise.
  - Separate 5-hour limits were reportedly raised at the Opus 5.5 launch (Sep 22, 2026). Only one source reports this.
  - Sources: [MindStudio](https://www.mindstudio.ai/blog/claude-code-weekly-rate-limit-changes); [bigguyonstuff](https://bigguyonstuff.com/claude-code-usage-limits-production/); [APIClaw](https://apiclaw.biz/blog/claude-code-rate-limits/); [Tygart Media](https://tygartmedia.com/claude-code-rate-limits/)
- **Claude Code Review** launched **Mar 9, 2026**:
  - Multi-agent PR review, initially a research preview for Team and Enterprise.
  - Billed on token usage, with a typical review costing **$15–25 per PR** and taking about 20 minutes.
  - Admins can set monthly spend caps per repo.
  - Sources: [Tessl blog](https://tessl.io/blog/anthropic-launches-ai-code-review-agents-that-scan-pull-requests-for-bugs); [CodeAnt](https://codeant.ai/blogs/anthropic-claude-code-review); [DEV Community](https://dev.to/umesh_malik/anthropic-code-review-for-claude-code-multi-agent-pr-reviews-pricing-setup-and-limits-3o35)

**OpenAI (ChatGPT plans / Codex)** [3rd-party/unverified; OpenAI pages not fetched]
- Lineup:
  - Codex is bundled into ChatGPT plans: Free, **Go $8**, **Plus $20**, and **Pro at $100, $200 and $500/mo**. Business is $20/user annual or $25 monthly.
  - Pro $100 is described as 5x Plus and Pro $200 as 20x Plus. The $500 tier is the only one with "Ultrafast" models.
  - Earlier-2026 articles list only Plus $20 and Pro $200, so the $100 and $500 tiers are recent.
  - Source: [MorphLLM Codex pricing](https://www.morphllm.com/codex-pricing)
- Billing method:
  - Since **Apr 2, 2026**, Codex usage is billed by tokens as credits rather than per message, on Plus, Pro, Business and new Enterprise plans.
  - Extra credits can be bought on Plus and Pro, or usage can run through an API key.
  - Sources: [UI Bakery](https://uibakery.io/blog/openai-codex-pricing); [CloudZero](https://www.cloudzero.com/blog/openai-codex-pricing/)
- Codex Cloud (background tasks) needs a paid plan. Free and Go get Codex only in the desktop app. — [pasqualepillitteri.it (DevDay 2026 summary)](https://pasqualepillitteri.it/en/news/19386/codex-cloud-web-mobile-devday-2026)

**Cursor (Anysphere, now owned by SpaceX/xAI)**
- **June 16, 2025:** Pro ($20) moved from "500 fast requests + unlimited slow" to "$20 of non-Auto model usage plus unlimited Auto". Users were surprised by overage charges and had no real-time usage view.
- **~July 4, 2025:** CEO Michael Truell apologized, and Cursor refunded unexpected charges incurred June 16 – July 4.
- **Aug 2025:** Teams moved to the same usage-based billing. Pro+ and Ultra ($200) tiers were added.
- Sources: [FinTech Weekly](https://www.fintechweekly.com/magazine/articles/cursor-pricing-change-user-backlash-refund); [Cursor forum "Clarifying Cursor Pro Pricing"](https://forum.cursor.com/t/clarifying-cursor-pro-pricing/113803); [Simon Willison](https://simonwillison.net/b/8818); [SaaS Price Pulse](https://www.saaspricepulse.com/blog/cursor-pricing-history)
- **Current tiers** (pricing page fetched 2026-10-14):

  | Tier | Price | Usage | Notes |
  |---|---|---|---|
  | Free | $0 | Limited | — |
  | Plus | **$8** | Base | Grok models only |
  | Premium | **$30** | 4x Plus | Adds cloud agents, automations, **Bugbot code review** and third-party models |
  | Super | **$100** | 15x Plus | — |
  | Ultra | **$200** | 50x Plus | — |
  | Teams | $30+/user | Pooled | — |
  | Enterprise | Custom | Pooled | — |

  Usage refreshes **weekly**. **Third-party models (e.g., Claude, GPT) are billed separately at API list price.** — [Cursor pricing](https://cursor.com/pricing)
- These tiers are part of **"The X Subscription"**, announced **Oct 12, 2026**:
  - It bundles Grok, Cursor and X Premium. Premium at $30 replaces SuperGrok + Cursor Pro + X Premium+, which previously totalled about $90.
  - Existing Cursor subscribers keep their current plans.
  - Sources: [xAI announcement](https://x.ai/news/x-subscription); [Teslarati](https://www.teslarati.com/spacex-just-combined-grok-cursor-and-x-into-one-mega-plan/); [TeslaNorth, 2026-10-12](https://teslanorth.com/2026/10/12/x-subscription-grok-cursor-premium-plans/)
- **Bugbot** (Cursor's AI PR reviewer) pricing history:
  - It was **$40/user/mo** (20% off yearly), flat for unlimited reviews on PRs a user authored. — [Cursor docs (legacy)](https://docs.cursor.com/bugbot/pricing); [Cursor legacy pricing page](https://cursor.com/docs/bugbot/legacy-pricing)
  - A "May 2026 pricing update" superseded that.
  - One aggregator says Bugbot moved to usage-based billing around **June 8, 2026** [3rd-party/unverified]. — [Dupple](https://dupple.com/learn/best-ai-code-review-tools)
  - It is now included from Premium up. — [Cursor pricing](https://cursor.com/pricing)

**GitHub Copilot**
- **June 1, 2026:** "premium requests" (with model multipliers) were replaced by **GitHub AI Credits**.
  - One credit is $0.01, metered on input, output and cached tokens at each model's rate.
  - Completions and next-edit suggestions are not metered.
  - Fallback to cheaper models was removed, so usage can stop when credits run out.
  - Sources: [GapVelocity](https://www.gapvelocity.ai/blog/github-copilots-new-usage-based-billing-what-changed-why-developers-are-upset-and-what-it-means); [Digital Applied](https://www.digitalapplied.com/blog/github-copilot-ai-credits-billing-2026-cost-audit-playbook); [WindowsForum](https://windowsforum.com/news/github-copilot-ai-credits-token-metering-replaces-premium-requests-what-it-means.423764/)
- Plans page (fetched 2026-10-14):

  | Plan | Price | Credits included (base + flex) |
  |---|---|---|
  | Pro | **$10** | $15 ($10 + $5) |
  | Pro+ | **$39** | $70 ($39 + $31) |
  | **Max** (new) | **$100** | $200 ($100 + $100) |
  | Business / Enterprise | Contact sales | — |

  Other details on the page:
  - The cloud coding agent is on Pro and above. Delegation to third-party agents is in preview on Pro+ and Max.
  - **From June 1, 2026, Copilot code-review workflows also consume GitHub Actions minutes.**
  - Source: [GitHub Copilot plans](https://github.com/features/copilot/plans)
- One developer reportedly used 822 credits on a single request, about 54% of a Pro+ monthly allocation [3rd-party/unverified]. — [GitHub Copilot credits explainers via search](https://blog.codercops.com/blog/github-copilot-ai-credits-pricing-2026)

**Cognition (Devin; Windsurf, now Devin Desktop)**
- Devin 2.0 (2025) cut the entry price from $500/mo to **Core at $20 + $2.25/ACU**. Team was $500/mo with 250 ACUs at $2.00 each. — [Lindy](https://www.lindy.ai/blog/devin-pricing); [fast.io](https://fast.io/resources/devin-ai-core-plan/)
- **March–April 2026** (sources differ on the month): Core and the $500 Team plan were retired.
  - Self-serve plans are now **Free, Pro $20, Max $200, Teams from $80/mo base + $40/seat**, with included daily and weekly quota plus on-demand usage billed in dollars.
  - Enterprise is still billed in ACUs at order-form rates.
  - Sources: [fast.io](https://fast.io/resources/devin-ai-core-plan.md); [Devin docs billing](https://docs.devin.ai/admin/billing.md) (docs confirm Free/Pro/Max/Teams and ACU billing for Enterprise; prices are from fast.io)
- Windsurf was shipped as **"Devin Desktop"** via an over-the-air update on **June 2, 2026**. — [Digital Applied](https://www.digitalapplied.com/blog/windsurf-becomes-devin-desktop-ide-migration-2026)

**Other agent and IDE vendors**
- **Augment Code:**
  - On **Oct 20, 2025** it moved from per-message plans to credit pools. Its stated reason was that one $250/mo Max user was "approaching $15,000 per month" in cost to Augment. — [Augment blog](https://www.augmentcode.com/blog/augment-codes-pricing-is-changing)
  - Kilo's test projected the $20 plan lasting 1–2 days and realistic spend of $300–600/mo [3rd-party test]. — [Kilo blog](https://blog.kilo.ai/p/testing-augment-codes-new-credit)
  - Further restructures followed: Feb 4, 2026 (top tier $200) and Aug 2026 (a Business plan at $100/mo for up to 50 seats, with usage at pass-through token cost) [3rd-party/unverified]. — [CostBench Feb 2026](https://costbench.com/changelog/augment-code-plans-renamed-2026-02/); [CostBench Aug 2026](https://costbench.com/changelog/augment-code-plan-removed-2026-08/); [usagepricing](https://usagepricing.com/blueprint/activity/augment-code-2026-08-11-price-change)
- **Amp (spun out of Sourcegraph):**
  - It became a standalone company around **Dec 2, 2025**. — [Tessl blog](https://tessl.io/blog/sourcegraph-spins-out-ai-coding-agent-amp-as-a-standalone-company/); [HackerNoon](https://hackernoon.com/sourcegraph-spins-out-amp-to-chase-the-ai-coding-frontier)
  - An ad-supported **"Amp Free"** tier launched **Oct 15, 2025** with about $10/day of usage. It reportedly reached a **$10M+ run-rate** before ads were removed in **March 2026**. Paid usage is pass-through API pricing with zero markup [3rd-party/unverified]. — [Ry Walker research](https://rywalker.com/research/amp-sourcegraph); [Tech Insider](https://tech-insider.org/?p=18762)
  - Sourcegraph's Cody is now Enterprise-only, starting around $16K [3rd-party]. — [usagepricing](https://usagepricing.com/blueprint/activity/2026-06-08-sourcegraph-cody-enterprise-only)
- **Factory (Droids):** $20–$200/mo self-serve range [3rd-party]. — [AI Agent Index](https://theaiagentindex.com/agents/factory-ai)

**Vibe-coding / app builders**
- **Replit** (pricing page fetched 2026-10-14):
  - **Core $20/mo** ($18 annual) includes $20 toward models. **Pro $100/mo** ($90 annual) includes **10 parallel agents** and $100 toward models.
  - Agent work uses "effort-based pricing (pay-as-you-go)".
  - Source: [Replit pricing](https://replit.com/pricing)
- Replit backlash:
  - Effort-based pricing replaced a flat $0.25 per checkpoint. Agent 3 (Sept 2025) triggered bill-shock complaints, for example "$1K in the last week" versus $180–200/mo before, and small tasks rising from $0.25 to about $2. — [The Register, 2025-09-18](https://www.theregister.com/2025/09/18/replit_agent3_pricing/)
  - Dates for the switch conflict across sources (mid-2024, June 2025, or July 1, 2026 for existing Core/Teams subscribers). — [usecarly](https://www.usecarly.com/blog/replit-agent-pricing-explained); [Banani](https://www.banani.co/blog/replit-pricing)
- **Lovable:** Free tier gives 5 daily build credits (up to 30/mo). Paid tiers are Pro, Business and Enterprise. Top-up credits last 12 months. The fetched page did not show dollar amounts. — [Lovable pricing](https://lovable.dev/pricing)
- **Bolt.new** (fetched 2026-10-14): Free gives 1M tokens/mo. **Pro is $25/mo starting at 10M tokens**, with rollover up to 2 months. Teams is $30/member/mo. — [Bolt pricing](https://bolt.new/pricing)
- **v0 (Vercel)** (fetched 2026-10-14):
  - Free is limited to 7 messages/day. **Plus is $30/user/mo** ($30 credits + $2/day login credits). **Business is $100/user/mo**.
  - Overage is metered per million tokens, from v0 Mini at $0.20 in / $1.20 out to v0 Max Fast at $10 / $50.
  - Source: [v0 pricing](https://v0.app/pricing)

### Inferences
- Price anchors are now shared across vendors:
  - **$20** is the entry agent tier: Claude Pro, ChatGPT Plus, Devin Pro, Replit Core and Cursor's legacy Pro.
  - **$100** is the "serious individual" tier: Claude Max 5x, ChatGPT Pro $100, Copilot Max, Cursor Super, Replit Pro.
  - **$200** is the power-user tier: Claude Max 20x, ChatGPT Pro $200, Cursor Ultra, Devin Max.
  - Any "layer above" product will be judged against these anchors.
- Every vendor has given up on flat pricing for agentic work, because agent token consumption is unbounded. The Augment $250 → $15K example is the clearest primary evidence.
  - This creates a **cost-visibility and spend-control problem** that buyers repeatedly complain about.
  - Usage dashboards, caps and refunds were the backlash points at Cursor, Replit, Copilot and Augment.
- Platform owners now bundle review into their own tiers:
  - Anthropic sells review per PR ($15–25).
  - Cursor folded Bugbot into its $30+ tiers.
  - Copilot code review is now metered through credits and Actions minutes.
- Cursor's post-acquisition pricing pushes Grok as the bundled model and bills Claude/GPT at API list price. This may push Claude-loyal users toward Claude Code directly. This is an inference from the pricing page structure, not a reported outcome.

### Gaps
- Windsurf/Devin Desktop current seat pricing was not found.
- Current Bugbot usage-based rates were not found; the current docs URL returned 404.
- Lovable dollar price points: the page fetch returned no amounts.
- Factory pricing came only from a third-party directory.
- OpenAI Codex pricing could not be checked against OpenAI's own pages, and third-party sources conflict on the 5-hour limits for Plus.
- No Anthropic primary source was fetched for the September 2026 weekly-limit change.

## Q2. Revenue/ARR, adoption and enterprise budgets for AI coding

### Takeaway
The money is concentrated in a few model-owning or agent-owning players:
- **Claude Code**: more than $2.5B run-rate, disclosed Feb 2026.
- **Cursor**: about $1B (Nov 2025) to a reported ~$2–4B (2026), then sold to SpaceX for $60B.
- **Lovable**: more than $600M (Sep 2026).
- **Cognition**: $492M disclosed (May 2026), with about $900M reported (Sep 2026).
- **Replit**: an estimated $240–525M.
- **GitHub Copilot**: 4.7M paid subscribers (Jan 2026).

Enterprise surveys show coding is the single largest enterprise AI application category: Menlo estimates **$4.0B in 2025, 55% of departmental AI spend**. Per-developer budgets are converging on about **$1,000/dev/year** as a 2026 target, with heavy teams paying $100–200/dev/month.

### Cited Findings

**Anthropic / Claude Code**
- **Feb 12, 2026** [Disclosed], from the Series G announcement: $30B raised at a $380B post-money valuation.
  - Company run-rate was **$14B**.
  - **Claude Code run-rate was over $2.5B**, more than doubled since the start of 2026.
  - Weekly active Claude Code users doubled since Jan 1, and business subscriptions quadrupled.
  - **Enterprise accounts for more than half of Claude Code revenue.**
  - Source: [Anthropic news](https://www.anthropic.com/news/anthropic-raises-30-billion-series-g-funding-380-billion-post-money-valuation)
- Earlier Claude Code milestones:
  - About $400M ARR by July 2025 [Estimate]. — [Sacra via search summary](https://sacra.com/research/warp)
  - More than $500M run-rate by Sep 2025 and **$1B by Nov 2025** [3rd-party/unverified]. — [Gradually.ai](https://www.gradually.ai/en/claude-code-statistics/); [getpanto](https://www.getpanto.ai/blog/claude-ai-statistics)
- Anthropic company run-rate:
  - Reached **$30B** (April 2026) [Company claim, reported]. — [VentureBeat](https://venturebeat.com/technology/anthropic-says-it-hit-a-30-billion-revenue-run-rate-after-crazy-80x-growth)
  - Later figures of about $47B (May 2026) and $65B (end of July 2026) appear only on aggregators [3rd-party/unverified]. — [CodeConductor](https://codeconductor.ai/blog/claude-code-anthropic-profitability/)
  - Claude Code figures of $8B or $15B appear on trackers but are **not** Anthropic disclosures. No official Claude Code figure after Feb 2026 was found. — [Claudify](https://claudify.tech/blog/state-of-claude-code-2026)

**Cursor / Anysphere**
- **Nov 13, 2025:** $2.3B Series D at a **$29.3B** valuation, co-led by Accel and Coatue. Cursor said annualized revenue had passed **$1B** [Disclosed]. — [Wikipedia: Cursor (company)](https://en.wikipedia.org/wiki/Cursor_(company)); [Silicon Canals](https://siliconcanals.com/t-cursor-100-million-2-billion-annualized-revenue-13-months/)
- Later revenue figures [Reported; not company-disclosed]:
  - About **$2B** in Feb 2026.
  - **$3B** in May 2026 (Wikipedia).
  - About **$4B** in June 2026 (Forbes, cited by aggregators).
  - Sources: [Silicon Canals](https://siliconcanals.com/t-cursor-100-million-2-billion-annualized-revenue-13-months/); [Wikipedia](https://en.wikipedia.org/wiki/Cursor_(company)); [Latka (estimate)](https://getlatka.com/companies/cursor.com)
- Before its first enterprise sales rep, Cursor reached $200M in revenue and "captured significant share" from Copilot. — [Menlo Ventures, 2025-12-09](https://menlovc.com/perspective/2025-the-state-of-generative-ai-in-the-enterprise/)
- Acquisition by SpaceX/xAI:
  - **April 2026:** xAI took an option to buy Cursor for **$60B** or pay $10B for a collaboration.
  - **June 16, 2026:** SpaceX exercised the option to buy.
  - **Aug 14–15, 2026:** The all-stock deal closed, at about 389–391M SpaceX Class A shares. Cursor now sits in the SpaceXAI division.
  - These are secondary sources; the 8-K was not checked. — [GIGAZINE](https://gigazine.net/gsc_news/en/20260816-spacex-officially-closes-cursor-acquisition/); [SentiSight](https://www.sentisight.ai/spacex-cursor-acquisition-closed/); [Tech Insider](https://tech-insider.org/cursor-60-billion-valuation-anysphere-ai-coding-2026/)

**Cognition (Devin + Windsurf)**
- Windsurf had **$82M ARR** at acquisition (July 2025), with 350+ enterprise customers [Disclosed]. — [Cognition blog](https://cognition.com/blog/windsurf)
- Funding and run-rate:
  - **Sept 2025:** $400M at a $10.2B valuation.
  - **May 27, 2026:** a Series D of more than $1B at $25B pre-money (about $26B post), led by Lux, General Catalyst and 8VC. **Run-rate was $492M** and enterprise usage was more than 10x since the start of 2026 [Disclosed]. — [Let's Data Science](https://letsdatascience.com/news/cognition-raises-1-billion-at-26-billion-valuation-5abc3f35); [Creeta](https://news.creeta.com/en/cognition-series-d-26b-valuation-2026/)
  - **July 2026:** Cognition said run-rate grew from $73M to $500M+ in the year since buying Windsurf [Company claim]. — [Mungomash](https://mungomash.com/orgs/cognition/financials/)
  - **Sep 8, 2026:** a reported Series E of $2B+ at **$48B**, with run-rate "almost $900M" [Reported; single source]. Bloomberg earlier reported talks at $40B or more. — [Unite.AI](https://www.unite.ai/?p=463367); [RuntimeWire](https://runtimewire.com/article/cognition-1-billion-funding-47-billion-valuation)

**Lovable**
- Run-rate history:
  - About $200M (Nov 2025).
  - **$400M** (Feb/Mar 2026).
  - **$500M** (June 2026, company-stated, with about 1M new projects per week).
  - **$600M+** (Sep 23–24, 2026, stated by co-founder Fabian Hedin at HumanX and reported by TechCrunch) [Company claim].
  - Sources: [Digg/TechCrunch](https://digg.com/tech/mrj2cqxj); [kingy.ai](https://kingy.ai/?p=931707); [Dealroom](https://dealroom.co/news/talk-xveOgrL5UC4-lovable-passes-600m-annual-run-rate-revenue-at-humanx-amsterdam/); [themodelwire](https://themodelwire.com/article/lovable-says-it-has-hit-500m-in-annualized-revenue-with-1-million-new-projects-a-01KTP9ER5ES52B549PNSC4C5ZY)
- Funding:
  - About $1.8B valuation (July 2025).
  - $330M at **$6.6B** (Dec 2025).
  - A **$400M Series C at $13.3B** (Aug 2026), led by Menlo Ventures and the Scaleup Europe Fund.
  - Sources: [Techzine](https://www.techzine.eu/news/devops/143582/lovable-valued-at-13-3-billion-after-new-funding/); [Northeast Times](https://northeasttimes.com/2026/08/13/lovable-the-app-building-startup-just-doubled-its-value-to-13-3-billion/)
- Lovable claims "two-thirds of Fortune 500" use it [Company claim]. — [kingy.ai](https://kingy.ai/?p=931707)

**Replit**
- Funding: $250M at **$3B** (Sep 2025), then **$400M at $9B** (Mar 2026), led by Georgian with a16z, Coatue and YC. Visa made a strategic investment in May 2026.
- Revenue figures conflict:
  - Sacra estimates **$525M annualized (Apr 2026)**, up from $300M at the end of 2025 [Estimate].
  - Other reports say about $240M ARR with 150K+ paying customers [Reported].
  - The company targets **$1B ARR by end of 2026**.
  - Sources: [Sacra](https://sacra.com/research/replit); [Ecosistema Startup](https://ecosistemastartup.com/?p=66976); [Olostep](https://www.olostep.com/answers/why-replit-9b-valuation-looks-cheap)

**GitHub Copilot**
- **4.7M paid subscribers**, up 75% YoY, per Microsoft's FY26 Q2 earnings call (**Jan 28, 2026**). Copilot Pro+ subscriptions grew 77% QoQ. Microsoft switched from reporting "users" (about 20M cumulative by July 2025) to "paid subscribers" [Disclosed, via secondary]. — [WindowsForum](https://windowsforum.com/news/microsoft-copilot-hits-15-million-paid-seats-and-4-7-million-github-subscribers.400630/); [aibusiness.vc](https://aibusiness.vc/b2b/github-copilot-2b-arr)
- Copilot revenue is not broken out. Estimates range from about $0.45B to $1.1B ARR [Estimate]. — [The Brief Script](https://thebriefscript.com/github-copilot-revenue-2026/)

**Other agent and IDE companies**
- **Factory:**
  - **$150M Series C at $1.5B** (Apr 16–17, 2026), led by Khosla with Sequoia, Insight and Blackstone.
  - **$200M at $5B** (Sep 15, 2026).
  - Sacra-sourced estimate: about $5M annualized (Dec 2025) growing to about **$60M** (Mar 2026) [Estimate].
  - Customers include NVIDIA, Adobe and MongoDB.
  - Sources: [Tech Insider](https://tech-insider.org/factory-ai-150-million-series-c-khosla-coding-droids-2026/); [Seedtable](https://seedtable.com/companies/factory/funding-rounds/other-2026-09); [CODERCOPS](https://blog.codercops.com/blog/factory-ai-200-million-funding-2026)
- **Warp:** ARR "grew 35x last year" and enterprise revenue rose more than 500% since Q4 2025, per an OpenAI customer story dated May 27, 2026 [Company claim]. About 700K active developers (CEO, podcast). A modelled revenue estimate is about $29M [Estimate]. — [OpenAI: Warp](https://openai.com/index/warp); [StartupHub](https://www.startuphub.ai/startups/warp.md); [EveryDev](https://www.everydev.ai/developers/warp)
- **Bolt.new (StackBlitz):** **$40M ARR by March 2025**, with 3M+ registered users. $105M Series B at about $700M (Jan 2025). No 2026 primary ARR was found. — [Dealroom](https://midlands.dealroom.co/news/note/bolt-new-by-stackblitz-20m-arr-in-2-months); [ToolJunction](https://www.tooljunction.io/ai-tools/bolt-new/company)

**Enterprise budgets and surveys**
- **Menlo Ventures, "2025: The State of Generative AI in the Enterprise" (Dec 9, 2025)**, based on 495 US enterprise AI decision-makers surveyed Nov 7–25, 2025, plus a market model:
  - Enterprise gen-AI spend was **$37B** in 2025, up from $11.5B.
  - Departmental AI spend was $7.3B. **Coding was $4.0B, 55% of departmental spend**, up from $550M in 2024 (about 7x). Code completion was $2.3B, and agents and app builders grew from near zero.
  - **Anthropic holds about 54% coding model share**, up from 42% six months earlier. **OpenAI holds 21%.**
  - **50% of developers use AI coding tools daily**, and 65% in top-quartile organizations.
  - Users in frontier use cases like coding are "quite price-insensitive" and "will pay more for performance".
  - Source: [Menlo Ventures report](https://menlovc.com/perspective/2025-the-state-of-generative-ai-in-the-enterprise/)
- **a16z CIO survey** (100 Global 2000 CIOs): average enterprise LLM spend went from about $2.5M (2024) to about $7M (2025), with about $11.6M expected for 2026 (+65%). Expected 2026 model-spend share is OpenAI 53%, Anthropic 18% and Google 18%. There is no coding-specific breakout. — [The Decoder](https://the-decoder.com/?p=31599)
- **DX (Oct 2025)**, from 50 budget holders plus a 275-leader poll:
  - Nearly half allocate **1–3% of total engineering budget** to AI tools.
  - 2025 per-developer spend: 38.4% spent $101–500/dev/yr, 10.5% spent $501–1,000, and 10.5% spent more than $1,000.
  - **$1,000/dev/yr is the common 2026 target**. The range is about $500 at the low end to $3,000+ for multi-tool setups.
  - Source: [DX blog](https://getdx.com/blog/how-are-engineering-leaders-approaching-2026-ai-tooling-budget/)
- **Pragmatic Engineer AI tooling survey** (906 responses, Jan 27 – Feb 17, 2026; published Mar 3, 2026):
  - **Claude Code is the most-used and most-loved tool (46% "most loved").**
  - Among regular agent users, 71% use Claude Code, 46% Copilot and 39% Cursor.
  - **70% use 2–4 tools at once.**
  - Codex, Gemini CLI, OpenCode and Antigravity are each at about 10%+.
  - Source: [Pragmatic Engineer](https://newsletter.pragmaticengineer.com/p/ai-tooling-2026)
- The same survey's spend findings, as reported secondhand [secondary summary of a paywalled survey]:
  - Employers pay more often than individuals, and employers buy pricier packages.
  - Companies commonly pay for "max" plans at **about $100–200/mo per engineer**, though some budgets stretch only to about $20.
  - **About 30% have hit usage limits.**
  - About 15% mention cost concerns.
  - Source: [aiproductivity.ai](https://aiproductivity.ai/news/pragmatic-engineer-survey-ai-tooling-2026/)
- Agentic teams spend **$200–$2,000+/engineer/month in tokens** on top of seats [Vendor benchmark; treat cautiously]. — [Larridin](https://larridin.com/developer-productivity-hub/developer-productivity-benchmarks-2026)

### Inferences
- Coding is a proven budget line, and the dominant spend flows to model owners or their closest distribution:
  - Anthropic holds 54% coding share, and Claude Code alone was above $2.5B by Feb 2026.
  - Cursor's value was ultimately captured via acquisition by a model owner (xAI/SpaceX).
- Two buyer segments pay at scale:
  - **professional developers via employers**, at $20–200/seat/mo plus usage;
  - **non-developer "vibe coders"**, via app builders (Lovable at $600M+ and Replit).
- Growth rates in 2026 (2–5x in a matter of months) make 2025 market-sizing numbers stale quickly. Menlo's $4B 2025 coding number is likely far below the 2026 run-rate, since Claude Code alone was above $2.5B in Feb 2026.

### Gaps
- No Gartner or IDC 2026 AI-coding spend figures were found. The web search budget ran out before targeted searches were possible.
- No official OpenAI Codex revenue figure was found.
- No official Claude Code run-rate after Feb 2026 was found.
- Cursor 2026 ARR comes only from press, and the SpaceX 8-K was not checked.
- Replit ARR estimates conflict ($240M vs $525M).
- Bolt 2026 ARR was not found.

## Q3. Products built as a "layer above the coding agent": traction, funding, failures

### Takeaway
**AI code review is the one layer-above wedge with clear, venture-scale traction:**
- CodeRabbit raised at **$1.5B (Aug 2026)** with revenue up 5x+ YoY and an estimated ARR of about $50M.
- Graphite was bought by Cursor (Dec 2025).
- Qodo raised a $70M Series B (Mar 2026).
- Greptile raised a $25M Series A from Benchmark.

**Pure orchestration and parallel-agent UIs mostly failed to monetize:**
- Terragon shut down (Feb 2026).
- Vibe Kanban/Bloop shut down (Apr 2026), saying most users were free.
- Conductor and Sculptor are free and bring-your-own-subscription.

**Background-agent platforms split:**
- Well-funded full-stack players (Cognition, Factory) scaled.
- Thin wrappers were acquired or shut down: Codegen went to ClickUp, and Tembo shut its cloud service.

**AI QA/testing is mixed:**
- Momentic and Meticulous each raised a $15M Series A, and TestSprite grew via MCP.
- Octomind shut down (mid-2026) for lack of market validation.

### Cited Findings

**AI code review**
- **CodeRabbit:**
  - Funding [Disclosed]:
    - Series A of $16M (Aug 13, 2024; CRV).
    - **Series B of $60M at $550M** (Sep 16, 2025; Scale Venture Partners, with NVentures).
    - **Series C of $143M at $1.5B** (Aug 12, 2026; Atomico and Smash Capital, with BMW i Ventures and Datadog as new investors).
    - Axios reported revenue **up more than 5x YoY**.
  - Product and distribution moves:
    - Issue Planner beta (Feb 10, 2026).
    - Slack Agent (Apr 22, 2026).
    - **Joined the Claude Marketplace (May 27, 2026), so Anthropic customers can apply existing spend commitments to CodeRabbit.**
    - "Agentic Change Management" (Aug 12, 2026).
  - Ranked #15 fastest-growing software vendor of 2025 by Brex spend data (Fortune, Dec 23, 2025).
  - Sources: [CodeRabbit newsroom](https://www.coderabbit.ai/newsroom); [SaaSRise](https://www.saasrise.com/deals/nvidia-backed-startup-coderabbit-valued-at-15-billion-in-round-5956b336-a8e0-4421-8234-b1b4973dd9c3); [The Next Web](https://thenextweb.com/news/coderabbit-raised-143m-to-read-the-code-ai-wrote)
  - ARR [Estimate]:
    - Sacra: about $25M at end-2025, growing to **about $50M by July 2026**. — [Sacra](https://sacra.com/c/coderabbit/)
    - ARR Club: $15M (Sep 2025) to $40M (Jun 2026). — [ARR Club](https://www.arr.club/coderabbit)
  - Pricing: Pro is about $24/dev/mo annual or $30 monthly, with unlimited reviews. The free tier covers public repos [3rd-party]. — [Dupple](https://dupple.com/learn/best-ai-code-review-tools); [CostBench](https://www.costbench.com/compare/coderabbit-vs-greptile/)
  - Research (Dec 17, 2025): in 470 OSS PRs, AI-written code had about 1.7x more issues than human code [Company research]. — [CodeRabbit newsroom](https://www.coderabbit.ai/newsroom)
- **Greptile:**
  - **$25M Series A led by Benchmark (Sep 2025)**, with YC and Initialized. TechCrunch had earlier reported talks at $30M on a $180M valuation.
  - No Series B was found.
  - Pricing: **$30/seat/mo including 50 reviews, then $1 per review**. Free for OSS, and 50% off for small startups.
  - Sources: [SiliconANGLE, 2025-09-23](https://siliconangle.com/2025/09/23/greptile-bags-25m-funding-take-coderabbit-graphite-ai-code-validation/); [Sacra](https://sacra.com/c/greptile); [aicodereview.cc](https://aicodereview.cc/blog/greptile-pricing)
- **Graphite (with its AI reviewer Diamond):**
  - **$52M Series B led by Accel (Mar 2025)**. Last valuation was about $290M.
  - **Cursor agreed to acquire Graphite on Dec 19, 2025.** The price was undisclosed, in cash and equity. Axios said Cursor paid "way over" $290M.
  - Cursor's stated rationale: writing code got faster, so review, safe merging and collaboration are now the bottleneck.
  - Graphite is used by "hundreds of thousands of engineers" (Cursor) or "500+ companies" including Shopify, Snowflake, Figma and Perplexity (SiliconANGLE).
  - It keeps operating independently, with integrations planned through 2026.
  - Sources: [Cursor blog](https://cursor.com/blog/graphite); [TechCrunch, 2025-12-19](https://techcrunch.com/2025/12/19/cursor-continues-acquisition-spree-with-graphite-deal); [SiliconANGLE](https://siliconangle.com/2025/12/19/cursor-acquires-ai-code-review-startup-graphite/)
- **Qodo:** **$70M Series B (Mar 30, 2026)**, led by Qumra Capital, bringing the total to about $120M. Angels include Peter Welinder (OpenAI). The prior round was a $40M Series A (Sep 2024). — [Munich Startup](https://insights.munich-startup.de/news/feed/qodo-raises-70m-as-ai-generated-code-outpaces-human-review-capacity); [CXO Digital Pulse](https://www.cxodigitalpulse.com/ai-code-platform-qodo-secures-70m-to-scale-enterprise-adoption/)
- **Cheap review tiers:** Sourcery Pro is about $12/mo, and Bito about $12/seat [3rd-party]. — [Dupple](https://dupple.com/learn/best-ai-code-review-tools)

**Orchestration / parallel-agent UIs**
- **Terragon** (cloud orchestrator for Claude Code, Codex and other CLIs; promoted by Sawyer Hood):
  - **It announced its wind-down on Jan 11, 2026 and shut down on Feb 9, 2026**, terminating all sandboxes and open-sourcing the code.
  - The shutdown page recommends **Claude Code on the web and Codex Web** as alternatives.
  - Sources: [Terragon OSS repo](https://github.com/terragon-labs/terragon-oss); [CodeHerder](https://codeherder.com/alternatives/terragon/); [Sawyer Hood on X](https://x.com/sawyerhood/status/1938263088836579536)
- **Vibe Kanban (Bloop):**
  - **Bloop shut down on Apr 10, 2026.** "Thousands of engineers use Vibe Kanban daily", but "the vast majority are free users", and they "couldn't find a business model that we could get excited about".
  - The project continues as community open source (Apache 2.0). Recent invoices were refunded.
  - Sources: [Vibe Kanban shutdown post](https://vibekanban.com/blog/shutdown); [Nimbalyst](https://nimbalyst.com/blog/vibe-kanban-after-bloop-whats-next/)
- **Conductor (Melty Labs, YC S24):**
  - A macOS app running parallel Claude Code and Codex agents in git worktrees.
  - **The app is free, and users bring their own Claude Pro/Max or API key.**
  - Funding is unverified and conflicting ($2.8M per EveryDev vs about $24.5M per DevTune).
  - Sources: [MorphLLM](https://www.morphllm.com/conductor-ai-coding); [EveryDev](https://www.everydev.ai/developers/conductor); [DevTune](https://devtune.ai/verticals/coding-agent-orchestration/conductor)
- **Sculptor (Imbue):** runs parallel Claude Code and Codex agents in Docker containers. **Free in beta, with users supplying their own keys or subscription.** No published commercial pricing as of June 2026 [3rd-party]. — [Ry Walker research](https://rywalker.com/research/sculptor); [usagepricing](https://www.usagepricing.com/blueprint/imbue)
- **Traycer:** an open-source desktop app and "nerve center" for running coding agents in parallel. No funding found. — [Traycer docs](https://docs.traycer.ai/); [GitHub](https://github.com/traycerai/traycer)
- **Warp:** repositioned from a terminal to an "agentic development environment", with Oz cloud orchestration across local and cloud agents. Revenue growth and user claims are listed under Q2. — [OpenAI: Warp](https://openai.com/index/warp); [Sacra](https://sacra.com/c/warp)

**Background-agent platforms**
- **Cognition/Devin** and **Factory:** see Q2 for the large raises and run-rates. Factory 2.0 extends into code review, security analysis, documentation, QA and incident response. — [Tech Insider](https://tech-insider.org/factory-ai-150-million-series-c-khosla-coding-droids-2026/)
- **Codegen:** **acquired by ClickUp (late 2025).** The standalone product shut down **Jan 9, 2026**, and founder Jay Hack reportedly became ClickUp's Head of AI. Prior funding was a $16.2M seed (Thrive, July 2023). — [YesPress](https://yespress.io/products/codegen); [Codegen site](https://codegen.com/ai-tools/codegen/); [Dealroom](https://dealroom.co/companies/codegen/)
- **Tembo:** about $20M raised, including a $14M Series A led by GreatPoint [Company claim]. It **shut down its earlier cloud service and rebuilt around "autonomous software maintenance"**. — [Ry Walker research, checked 2026-09-15](https://rywalker.com/research/tembo)
- **OpenHands (All Hands AI):**
  - $5M seed (Sep 2024) and an **$18.8M Series A (Nov 18, 2025)** led by Madrona, with Menlo participating.
  - It launched an "Agent Control Plane" on May 6, 2026.
  - No 2026 round was found.
  - Sources: [OpenHands press](https://hub.openhands.dev/press); [CB Insights](https://www.cbinsights.com/company/all-hands/financials)
- **Cosine:** about $2.5M seed (Aug 2024; total $3.5–8M by source). In April 2026 it was chosen as a UK Sovereign AI partner, receiving 500K GPU hours and an option for the government venture arm in its next round. — [UKTN](https://www.uktech.news/ai/uk-ai-startup-cosine-developer-20240813); [Tech.eu, 2026-04-17](https://tech.eu/2026/04/17/cosine-goes-from-benchmark-leader-to-cornerstone-of-uk-sovereign-ai-strategy/)
- **Charlie Labs:** seed round June 2025 (Abstract, Maple VC, The General Partnership), with 7 employees. Amount undisclosed. — [PitchBook](https://pitchbook.com/profiles/company/877090-69)

**AI QA / testing / verification**
- **Momentic:**
  - $3.7M seed (Mar 2025), then a **$15M Series A (Nov 24, 2025)** led by Standard Capital with Dropbox Ventures and YC. It is pitched as a **"verification layer for software"**.
  - Customers include Notion, Quora, Webflow and Xero.
  - It claims 200M+ steps per month and 390K bugs found [Company claim].
  - TechCrunch flagged competitive pressure from foundation-model providers offering agentic testing.
  - Sources: [TechCrunch, 2025-11-24](https://techcrunch.com/2025/11/24/momentic-raises-15m-to-automate-software-testing); [Momentic blog](https://momentic.ai/blog/series-a)
- **Meticulous:** **$15M Series A led by Chemistry, with Menlo** (dated Jul 15, 2026). It auto-generates and maintains UI-flow regression tests. Customers include Notion, ElevenLabs, Dropbox, Wiz and LaunchDarkly. — [Pulse 2.0](https://pulse2.com/meticulous-raises-15-million-series-a-led-by-chemistry/); [citybiz](https://www.citybiz.co/article/916256/meticulous-raises-15m-series-a-led-by-chemistry-to-expand-ai-software-testing/)
- **TestSprite:**
  - **$6.7M seed (Oct 2025)** led by Trilogy, about $8.1M in total.
  - **Users grew from about 6K to 35K+ in about 90 days after its MCP server launched (Jul 15, 2025)**. The server is pitched as "the first testing agent designed to work alongside coding agents" (Cursor, Copilot).
  - A later claim of 100K+ developers is unverified.
  - Sources: [i-programmer](https://www.i-programmer.info/news/90-tools/18421-testsprite-20-sees-user-growth.html); [citybiz](https://www.citybiz.co/?p=764616)
- **QA Wolf** (a managed QA service): its latest round was a **$36M Series B (July 2024)** led by Scale VP, about $56–57M in total. No 2026 ARR or round was found. — [Scale VP / PR Newswire](https://www.scalevp.com/press/qa-wolf-raises--36-million-series-b-and-opens-waitlist-for-android-and-ios-test-automation)
- **Octomind** (an AI Playwright E2E testing company with a $4.8M seed led by Cherry Ventures, Apr 2024):
  - **The product was switched off at the end of May 2026, and the company wound down by the end of June 2026.**
  - The farewell letter, as quoted by secondary sources, says "We didn't find the market validation we needed to keep going". It also says the problem is "only getting more urgent as AI agents write more of the code".
  - The octomind.dev domain did not resolve (DNS failure) when fetched on 2026-10-14.
  - Sources: [RFP.wiki](https://www.rfp.wiki/vendors/octomind); [TestMu migration page](https://www.testmuai.com/octomind-alternative/); [Tech.eu, 2024](https://tech.eu/2024/04/23/octomind-raises-4-8m-for-ai-powered-web-testing/)
- **Checksum:** about $2M ARR, bootstrapped [Estimate]. — [Latka](https://getlatka.com/companies/checksum.ai)
- **Bug0:** no funding found. Bug0 publishes content arguing that AI-assisted development did not shrink QA budgets (a "2026 Quality Tax"). — [Bug0 blog](https://bug0.com/blog/the-2026-quality-tax-ai-assisted-development-qa-budget)

**Spec / planning**
- **Tessl:**
  - **$125M in total**: a $100M Series A led by Index and a $25M seed from boldstart and GV, announced Nov 14, 2024 at about a $750M valuation.
  - A mid-2026 review calls spec-as-source "still mostly a thesis".
  - Tessl now offers a free agent-skills and context registry and CLI that works with Claude Code, Cursor and Gemini, which is a repositioning from its original pitch.
  - Sources: [Fortune, 2024-11-14](https://fortune.com/2024/11/14/tessl-funding-ai-software-development-platform); [CodeMySpec review](https://codemyspec.com/blog/tessl-review)
- **CodeRabbit Issue Planner** (Feb 10, 2026) moved review vendors into planning. — [CodeRabbit newsroom](https://www.coderabbit.ai/newsroom)

### Inferences
- **What worked:** products that are (a) **agent-neutral**, working across Claude Code, Codex, Cursor and Copilot and across GitHub, GitLab and Bitbucket; (b) **sold per seat to teams or engineering leaders** rather than to individuals; and (c) attached to a **merge-gate artifact** such as the PR. CodeRabbit is the clearest case.
  - Review tools also have a measurable story ("AI code has 1.7x more issues") that maps to an existing budget for quality, security and compliance.
- **What failed:** **local or cloud UIs that orchestrate someone else's agent** (Terragon, Vibe Kanban), where users already pay $20–200/mo to the agent vendor and refuse a second subscription for a UI.
  - The model owners then shipped the same feature: cloud or background agents, parallel worktrees and agent views.
  - Several survivors (Conductor, Sculptor, Traycer) are free or open source and BYO-subscription, so they do not yet show a monetization model.
- **Testing/QA:** demand exists (Momentic, Meticulous, TestSprite raised), but standalone AI-E2E testing is a hard business at seed scale (Octomind).
  - The products that raised emphasize either enterprise customers (Notion, Dropbox, Wiz) or tight integration with coding agents via MCP (TestSprite).
- Many "layer" startups reposition toward **governance or control-plane** language: CodeRabbit "Agentic Change Management", OpenHands "Agent Control Plane", Warp "agent control layer", Tembo "autonomous maintenance". This suggests the investor-backed thesis has moved from "orchestrate agents" to "govern and verify agent changes".

### Gaps
- No 2025–2026 data was found for Ellipsis, Sourcery funding status, Omnara, Claude Squad, Reflect or Charlie Labs' current status. The web search budget was exhausted before these could be checked.
- Graphite revenue at acquisition was not found.
- Bugbot revenue or adoption was not found.
- Conductor funding is unverified.
- QA Wolf and Momentic revenue were not found.
- No primary fetch of Octomind's farewell letter was possible because the domain is offline.
- Greptile ARR was not found.

## Q4. Which categories did incumbents absorb in 2025–2026, and what happened to the startups?

### Takeaway
In 2025–2026 the model and IDE owners absorbed four categories:
- **background/cloud agents**: Codex Cloud, Claude Code on the web, Copilot coding agent and Cursor cloud agents;
- **parallel-agent orchestration**: Cursor 2.0/3 agent windows, Claude Code background agents and Agent View, GitHub Agent HQ, and Replit Pro's 10 parallel agents;
- **AI code review**: Cursor Bugbot plus the Graphite acquisition, Claude Code Review, and Copilot code review;
- **agent-adjacent IDEs**, through M&A: Windsurf to Cognition, Cursor to SpaceX/xAI, Codegen to ClickUp, Amp spun out of Sourcegraph.

Startups in the absorbed orchestration and background-agent niches shut down or were acquired (Terragon, Vibe Kanban, Codegen). Code-review startups survived by being cross-platform and raised larger rounds (CodeRabbit, Qodo).

### Cited Findings
- **Background agents:**
  - OpenAI launched the Codex Cloud research preview on **May 16, 2025**, running many tasks in parallel in cloud sandboxes and opening PRs. — [OpenAI Codex web docs](https://developers.openai.com/codex/cloud); [Wikipedia: Codex](https://en.wikipedia.org/wiki/Codex_(AI_agent))
  - Persistent, shareable environments followed at DevDay (Sep 2026) [3rd-party]. — [pasqualepillitteri.it](https://pasqualepillitteri.it/en/news/19386/codex-cloud-web-mobile-devday-2026)
  - Terragon's shutdown page points users to **Claude Code on the web and Codex Web**. — [CodeHerder](https://codeherder.com/alternatives/terragon/); [Terragon OSS](https://github.com/terragon-labs/terragon-oss)
- **Parallel orchestration inside the agents:**
  - **Cursor 2.0 (Oct 2025)** runs up to 8 parallel agents in git worktrees. **Cursor 3 (Apr 2026)** added an "Agents Window" showing local, worktree, cloud and SSH agents in one sidebar. — [Techzine](https://www.techzine.eu/news/devops/135916/cursor-2-0-introduces-parallel-agents-and-new-model/); [dsebastien notes](https://notes.dsebastien.net/30+Areas/33+Permanent+notes/33.02+Content/Cursor+Multi-Agents)
  - Claude Code added local background agents (Ctrl+B, v2.0.60) and **"Agent View"**, one screen for dispatching and managing many background sessions (v2.1.139+, research preview) [3rd-party]. — [dsebastien: Claude Code Agent View](https://dsebastien.net/claude-code-agent-view-one-screen-for-every-background-session/); [ClaudeLog](https://claudelog.com/faqs/what-are-background-agents/)
  - **GitHub Agent HQ** was announced in late 2025. **On Feb 4, 2026, Claude and Codex became available on Agent HQ** alongside Copilot, for Pro+ and Enterprise. Model selection for third-party agents followed in April 2026. — [GitHub blog, 2026-02-04](https://github.blog/2026-02-04-pick-your-agent-use-claude-and-codex-on-agent-hq/); [Daniel Vaughan](https://codex.danielvaughan.com/2026/04/16/codex-as-github-coding-agent-agent-hq-model-selection-cloud-review/)
  - Replit Pro ($100) includes "10 parallel agents". — [Replit pricing](https://replit.com/pricing)
- **Code review:**
  - Cursor shipped Bugbot ($40/user, mid-2025), then **acquired Graphite (Dec 19, 2025)**. Bugbot is now bundled in the $30+ tiers. — [TechCrunch](https://techcrunch.com/2025/12/19/cursor-continues-acquisition-spree-with-graphite-deal); [Cursor pricing](https://cursor.com/pricing)
  - Anthropic launched **Claude Code Review (Mar 9, 2026; $15–25/PR)**. — [Tessl blog](https://tessl.io/blog/anthropic-launches-ai-code-review-agents-that-scan-pull-requests-for-bugs)
  - GitHub Copilot code review is metered via credits and, from Jun 1, 2026, Actions minutes. Copilot runs a first-pass self-review (CodeQL) before handing PRs to humans. — [GitHub plans](https://github.com/features/copilot/plans); [i-programmer](https://www.i-programmer.info/news/90-tools/18447-github-announces-agent-hq-organizer.html)
- **Testing:** foundation-model providers offering agentic testing was flagged as a competitive threat at Momentic's Series A. — [TechCrunch](https://techcrunch.com/2025/11/24/momentic-raises-15m-to-automate-software-testing)
- **Outcomes for startups:**
  - Terragon shut down (Feb 9, 2026). — [CodeHerder](https://codeherder.com/alternatives/terragon/)
  - Vibe Kanban/Bloop shut down (Apr 10, 2026). — [Vibe Kanban](https://vibekanban.com/blog/shutdown)
  - Codegen was acquired by ClickUp and its standalone product shut (Jan 9, 2026). — [YesPress](https://yespress.io/products/codegen)
  - Tembo shut its cloud service and pivoted. — [Ry Walker](https://rywalker.com/research/tembo)
  - Octomind shut down (May–June 2026). — [RFP.wiki](https://www.rfp.wiki/vendors/octomind)
  - Windsurf was acquired by Cognition (July 2025) and rebranded Devin Desktop (June 2, 2026). — [Cognition](https://cognition.com/blog/windsurf); [Digital Applied](https://www.digitalapplied.com/blog/windsurf-becomes-devin-desktop-ide-migration-2026)
  - Graphite was acquired by Cursor (Dec 2025). Cursor was acquired by SpaceX/xAI ($60B, closed Aug 2026). — [GIGAZINE](https://gigazine.net/gsc_news/en/20260816-spacex-officially-closes-cursor-acquisition/)
  - Amp was spun out of Sourcegraph (Dec 2025), and Cody went enterprise-only. — [Tessl blog](https://tessl.io/blog/sourcegraph-spins-out-ai-coding-agent-amp-as-a-standalone-company/)
- **Counter-trend: neutral review vendors partnered with the platforms rather than being displaced.**
  - CodeRabbit joined the Claude Marketplace (May 27, 2026), raised at $1.5B (Aug 2026), and added Datadog as an investor.
  - Qodo raised $70M (Mar 2026) with angels from frontier labs.
  - Sources: [CodeRabbit newsroom](https://www.coderabbit.ai/newsroom); [agentmarketcap](https://agentmarketcap.ai/blog/2026/04/18/qodo-70m-series-b-cross-frontier-lab-angel-code-verification)

### Inferences
- The pattern is that any feature whose value is "run more of *my* agent" (background execution, parallelism, worktrees, agent dashboards) gets built by the agent owner within 3–9 months, because it directly drives token consumption. Terragon lasted about 7 months from its mid-2025 launch to its Feb 2026 shutdown.
- Features whose value is "**check** the agent's output" have stayed a viable independent category. Examples are PR review, test generation and execution, and governance.
  - Buyers want a reviewer that is not the same vendor as the author.
  - Review must span multiple agents, since 70% of developers use 2–4 tools.
  - Even so, model owners now ship their own reviewers (Anthropic, Cursor, GitHub), so neutrality and depth are the remaining moat.
- Distribution through the model owner's marketplace is emerging as a route to existing budgets. CodeRabbit's Claude Marketplace listing lets customers spend committed Anthropic dollars on it.

### Gaps
- No primary Anthropic launch post for Claude Code on the web was retrieved, so its exact date is not confirmed here.
- Whether Google (Jules, Antigravity, Gemini Code Assist) absorbed review or testing was not researched; the search budget was exhausted.
- No data was found on churn at CodeRabbit or Greptile after Claude Code Review and Bugbot bundling.

## Q5. What do buyers say about paying for verification, review or orchestration on top of Claude Code or Codex subscriptions?

### Takeaway
Buyers and budget holders will pay for **review and verification**, but at **seat-like prices** of about $12–40/dev/mo, ideally flat and unlimited. They resist both **per-PR metering** (Claude Code Review at $15–25/PR drew a "devs are losing their minds" backlash) and **paying anything for orchestration UIs**, which they expect free on top of their agent subscription.

Budget data supports a modest second line item:
- DX found **85.7% of leaders reserve 2026 budget for non-authoring tools** (review, debugging, security, planning, docs).
- That reservation is typically 15–20% of an AI budget targeted at about $1,000/dev/yr.
- That is roughly $150–200/dev/yr, about $12–17/dev/mo.

### Cited Findings
- DX budget findings (Oct 2025):
  - **85.7%** of engineering budget holders reserve some 2026 AI funds for tools not focused on code authoring (code review, debugging, security, project planning, docs).
  - The typical allocation is **15–20% of the AI tooling budget for non-authoring** and about 10% for authoring challengers.
  - The common 2026 target is **$1,000/dev/yr**.
  - 86% are uncertain which tools deliver the most benefit, 40% lack ROI data, and over half are considering controlling AI spend.
  - Source: [DX](https://getdx.com/blog/how-are-engineering-leaders-approaching-2026-ai-tooling-budget/)
- Menlo: for frontier use cases like coding, buyers are "quite price-insensitive" and "will pay more for performance" (Dec 2025). — [Menlo Ventures](https://menlovc.com/perspective/2025-the-state-of-generative-ai-in-the-enterprise/)
- Pragmatic Engineer survey (Jan–Feb 2026):
  - Employers fund most AI tool spend, commonly "max" plans at **$100–200/mo per engineer**, but some only about $20.
  - About 30% hit limits.
  - Cost concern is rising among budget holders.
  - **Code review and code validation are the top agent use case.**
  - Sources: [Pragmatic Engineer](https://newsletter.pragmaticengineer.com/p/ai-tooling-2026); [aiproductivity.ai summary](https://aiproductivity.ai/news/pragmatic-engineer-survey-ai-tooling-2026/)
- **Per-PR pricing backlash:**
  - Headlines include "Anthropic wants $25 per pull request: devs are losing their minds over Claude Code Review" and "Claude Code Review Costs $25, So I Built My Own AI Code Reviewer, for Free". The article body was not retrievable (HTTP 403).
  - Sources: [Level Up Coding](https://levelup.gitconnected.com/anthropic-wants-25-per-pull-request-devs-are-losing-their-minds-over-claude-code-review-55dbbaca4996); [Dory Zidon](https://doryzidon.com/blog/ai-code-review-diy); [Emelia "is it worth it?"](https://emelia.io/hub/claude-code-review-test)
- **Bugbot price pushback:** Cursor forum threads are titled "Bugbot – Too expensive" and "Bugbot Pricing Feedback" (at $40/user/mo). Cursor later moved Bugbot to usage-based billing and bundled it into its $30+ tiers. — [Cursor forum: too expensive](https://forum.cursor.com/t/bugbot-too-expensive/126724); [Cursor forum: pricing feedback](https://forum.cursor.com/t/bugbot-pricing-feedback/131907); [Cursor pricing](https://cursor.com/pricing)
- **Accepted review price anchors** [3rd-party]:
  - CodeRabbit Pro: about $24–30/dev/mo, unlimited.
  - Greptile: $30/seat including 50 reviews, then $1 per review.
  - Sourcery and Bito: about $12.
  - Copilot: from $10.
  - A comparison table claims Greptile costs $600/mo for 10 devs at 80 PRs each versus $240 for CodeRabbit. The source is a CodeRabbit competitor, so treat this as directional.
  - Sources: [Dupple](https://dupple.com/learn/best-ai-code-review-tools); [aicodereview.cc](https://aicodereview.cc/blog/greptile-pricing); [CostBench](https://www.costbench.com/compare/coderabbit-vs-greptile/)
- **Orchestration willingness to pay is low:**
  - Vibe Kanban: "the vast majority are free users", and they "couldn't find a business model". — [Vibe Kanban](https://vibekanban.com/blog/shutdown)
  - Conductor and Sculptor are free, with users bringing their own Claude or Codex subscription. — [MorphLLM](https://www.morphllm.com/conductor-ai-coding); [usagepricing (Imbue)](https://www.usagepricing.com/blueprint/imbue)
- **Testing willingness to pay is unproven at small scale:** Octomind cited a lack of "market validation". — [RFP.wiki](https://www.rfp.wiki/vendors/octomind)
- **Cost-unpredictability is the dominant complaint across agent pricing**, and it makes buyers wary of adding another metered tool:
  - Cursor (June 2025 refunds). — [FinTech Weekly](https://www.fintechweekly.com/magazine/articles/cursor-pricing-change-user-backlash-refund)
  - Replit ("$1K in the last week"). — [The Register](https://www.theregister.com/2025/09/18/replit_agent3_pricing/)
  - Copilot AI Credits ("why developers are upset"). — [GapVelocity](https://www.gapvelocity.ai/blog/github-copilots-new-usage-based-billing-what-changed-why-developers-are-upset-and-what-it-means)
  - Augment (credits "without clear visibility"). — [Kilo](https://blog.kilo.ai/p/testing-augment-codes-new-credit)
- **Demand driver for verification:**
  - CodeRabbit's study found AI code has about 1.7x more issues. — [CodeRabbit newsroom](https://www.coderabbit.ai/newsroom)
  - Qodo's raise was framed as "AI-generated code outpaces human review capacity". — [Munich Startup](https://insights.munich-startup.de/news/feed/qodo-raises-70m-as-ai-generated-code-outpaces-human-review-capacity)
  - Cursor's Graphite rationale was that review, not writing, is now the bottleneck. — [Cursor blog](https://cursor.com/blog/graphite)
  - Octomind's letter says testing is "only getting more urgent". — [RFP.wiki](https://www.rfp.wiki/vendors/octomind)

### Inferences
- A layer-above verification product sold on top of Claude Code or Codex has a realistic pricing envelope:
  - about **$15–40/dev/mo flat** (seat), or
  - a team plan whose effective cost is in that range.
  - That matches the CodeRabbit, Greptile and Bugbot anchors and DX's roughly $150–200/dev/yr non-authoring slice.
- Per-run pricing above about $5–10 per check will likely be compared unfavorably with Anthropic's $15–25/PR review and with free DIY scripts. This is an inference.
- Buyers distinguish **"prove the change works / is safe"**, a budgetable, team-level quality spend, from **"help me run more agents"**, which they expect bundled. The former has funding and revenue evidence (CodeRabbit, Qodo, Momentic, Meticulous). The latter has shutdown evidence (Terragon, Vibe Kanban).
- Because individual developers' spend is already committed to the $100–200/mo agent tier, monetization for a layer-above product most plausibly comes from:
  - the **team or engineering-leader budget**; or
  - **marketplace drawdown of existing model-vendor commitments** (the CodeRabbit + Claude Marketplace precedent).
- Free/BYO-key tools can win users (Vibe Kanban had "thousands" of daily users) but still fail to convert.
- Evidence that a verification product works must be legible to buyers. Successful vendors lead with quantified defect findings (Momentic's "390K bugs", CodeRabbit's "1.7x issues"), and buyers report not knowing which tools deliver value (DX: 86% uncertain). Browser- or test-proven verdicts tied to the PR are the kind of artifact that can justify a line item. This is an inference.

### Gaps
- No direct buyer survey isolating willingness to pay for verification or QA layered on a Claude Code or Codex subscription was found.
- The article bodies on the Claude Code Review backlash (Level Up Coding) were not accessible, so specific user quotes are not captured.
- No Hacker News or Reddit threads were sampled; the search budget was exhausted.
- No data was found on conversion rates from free to paid for BYO-key orchestration tools other than Vibe Kanban's qualitative statement.
- No Gartner or IDC survey on AI code-review or testing spend was found.
- Note on research coverage: the session-wide web search limit (200 searches) was reached partway through, so Ellipsis, Sourcery, Omnara, Claude Squad, Reflect, Google Jules/Antigravity pricing, Windsurf pricing and a primary check of Graphite revenue were not researched. A follow-up pass could cover them.
