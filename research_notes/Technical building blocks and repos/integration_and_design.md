# Integration surfaces, orchestration/persistence building blocks, and system-design references for Contexer

Scope: a layer that supervises existing coding agents (Claude Code, Codex, OpenCode), proves behaviour with executable acceptance checks, and gates merges with verified evidence. State as of 2026-10-14. Repo metadata (stars, license, last push, latest release, `requires-python`) was pulled with read-only `gh api` calls on 2026-10-14 unless stated otherwise. Coding-agent platforms, browser-testing tools and sandbox providers are out of scope (other researchers).

Verdict key: **BUILD ON** = take as a dependency; **BORROW IDEAS** = copy the design, not the code; **AVOID** = poor fit for Contexer now, with reasons.

---

## Key Question 1: How should Contexer integrate with GitHub (and trackers/chat) to act as a blocking, evidence-presenting checker?

### Takeaway
For the service phase, Contexer should be a **GitHub App**, not only an Action: only Apps can create check runs through the Checks API, receive `check_run.rerequested` / `requested_action` and `merge_group` events, and be pinned as the required check's "expected source" so nobody else can turn the gate green. Checks give Contexer a Markdown summary of up to 65,535 characters, images, up to 50 annotations per call, a `details_url` link and up to 3 action buttons. That is enough for a readable evidence report, with the full report hosted by Contexer, because GitHub keeps check data for only 400 days. GitHub's Agent HQ (Claude and Codex as agents inside GitHub) has **no documented hook for third-party verifiers in its pre-PR validation step**. The plug-in points are the PR's required checks and MCP servers in custom agents.

### Cited Findings

**Checks API: who can write, statuses, conclusions**
- Write access to the Checks API is **only available to GitHub Apps**. OAuth apps and authenticated users can read check runs and suites but cannot create them. Apps need `checks:write`. Non-App integrations are pointed to commit statuses instead — [GitHub Docs: Using the REST API to interact with checks](https://docs.github.com/en/rest/guides/using-the-rest-api-to-interact-with-checks)
- Check run statuses: `queued`, `in_progress`, `requested`, `waiting`, `pending`, `completed`. Only GitHub Actions can set `requested`, `waiting` or `pending`. Completed conclusions: `action_required`, `cancelled`, `timed_out`, `failure`, `neutral`, `skipped`, `success`. Suites also have `stale` and `startup_failure`. A suite reports its highest-priority run conclusion. A run left incomplete for more than 14 days becomes `stale`, and only GitHub can set that — [GitHub Docs: checks guide](https://docs.github.com/en/rest/guides/using-the-rest-api-to-interact-with-checks)
- GitHub sends `check_suite` `requested` to Apps with `checks:write` on each push by default. Automatic suite creation can be turned off through "Update repository preferences for check suites", after which the App creates suites itself — [GitHub Docs: checks guide](https://docs.github.com/en/rest/guides/using-the-rest-api-to-interact-with-checks)
- **Retention:** GitHub keeps checks data for **400 days**, then archives it and deletes it 10 days later. Merging a PR whose required checks were archived needs a re-run — [GitHub Docs: checks guide](https://docs.github.com/en/rest/guides/using-the-rest-api-to-interact-with-checks)
- A check suite keeps at most 1,000 check runs with the same name. Older ones are deleted automatically — [GitHub REST: Check runs](https://docs.github.com/en/rest/checks/runs)

**Check run output limits (verified in GitHub's OpenAPI description, `github/rest-api-description`, downloaded 2026-10-14)**
- `output.summary` and `output.text` support Markdown, with a **maximum of 65,535 characters** each — [GitHub REST API description (OpenAPI)](https://github.com/github/rest-api-description/blob/main/descriptions/api.github.com/api.github.com.json)
- `output.annotations` takes at most **50 per request**. Further updates append to the existing annotations. Annotation `message` and `raw_details` can be up to 64 KB, `title` up to 255 characters, and `annotation_level` is `notice`, `warning` or `failure` — [GitHub REST: Check runs](https://docs.github.com/en/rest/checks/runs)
- `output.images[]` needs `alt` and `image_url` (the full URL of the image); `caption` is optional — [GitHub REST: Check runs](https://docs.github.com/en/rest/checks/runs)
- `actions[]` takes at most **3 buttons**: `label` up to 20 characters, `description` up to 40, `identifier` up to 20. A click sends `check_run.requested_action` to the App, which reads `requested_action.identifier` — [GitHub REST: Check runs](https://docs.github.com/en/rest/checks/runs); [GitHub Docs: checks guide](https://docs.github.com/en/rest/guides/using-the-rest-api-to-interact-with-checks)
- `details_url` is "the URL of the integrator's site that has the full details", and `external_id` is the integrator's own reference — [GitHub REST: Check runs](https://docs.github.com/en/rest/checks/runs)
- GitHub Actions workflow commands are limited to **10 warning and 10 error annotations per step**, a constraint the App route does not have — [GitHub REST: Check runs](https://docs.github.com/en/rest/checks/runs)
- **Rerequest:** `POST .../check-runs/{id}/rerequest` fires `check_run` `rerequested`, resets the suite to queued and clears its conclusion. It returns 403 if the run "doesn't belong to the authenticated GitHub App". Clicking re-run in the UI sends the `check_run` webhook to the App that created the run — [GitHub REST: Check runs](https://docs.github.com/en/rest/checks/runs); [GitHub Docs: checks guide](https://docs.github.com/en/rest/guides/using-the-rest-api-to-interact-with-checks)

**Commit statuses (the non-App alternative)**
- Anyone with push access can create a commit status for a SHA. The limit is 1,000 statuses per `sha` and `context` — [GitHub REST API description (OpenAPI), `POST /repos/{owner}/{repo}/statuses/{sha}`](https://github.com/github/rest-api-description)

**Required status checks and branch protection**
- Required checks must report `successful`, `skipped` **or `neutral`** before a merge is allowed. They "can be checks or commit statuses". In strict mode the branch must also be up to date with the base — [GitHub Docs: About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- A required check can be pinned to an **expected source App**. If any other person or integration sets that status, merging is blocked — [GitHub Docs: About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- Only one branch protection rule applies at a time, but this restriction does not apply to rulesets — [GitHub Docs: About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)

**Merge queue**
- The queue waits for required checks on a temporary merge-group branch. The branch prefix is `gh-readonly-queue/{base_branch}`, and its SHA differs from the PR's. Third-party CI must run on pushes to that prefix. GitHub Actions workflows must trigger on `merge_group`, or "the required status check will not be reported" — [GitHub Docs: Managing a merge queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)
- Settings include build concurrency (1–100 `merge_group` webhooks dispatched) and a status-check timeout after which the queue treats checks as failed. A failing group is removed and the queue rebuilds — [GitHub Docs: Managing a merge queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)
- The `merge_group` webhook (`checks_requested`, `destroyed`) is **GitHub App only** and needs read access to the "Merge queues" permission. On `checks_requested` the App reports on the head SHA via check runs or commit statuses — [GitHub Docs: Webhook events and payloads](https://docs.github.com/en/webhooks/webhook-events-and-payloads)

**Webhooks relevant to Contexer**
- `check_run`: `created`, `completed`, `rerequested`, `requested_action`. The last two need Checks write access, and repository or organization webhooks only receive `created` and `completed`. `check_suite`: `completed`, `requested`, `rerequested`. For runs triggered from a fork's branch, `pull_requests` is empty and `head_branch` is null — [GitHub Docs: Webhook events and payloads](https://docs.github.com/en/webhooks/webhook-events-and-payloads)
- `pull_request` (`opened`, `synchronize`, `reopened`, `ready_for_review`, `labeled`, …), `issue_comment` (for slash-command style triggers), `pull_request_review` (`submitted`, `edited`, `dismissed`), and `deployment_status`, which is a good trigger for verifying a preview deploy and never fires for the `inactive` state — [GitHub Docs: Webhook events and payloads](https://docs.github.com/en/webhooks/webhook-events-and-payloads)
- Payloads are capped at 25 MB. Larger events are not delivered — [GitHub Docs: Webhook events and payloads](https://docs.github.com/en/webhooks/webhook-events-and-payloads)
- The server should return **2XX within 10 seconds** or the delivery counts as failed. Process payloads from a queue. Deduplicate on `X-GitHub-Delivery`, which redeliveries keep. Redeliver missed webhooks after an outage. Use a high-entropy secret and HTTPS. Subscribe only to the events you need — [GitHub Docs: Best practices for using webhooks](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks)

**PR reviews and comments**
- `POST /pulls/{n}/reviews` takes `event` = `APPROVE`, `REQUEST_CHANGES` or `COMMENT`. A blank `event` creates a `PENDING` review. Creating content too quickly can hit secondary rate limits. Issue comments (`POST /issues/{n}/comments`) work on PRs, since every PR is an issue — [GitHub REST API description (OpenAPI)](https://github.com/github/rest-api-description)

**GitHub App vs Action**
- GitHub Apps can act independently of a user, using installation tokens with narrow per-repo permissions and built-in webhooks. User-to-server tokens are limited by both the App's and the user's permissions — [GitHub Docs: About creating GitHub Apps](https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/about-creating-github-apps)
- `GITHUB_TOKEN` is itself a GitHub App installation token scoped to the workflow's repository. It expires when the job ends, at most 6 hours on GitHub-hosted runners and up to 24 hours on self-hosted runners. Events it triggers do not start new workflow runs, except `workflow_dispatch` and `repository_dispatch` — [GitHub Docs: GITHUB_TOKEN](https://docs.github.com/en/actions/concepts/security/github_token)

**Python libraries and the Probot pattern** (gh metadata 2026-10-14)

| Library | URL | License | Stars | Last push | Python | Notes | Verdict |
|---|---|---|---|---|---|---|---|
| githubkit | https://github.com/yanyongyu/githubkit | MIT | 354 | 2026-10-07 (v0.16.1, 2026-08-14) | >=3.10 | Sync and async, fully typed, Pydantic models for REST responses and webhook events, REST + GraphQL, pagination, auto retry, HTTP cache (Hishel), REST API versioning; inspired by Octokit ([README](https://github.com/yanyongyu/githubkit)). Source has `githubkit/auth/app.py` (App and installation auth strategies), `webhooks.verify`/`sign`/`parse`, `retry.py` and `throttling.py`. Dependencies: `httpx`, `pydantic`, `hishel` (pyproject) | **BUILD ON**: matches Contexer's httpx + pydantic stack, async, typed webhook models, App auth |
| PyGithub | https://github.com/PyGithub/PyGithub | LGPL-3.0 | 7,789 | 2026-10-13 (v2.10.0, 2026-08-20) | >=3.10 | Sync, `requests`-based (pyproject) | **AVOID** for the service (sync-only, extra HTTP stack, LGPL). Acceptable for small scripts |
| gidgethub | https://github.com/brettcannon/gidgethub | Apache-2.0 | 424 | 2026-09-25 | >=3.10 | "An async GitHub API library for Python" (repo description) | **BORROW IDEAS** (small async design); githubkit is more complete |
| Probot | https://github.com/probot/probot | ISC | 9,621 | 2026-10-13 | TypeScript only | Framework for building GitHub Apps (repo description) | **BORROW IDEAS**: the pattern of webhook → typed event handler → per-installation authenticated client. Replicate in Python with githubkit + a small ASGI receiver |

**How existing third-party checkers present evidence on a PR**
- **Argos** (visual testing): GitHub App with Contents, Statuses, Pull requests and Actions permissions. Reports **commit statuses** (contexts `argos`, `argos/<build>`, `argos/<project>`, `argos/summary`), not check runs. Posts a PR comment with the latest build results and links back to Argos. Supports native Merge Queue: uploads on `pull_request` and `merge_group`, compares queued changes against the merge base of all PRs in the queue, and needs full access for queue mode. Builds the merge commit but posts status on the PR head commit — [Argos docs: GitHub](https://argos-ci.com/docs/github). Repo: https://github.com/argos-ci/argos (MIT, 637 stars, pushed 2026-10-14)
- **Chromatic**: two separate PR checks, "UI Tests" (diff against the accepted baseline; accepting changes turns it green, denying fails the build immediately) and "UI Review" (head vs merge base, assigned reviewers, checklist). No visual changes passes automatically. Changes keep the check **pending, blocking merge, until someone approves**. Gotcha: if the CI step is skipped, the required check stays pending forever, so Chromatic says to run with `--skip` (reports skipped) instead of skipping the step — [Chromatic: Mandatory PR checks](https://www.chromatic.com/docs/mandatory-pr-checks/); [Chromatic: In pull request workflow](https://www.chromatic.com/docs/in-pull-request/); [Chromatic: Review](https://www.chromatic.com/docs/review/)
- **Percy**: commit status that moves through processing → changes need review → approved. Approving in Percy turns the GitHub status green. Approval is not required by default but can be made a merge blocker. Builds on the main branch are auto-approved by default. Needs commit-status write access — [BrowserStack: Integrate Percy with GitHub](https://www.browserstack.com/docs/percy/integrations/source-control/github); [Percy basics](https://docs.percy.io/docs/percy-platform-basics). Percy also publishes a "Visual Testing Plugin for AI coding agents", an example of a verifier plugging into agents directly — [BrowserStack: Visual testing plugin for AI coding agents](https://www.browserstack.com/docs/percy/ai-agents/visual-testing-plugin)
- **CodeRabbit pre-merge checks** (vendor docs, undated): built-in checks (docstring coverage, default 80%; PR title; PR description; linked-issue assessment) plus natural-language custom checks that run in a read-only sandbox and may use MCP tools (Team plan and up). Each check is `off`, `warning` (the default, non-blocking) or `error`, which blocks only with the Request Changes workflow. The docs advise starting in `warning`. Results appear in the PR walkthrough comment as "Failed checks" and "Passed checks" tables, with status Error, Warning, Passed or Inconclusive; Inconclusive does not block. Overrides via "Ignore failed checks" or `@coderabbitai ignore pre-merge checks` apply per PR, are tagged `[IGNORED]`, and can be limited to requested reviewers (not the author) — [CodeRabbit docs: Pre-merge checks](https://docs.coderabbit.ai/pr-reviews/pre-merge-checks)
- **Greptile**: a top-level PR summary comment (plain-language summary, file-by-file breakdown, optional sequence diagram) plus inline comments, with a 0–5 "confidence score" mapped to merge advice. Status is shown through emoji reactions (analysing about 3 minutes, complete, failed) — [Greptile docs: First PR review](https://www.greptile.com/docs/code-review/first-pr-review). I found no official docs on Greptile's check-run name or conclusions. Community skills look for check runs named "greptile" on the head SHA (secondary, unverified)

**GitHub Agent HQ / custom agents: can a third-party verifier plug in?**
- Agent HQ was announced 2025-10-28 at Universe: "mission control" across GitHub, VS Code, mobile and CLI; "branch controls" over when CI and other checks run on agent-created code; agent identity controls; integrations with Slack and Linear (Jira, Teams, Azure Boards and Raycast earlier); AGENTS.md and custom agents; an MCP registry in VS Code; and an agent control plane (public preview) — [GitHub Blog: Welcome home, agents](https://github.blog/news-insights/company-news/welcome-home-agents/)
- Claude and Codex became coding agents in GitHub in **public preview on 2026-02-04** (Copilot Pro+ and Enterprise), expanded to Business and Pro on 2026-02-26, when the Agent Control Plane became GA — [GitHub Changelog 2026-02-04](https://github.blog/changelog/2026-02-04-claude-and-codex-are-now-available-in-public-preview-on-github/); [GitHub Changelog 2026-02-26](https://github.blog/changelog/2026-02-26-claude-and-codex-now-available-for-copilot-business-pro-users/)
- Third-party coding agents are still "currently in public preview" (docs, read 2026-10-14). Enabling them installs GitHub Apps named "anthropic code agent" and "openai code agent". Their code is scanned automatically **before the PR is finalized** with CodeQL, secret scanning and dependency checks (no GHAS licence needed). The docs list **no extension point for external validators** and don't say whether admins can configure the validation tools — [GitHub Docs: About third-party agents](https://docs.github.com/en/copilot/concepts/agents/about-third-party-agents)
- **Custom agents** are Markdown profiles with YAML frontmatter (`name`, `description`, `tools`, `mcp-servers`), stored at `.github/agents/NAME.md` in a repo or `/agents/` in the org's `.github`/`.github-private` repo. They work in Copilot cloud agent, IDEs, the Copilot app and the Copilot CLI, and **can declare MCP servers** — [GitHub Docs: About custom agents](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-custom-agents)
- GitHub Code Quality became GA on 2026-07-20 — [GitHub Changelog 2026-06-16](https://github.blog/changelog/2026-06-16-github-code-quality-generally-available-july-20-2026)

**Triggers from Linear, Jira and Slack**
- **Linear for Agents** (Developer Preview; "APIs may change before general availability"). OAuth with `actor=app` installs the integration as an app user; `app:assignable` and `app:mentionable` scopes allow delegation and @mentions. Assigning an issue sets the agent as `delegate` while humans keep ownership. Delegation creates an `AgentSessionEvent` (`created`), and the agent **should emit a `thought` activity within 10 seconds**. Installed agents are not billable users. Distribution to other workspaces needs a listing in Linear's directory — [Linear Developers: Agents](https://linear.app/developers/agents)
- **Slack Events API**: respond with HTTP 2xx **within 3 seconds**. Retries happen up to 3 times (almost immediately, after 1 minute, after 5 minutes) with an `x-slack-retry-num` header. Socket Mode avoids needing a public URL. The cap is 30,000 deliveries per workspace per app per 60 minutes — [Slack docs: Events API](https://docs.slack.dev/apis/events-api/)
- Production references: Stripe Minions start mostly from a Slack mention, with CLI, web and internal-tool buttons (for example a "fix flaky test" button on CI tickets) — [Stripe Minions Part 1, 2026-02-09](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents). Ramp Inspect uses Slack (a fast model routes each message to a repo), web and a Chrome extension — [Ramp Builders: Why we built our background agent](https://builders.ramp.com/post/why-we-built-our-background-agent). OpenAI Symphony polls a Linear board — [openai/symphony README](https://github.com/openai/symphony)
- Jira: I did not fetch Jira webhook or Automation docs. Agent HQ lists Jira as an existing mission-control integration — [GitHub Blog: Welcome home, agents](https://github.blog/news-insights/company-news/welcome-home-agents/)

### Inferences
- **Map Contexer verdicts carefully: `neutral` passes a required check.** Contexer's "blocked/inconclusive" verdict must not be reported as `neutral` on a gating check, or it silently allows the merge. Use `action_required` when a human must approve the checklist or a decision is needed, `failure` for a disproven criterion, `timed_out` or `cancelled` for budget or crash, and `success` only when every locked check has passing evidence. `skipped` should be used only when the change provably cannot affect any locked contract. This follows from the passing set (success, skipped, neutral) in the protected-branches doc.
- **Proposed check run layout:** name `Contexer / acceptance` (consider a second, `Contexer / regression replay`, so they can be required separately, as Chromatic does with UI Tests and UI Review). Summary (≤65,535 characters): a per-criterion table (criterion → verdict → evidence kind → link), the attempt count and budget spent. `images[]`: 1–3 key screenshots. `details_url`: the full Contexer evidence report. `external_id`: the Contexer run id. `actions[]` (≤3, label ≤20 characters): "Re-verify", "Approve checks", "Repair". Annotations: only when evidence maps to file lines (for example an assertion in a saved check file).
- Image URLs in `output.images` must be fetchable later. Short-lived presigned URLs would likely break old reports, and data is kept only 400 days. So the evidence store must be Contexer-owned and long-lived, with the check output as a pointer. (This is inference; the docs only say "full URL of the image".)
- Always report *something* on every PR SHA and merge-group SHA. Chromatic's "pending forever" failure shows a required check that never reports blocks merging indefinitely.
- **Merge queue + hour-long runs:** a full build–verify–repair loop cannot run inside a merge-queue timeout. In queue mode, Contexer should run only **regression replay of locked contracts** against the merge-group SHA. It must report on that SHA (not the PR head) and needs the App's `merge_group` subscription. The full loop belongs on `pull_request` and `synchronize`.
- **Ack-then-enqueue is mandatory.** GitHub's 10-second, Slack's 3-second and Linear's 10-second windows mean the webhook receiver should only verify the signature, dedupe on the delivery id, persist a job row and return 2xx. Run execution happens in a worker reading from the durable run store (see KQ2).
- **Local CLI first, App later:** a `contexer verify --report github` path can post a commit status (works with push access, as Argos does) or a check run from Actions, so teams can adopt before the App exists. The App adds source pinning, the re-run and action buttons, and merge-queue events. Pinning the App as the expected source is the anti-tamper property that matters for "gates merges with verified evidence".
- **Agent HQ positioning:** GitHub's built-in validation of agent PRs is security-oriented (CodeQL, secrets, dependencies) and closed. Contexer's behavioural verification fits as (a) a required check on agent-created PRs, which apply to any agent including Copilot, Claude and Codex in GitHub, and (b) an MCP server referenced from a repo's `.github/agents/*.md`, so in-GitHub agents can call `contexer.verify` before finishing. Both are documented surfaces; a native "validator plugin" slot is not.
- Borrow CodeRabbit's rollout ergonomics: per-check `warning` → `error` modes, a per-PR override command with an audit tag, and overrides limited to requested reviewers. Also borrow Percy and Chromatic's "approve in the report → status turns green" loop for the human checklist-approval step (implemented with `requested_action` or a link back to the Contexer report).

### Gaps
- Not verified: whether `GITHUB_TOKEN`-created check runs land in the workflow's own check suite, and whether `GITHUB_TOKEN` can write checks or comments on fork PRs. The fetched docs page didn't cover forks.
- Not verified: whether a GitHub App's `APPROVE` review counts toward required approving reviews.
- No official Greptile check-run documentation found. Argos's PR-comment layout and approval-to-status behaviour weren't detailed on the page fetched.
- Jira (webhooks, Automation, Rovo) trigger mechanics not researched due to budget.
- GitHub's merge queue doc doesn't give default timeout or concurrency values.

---

## Key Question 2: Which durable-execution / persistence approach fits runs of minutes to an hour that must survive crashes and resume, for a small Python team going from local CLI to GitHub App service? Is SQLite + an explicit state enum enough at first?

### Takeaway
Yes. **SQLite plus an explicit run/step state enum, written synchronously before and after every step, with idempotent steps and external blob storage, is enough for the CLI phase.** OpenAI's Symphony spec deliberately recovers from restarts *without* a durable orchestrator DB, using only tracker and filesystem state. When Contexer becomes a multi-worker GitHub App service, **DBOS** is the lightest upgrade: an MIT library with no separate server, SQLite by default and Postgres for production. **Hatchet** (MIT, Postgres) fits if a queue and UI are wanted. **Temporal** is the strongest but heaviest (server plus determinism sandbox). **Inngest** (SSPL server) and **Restate** (BSL server) carry licence and server overhead. **Prefect** targets data pipelines. **LangGraph** checkpointing is a useful design reference but would pull Contexer into a graph framework it has deliberately deferred.

### Cited Findings

**Building-block table** (gh metadata 2026-10-14)

| Block | Repo / docs | License | Stars | Last push / latest release | Python | What it is | Verdict for Contexer |
|---|---|---|---|---|---|---|---|
| DBOS Transact (Python) | https://github.com/dbos-inc/dbos-transact-py · https://docs.dbos.dev | MIT | 1,628 | 2026-10-14 / 3.2.0 (2026-09-29) | >=3.10 | Library: decorate workflows and steps, checkpoints to a "system database". No orchestration server | **BUILD ON at the service phase** (optional now): lightest real durable execution, SQLite → Postgres path |
| Temporal Python SDK + server | https://github.com/temporalio/sdk-python · https://github.com/temporalio/temporal | MIT / MIT | 1,223 / 23,699 | 2026-10-14 / 1.34.0 (2026-09-30) | >=3.10 | Event-sourced workflows replayed on workers. Needs Temporal server (Go) or Temporal Cloud | **BORROW IDEAS now**; revisit only for a multi-language or high-scale hosted service |
| Hatchet | https://github.com/hatchet-dev/hatchet · https://docs.hatchet.run | MIT | 8,113 | 2026-10-14 / v0.110.5 (2026-10-06); Python SDK 1.42.1 | >=3.10 | Queue + DAGs + durable tasks; Postgres durability layer; OTel; self-host via "Hatchet Lite" | **BORROW IDEAS / later option** if a hosted job queue with UI is needed |
| Inngest | https://github.com/inngest/inngest · https://github.com/inngest/inngest-py | Server: SSPL 1.0 with "Apache 2.0 Future License"; py SDK Apache-2.0 | 5,942 / 217 | 2026-10-14; py SDK 0.5.19 (2026-06-23) | >=3.10 | Step functions invoked over HTTP by the Inngest server (single Go binary) | **AVOID**: SSPL server, 0.x Python SDK, HTTP-callback model awkward for a local CLI |
| Restate | https://github.com/restatedev/restate · https://github.com/restatedev/sdk-python | Server: BSL 1.1 (no "Public Restate Platform Service"); SDK MIT | 4,558 / 82 | 2026-10-14 / v1.8.0 (2026-10-14) | >=3.10 | Rust single-binary server, durable journal, exactly-once messaging, durable promises and timers | **AVOID** for now: BSL server, extra process, small Python community |
| Prefect | https://github.com/PrefectHQ/prefect | Apache-2.0 | 24,018 | 2026-10-13 / 3.8.8 (2026-10-06) | >=3.11,<3.15 | "Workflow orchestration framework for building resilient data pipelines"; server/UI at :4200 | **AVOID**: data-pipeline orientation and server; adds little over DBOS for this use |
| LangGraph | https://github.com/langchain-ai/langgraph · https://docs.langchain.com/oss/python/langgraph/durable-execution | MIT | 43,261 | 2026-10-14 / langgraph 1.2.15 | >=3.10 | Graph runtime with checkpointers (`InMemorySaver`, `SqliteSaver`, `PostgresSaver`), threads, interrupts | **BORROW IDEAS** (keep deferred): checkpoint-per-step, `thread_id`, durability modes, interrupts for human checkpoints |
| Absurd | https://github.com/earendil-works/absurd | Apache-2.0 | 2,490 | 2026-08-10 | Python SDK (also Go, TS) | "Simplest durable execution" built entirely on Postgres, no other services | **BORROW IDEAS**: smallest design to copy for an in-house store |
| procrastinate | https://github.com/procrastinate-org/procrastinate | MIT | 1,420 | 2026-10-12 | — | PostgreSQL-based task queue for Python | **BORROW IDEAS / optional** queue if not using DBOS queues |

**DBOS**
- "No separate orchestration server and no infrastructure required besides Postgres." On restart DBOS finds `PENDING` workflows, re-invokes them with checkpointed inputs, returns saved step outputs instead of re-running them, and resumes at the first step without a checkpoint. Workflows must be deterministic (API calls and time reads go in steps) and steps should be idempotent. Versioning makes workflows recover only on compatible code. Durable queues include rate and concurrency limits. Conductor, the managed control plane, is "strongly recommended" for production but never involved in execution — [DBOS docs: Architecture](https://docs.dbos.dev/architecture)
- Cost model: one DB write per step plus two per workflow. Large inputs and outputs are expensive, so store files in blob storage and pass pointers. A single Postgres sustained more than 40K workflows or steps per second in DBOS's benchmark (vendor claim) — [DBOS docs: Architecture](https://docs.dbos.dev/architecture)
- **SQLite support:** `system_database_url` "may be either Postgres or SQLite, though Postgres is recommended for production". With no URL set, DBOS uses `sqlite:///[application_name].sqlite`. SQLite always uses polling (no LISTEN/NOTIFY) — [DBOS docs: Configuration](https://docs.dbos.dev/python/reference/configuration). The source tree has `dbos/_sys_db_sqlite.py` (gh code search, 2026-10-14). Note the README still describes DBOS as Postgres-backed — [README](https://github.com/dbos-inc/dbos-transact-py)
- DBOS's own comparison: use DBOS to add durable workflows "with minimal rearchitecting"; use Temporal if you don't want Postgres or need an unsupported language (vendor framing) — [dbos-transact-py README](https://github.com/dbos-inc/dbos-transact-py)

**Temporal**
- The Python workflow sandbox blocks known non-deterministic calls at import and run time but "is not completely isolated". A non-determinism error fails the workflow task until the code is fixed. Third-party modules must be explicitly passed through and side-effect-free — [Temporal docs: Python sandbox](https://docs.temporal.io/develop/python/python-sdk-sandbox)
- `temporal server start-dev` loses executions on exit by default. `--db-filename` persists to a file (SQLite pragmas are configurable). UI on :8233, gRPC on :7233. "Not intended for production use" — [Temporal CLI: server](https://docs.temporal.io/cli/server)
- Event history hard limit is **51,200 events or 50 MB**, with warnings at 10,240 events or 10 MB. Pending activities and child workflows default to at most 2,000 each — [Temporal docs: Workflow execution limits](https://docs.temporal.io/workflow-execution/limits)
- The OpenAI Agents SDK integration (each agent invocation runs as an Activity via `OpenAIAgentsPlugin`) was announced as GA on 2026-03-23 (vendor). The Python API reference still labels the module experimental — [Temporal blog](https://temporal.io/blog/announcing-openai-agents-sdk-integration); [python.temporal.io module docs](https://python.temporal.io/temporalio.contrib.openai_agents.html)

**Inngest / Hatchet / Restate self-hosting**
- Inngest self-host: a single CLI binary, `inngest start` (ports 8288 and 8289). Default persistence is SQLite at `./.inngest/main.db` plus an in-memory Redis snapshotted to SQLite. Postgres and Redis can be external. SQLite "does not support scaling beyond a single node". No guaranteed support for self-hosted, and old Postgres rows are not auto-deleted — [Inngest docs: Self-hosting](https://www.inngest.com/docs/self-hosting)
- Hatchet: "Hatchet Lite" single image (dev, test, low-throughput production), Docker Compose with PostgreSQL and optional RabbitMQ, or Helm. `hatchet server start` wraps Lite — [Hatchet docs: Self-hosting](https://docs.hatchet.run/self-hosting). Its README positions durable tasks as a drop-in replacement for Temporal or DBOS workflows (vendor claim) — [Hatchet README](https://github.com/hatchet-dev/hatchet)
- Restate installs via Homebrew, `npx @restatedev/restate-server` or Docker — [Restate README](https://github.com/restatedev/restate)

**LangGraph durability**
- Durability modes: `"exit"` (persist only at end, fail or interrupt; fastest, no mid-run recovery), `"async"` (persist in the background while the next step runs; a crash can lose the last checkpoint), `"sync"` (persist before each next step). `durability` replaced `checkpoint_during` in v0.6.0. Non-deterministic operations should be wrapped in tasks — [LangGraph docs: Durable execution](https://docs.langchain.com/oss/python/langgraph/durable-execution) (via search snippet; full page content not retrieved)
- Checkpointers: `InMemorySaver` (lost on restart), `SqliteSaver` (file-based, for development), `PostgresSaver`/`AsyncPostgresSaver` (production). Runs attach to a `thread_id`, and old checkpoints should be pruned — [LangGraph persistence docs](https://docs.langchain.com/oss/python/langgraph/durable-execution)

**Ecosystem signal**
- Pydantic AI ships durable-execution integrations co-maintained with Temporal, DBOS, Prefect, Restate and AWS Lambda, plus external ones for Absurd, Airflow, Kitaru and pgtask. It notes that "durability is not storage": the engine keeps a run alive across crashes, but conversation persistence is separate — [Pydantic AI docs: Durable execution overview](https://pydantic.dev/docs/ai/integrations/durable_execution/overview/)

**Design references for a hand-rolled store**
- **OpenAI Symphony spec** (Draft v1, Apache-2.0; repo created 2026-02-26, 27,677 stars, last push 2026-09-15, Elixir reference implementation; https://github.com/openai/symphony/blob/main/SPEC.md):
  - The orchestrator is the single authority that mutates scheduling state.
  - Issue claim states: `Unclaimed`, `Claimed`, `Running`, `RetryQueued`, `Released`.
  - Run attempt phases: `PreparingWorkspace`, `BuildingPrompt`, `LaunchingAgentProcess`, `InitializingSession`, `StreamingTurn`, `Finishing`, then terminal `Succeeded`, `Failed`, `TimedOut`, `Stalled` or `CanceledByReconciliation`. "Distinct terminal reasons are important because retry logic and logs differ."
  - Restart recovery is "tracker-driven and filesystem-driven (without a durable orchestrator DB)".
  - Failure retries back off as `min(10000 * 2^(attempt-1), max_retry_backoff_ms)`, default cap 5 minutes. Stall detection kills a worker after `stall_timeout_ms` (default 5 minutes) without agent events.
  - Defaults: `max_turns` 20 per worker session, `max_concurrent_agents` 10, `turn_timeout_ms` 1 hour (an inactivity timeout, not a total cap).
  - Workspace hooks `after_create`, `before_run`, `after_run` and `before_remove` each have a 60-second timeout.
  - Reconciliation runs before dispatch on every tick, and per-issue workspaces are preserved across runs — [openai/symphony SPEC.md](https://github.com/openai/symphony/blob/main/SPEC.md)
- **Ramp Inspect:** Cloudflare Durable Objects give each session its own SQLite database. A snapshot after each session lets follow-ups resume. A GitHub App mints a fresh installation token per clone. PRs are opened with the user's own token so users can't approve their own changes. Webhooks track PR status — [Ramp Builders](https://builders.ramp.com/post/why-we-built-our-background-agent) (post undated on the page)
- **12-factor agents:** Factor 5 "Unify execution state and business state", Factor 6 "Launch/Pause/Resume with simple APIs" (external triggers like webhooks resume agents), Factor 12 "Make your agent a stateless reducer" — [humanlayer/12-factor-agents](https://github.com/humanlayer/12-factor-agents) (Apache-2.0 licence file, 26,680 stars, **last push 2025-09-21**, so stale as a living doc)

### Inferences
- **Recommended path:** keep the async state machine, but make persistence explicit now, which is M4's "sqlite run store" in `product-plan.md`.
  1. Tables: `runs` (id, goal, repo, base_sha, state enum, budget, attempt, created/updated), `steps` (run_id, seq, kind, state, input_hash, output_ref, started/ended, error_category), `evidence` (step_id, kind, uri, sha256), `checks` (locked contracts).
  2. Write state **synchronously** before a side effect and after its result (LangGraph `"sync"` semantics). WAL mode.
  3. Make every step idempotent, keyed by (run_id, seq, input_hash), so a resumed run reuses saved outputs (DBOS semantics).
  4. Keep screenshots, traces and logs on disk or object storage and store only pointers (the DBOS and Temporal limits both point this way).
  5. Record the coding-agent session id (for example Claude Code session or Codex thread) and the git checkpoint SHA per turn, so a resumed run continues the agent conversation and can roll back code.
  6. Use distinct terminal reasons (`succeeded`, `failed_checks`, `budget_exhausted`, `timed_out`, `stalled`, `cancelled`, `needs_human`), as in Symphony.
- **Trigger to adopt DBOS:** more than one worker process, webhook-driven runs on a server, or a need for durable timers and queues with concurrency limits. Its decorator model can wrap the existing step functions, and its SQLite default means the CLI could use it unchanged. The risk is that DBOS requires deterministic workflow functions, so the agent subprocess call and the browser run must be steps.
- **Why not Temporal first:** a separate server process (even in dev), sandbox and passthrough friction with Playwright and subprocess-heavy code, and event-history limits that rule out streaming agent events into history. Its strengths (multi-language, massive scale) are not Contexer's near-term constraints.
- **Why not LangGraph now:** checkpointing is attractive, but the graph DSL adds framework weight to a loop the team already models as a bounded state machine. Take the ideas: thread id, durability modes, interrupts as human checkpoints.
- Symphony shows an alternative for the GitHub App phase: treat GitHub (PR plus check-run state) as the system of record and reconcile on every tick. Contexer could combine both, with a local store for evidence and steps and GitHub or the tracker for "what should be running".

### Gaps
- The full LangGraph durable-execution page body was not retrieved (only search snippets), so idempotency guidance comes from the snippet summary.
- No independent benchmark compares DBOS-on-SQLite reliability under concurrent CLI and worker use. DBOS states only that Postgres is recommended for production.
- Prefect 3 mid-flow resume semantics (transactions, result persistence) were not researched in depth. The verdict rests on its stated data-pipeline orientation and server requirement.
- Restate Python SDK maturity beyond "versions < 0.10 deprecated" was not assessed.

---

## Key Question 3: What should Contexer use for observability and cost tracking/control of long agent runs?

### Takeaway
Emit **OpenTelemetry** with the **GenAI semantic conventions** (`invoke_agent`, `execute_tool`, `invoke_workflow`, `gen_ai.usage.*`). They are still "Development" status and moved in 2026 to a dedicated repo, so pin a version. Store a local copy of each run's trace and cost in the run store, and treat Langfuse, Phoenix and Logfire as optional OTLP destinations rather than dependencies. For the *coding agent's* spend, the cheapest accurate source is the agent's own telemetry: Claude Code exports `claude_code.cost.usage` and per-request `cost_usd` over OTel, and accepts `OTEL_RESOURCE_ATTRIBUTES` for tagging a run id. Hard budget enforcement across agents needs a gateway (`ANTHROPIC_BASE_URL` → LiteLLM or similar). LiteLLM budgets require Postgres, and LiteLLM's PyPI package was compromised in March 2026, so pin hashes if used.

### Cited Findings

**Building-block table** (gh metadata 2026-10-14)

| Block | Repo / docs | License | Stars | Last push / release | Python | What it does | Verdict |
|---|---|---|---|---|---|---|---|
| OTel GenAI semantic conventions | https://github.com/open-telemetry/semantic-conventions-genai | Apache-2.0 | 439 (repo created 2026-05-05) | 2026-10-14 | n/a | Spans, metrics and events for GenAI clients, agents, MCP and providers | **BUILD ON** (attribute names and span shapes) |
| opentelemetry-python-contrib | https://github.com/open-telemetry/opentelemetry-python-contrib | Apache-2.0 | 1,113 | 2026-10-14 | — | OTel instrumentations for Python modules | **BUILD ON** (httpx etc. instrumentation) |
| Langfuse | https://github.com/langfuse/langfuse · https://github.com/langfuse/langfuse-python | MIT outside `ee/` dirs (copyright "ClickHouse, Inc." in LICENSE); SDK MIT | 35,820 / 502 | 2026-10-14 / server v4.59.0; SDK 5.0.1 | SDK >=3.11 | Open-source LLM tracing and evals platform | **BORROW IDEAS / optional exporter target**: self-host is heavy |
| Arize Phoenix | https://github.com/Arize-ai/phoenix | **Elastic License 2.0** | 11,834 | 2026-10-14 / v20.21.3 | >=3.11,<3.15 | OTel/OpenInference tracing and evals; Docker/Helm self-host | **BORROW IDEAS / optional local viewer**: ELv2 forbids offering it as a hosted service |
| OpenInference | https://github.com/Arize-ai/openinference | Apache-2.0 | 1,264 | 2026-10-14 | — | OTel instrumentations for AI frameworks | Optional |
| OpenLLMetry (Traceloop) | https://github.com/traceloop/openllmetry | Apache-2.0 | 7,494 | 2026-10-13 / traceloop-sdk 0.62.4 | >=3.10 | Standard OTel instrumentations for LLM providers (OpenAI, Anthropic, …) and vector DBs | **BORROW** individual instrumentations if Contexer calls LLM SDKs directly |
| LiteLLM | https://github.com/BerriAI/litellm · https://docs.litellm.ai | MIT outside `enterprise/` | 61,237 | 2026-10-14 / v1.105.1 (pyproject on main: 1.107.0) | >=3.10,<3.15 | Python SDK + AI Gateway (proxy): virtual keys, spend tracking, budgets, rate limits; repo description now says "Rust core with Python SDK" | **BORROW IDEAS / optional gateway**; **AVOID as a hard dependency** of the CLI |
| Pydantic Logfire | https://github.com/pydantic/logfire | SDK MIT; server **closed source** | 4,512 | 2026-10-14 / v5.2.0 | >=3.10 | Opinionated OTel wrapper; SDK can export to any OTel backend | **BORROW**: fine as an OTel convenience layer, but don't tie Contexer to the closed backend |

**OTel GenAI conventions**
- The GenAI semconv pages on opentelemetry.io now say they "have moved" to the `semantic-conventions-genai` repository — [OpenTelemetry: GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/); [semantic-conventions-genai README](https://github.com/open-telemetry/semantic-conventions-genai)
- Agent span operations `create_agent`, `execute_tool`, `invoke_agent` and `invoke_workflow` are all **Development** status. The span name SHOULD be `invoke_agent {gen_ai.agent.name}`. `gen_ai.usage.input_tokens` (Development, Recommended) SHOULD include cached tokens. Docs exist for Anthropic, OpenAI, Bedrock, Azure AI Inference, MCP, events, metrics and token metrics — [semantic-conventions-genai docs/gen-ai](https://github.com/open-telemetry/semantic-conventions-genai/tree/main/docs/gen-ai) (read via gh, 2026-10-14)
- OpenLLMetry says "Our semantic conventions are now part of OpenTelemetry!" — [OpenLLMetry README](https://github.com/traceloop/openllmetry)

**Coding-agent telemetry (Claude Code)**
- Telemetry is enabled with `CLAUDE_CODE_ENABLE_TELEMETRY=1` plus `OTEL_METRICS_EXPORTER` / `OTEL_LOGS_EXPORTER` (otlp, prometheus or console) and the OTLP endpoint and protocol. Traces are beta and need `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1` and `OTEL_TRACES_EXPORTER` — [Claude Code docs: Monitoring usage](https://code.claude.com/docs/en/monitoring-usage)
- Metrics: `claude_code.cost.usage` (USD), `claude_code.token.usage` (type input, output, cacheRead or cacheCreation), `claude_code.session.count`, `claude_code.lines_of_code.count`, `claude_code.commit.count`, `claude_code.pull_request.count` and `claude_code.active_time.total`. Events: `claude_code.api_request` (with `cost_usd`, tokens, `duration_ms`, `request_id`), `claude_code.tool_result`, `claude_code.tool_decision` and `claude_code.user_prompt` (prompt redacted unless `OTEL_LOG_USER_PROMPTS=1`). `session.id` is included by default. Custom tags go in `OTEL_RESOURCE_ATTRIBUTES` (no spaces) — [Claude Code docs: Monitoring usage](https://code.claude.com/docs/en/monitoring-usage)
- Claude Code can be pointed at any gateway that exposes a supported API format via `ANTHROPIC_BASE_URL` plus a gateway credential or `apiKeyHelper`. Anthropic "doesn't endorse, maintain, or audit third-party gateway products". Gateways provide credentials, usage attribution, budgets, rate limits and audit logs, but must be kept updated as Claude Code adds features. `allowedProviders: ["customEndpoint"]` (v2.1.285+) forces a gateway — [Claude Code docs: Other LLM gateways](https://code.claude.com/docs/en/llm-gateway)

**LiteLLM budgets and the supply-chain incident**
- Budgets are available at global proxy, team, team member, internal user, virtual key, per-model (enterprise) and end-user/customer levels, with `budget_duration` resets such as "30d". Over-budget requests fail with `ExceededTokenBudget` / `budget_exceeded` errors (examples show 400, 429 and 401 by type). TPM, RPM and max-parallel limits are available. **"Budgets require a database"** (Postgres); without one the global `max_budget` fails open and key, team and user budgets error with "No connected db" — [LiteLLM docs: Budgets, rate limits](https://docs.litellm.ai/docs/proxy/users)
- On **2026-03-24**, LiteLLM PyPI versions **1.82.7 and 1.82.8** were malicious. A `.pth` payload exfiltrated credentials such as SSH keys, cloud credentials, kube configs and `.env` files at interpreter start without needing `import litellm`. The PyPI token was reportedly leaked via a compromised Trivy step in CI. GitHub source was not modified. Exposure-window reports vary (about 2 to under 5 hours) — [NetSPI](https://www.netspi.com/blog/executive-blog/ai-ml-pentesting/litellm-supply-chain-compromise/); [pypistats blog](https://pypistats.com/blog/litellm-pypi-supply-chain-compromise-how-a-popular-llm-proxy-became-a-credential-stealing-backdoor-march-24-2026); [bastion.tech](https://bastion.tech/blog/litellm-pypi-supply-chain-attack) (secondary security write-ups; no official advisory fetched)

**Langfuse / Phoenix / Logfire deployment facts**
- Langfuse self-host needs Langfuse Web, Langfuse Worker, **PostgreSQL, ClickHouse, Redis/Valkey and S3/blob storage**. Docker Compose is for "local use and testing" (single VM, no HA or backups), and production uses Helm or cloud templates. EE-marked features are Organization Creators, Instance Management API and UI customisation (docs "Version: v4") — [Langfuse: Self-hosting](https://langfuse.com/self-hosting)
- Phoenix runs locally, in a container (Docker Hub image, Helm chart) or in the cloud. It instruments via OpenInference and lists the Claude Agent SDK, OpenAI Agents SDK, LangGraph and LiteLLM among integrations. Arize AX is the managed version — [Phoenix README](https://github.com/Arize-ai/phoenix)
- Logfire: "the server application for recording and displaying data is closed source". The SDKs are open source and can export to any OTel-compatible backend — [Logfire README](https://github.com/pydantic/logfire)

### Inferences
- **Instrument Contexer's own loop with OTel spans** named after GenAI semconv: `invoke_workflow contexer.run` → `invoke_agent claude-code` (one per executor turn) → `execute_tool browser.verify` / `execute_tool check.<id>`. Attach `contexer.run_id`, `contexer.attempt`, `contexer.check_id` and the verdict as custom attributes. Pin the semconv version because everything is Development status.
- **Per-run cost without a gateway:** launch the coding agent with `CLAUDE_CODE_ENABLE_TELEMETRY=1`, an OTLP endpoint served by Contexer (or a local collector), and `OTEL_RESOURCE_ATTRIBUTES=contexer.run_id=<id>`. Then sum `cost_usd` from `claude_code.api_request` events per run. This gives a budget meter Contexer can enforce by stopping the agent between turns. For Contexer's own LLM calls (criteria compiler, judge), record provider `usage` directly. Codex and OpenCode telemetry equivalents were not verified (see gaps).
- **Hard cap across agents** (mid-turn enforcement) needs a gateway. Offer "bring your own gateway" (set `ANTHROPIC_BASE_URL`) rather than bundling LiteLLM. If LiteLLM is used, pin exact versions with hashes, given the March 2026 compromise and the Postgres requirement for budgets.
- **Default sink = local:** write spans and events into the SQLite run store or JSONL next to the evidence, so the evidence report can show cost, time and tokens per attempt with no external service. Optional OTLP export lets teams send the same data to Langfuse, Phoenix, Logfire, Datadog and similar. Avoid making Langfuse (four backing services) or Phoenix (ELv2) a required component of a product that may later be offered as a hosted GitHub App.

### Gaps
- Not verified: Codex CLI and OpenCode OTel or cost-export capabilities. Codex `[otel]` config exists in my prior knowledge but was not checked in this session.
- No official LiteLLM security advisory was fetched; incident details come from third-party security blogs.
- The OTel GenAI `OTEL_SEMCONV_STABILITY_OPT_IN` value for the 2026 conventions was not confirmed.
- Langfuse's licence-key-gated feature list beyond the three EE items was not enumerated.

---

## Key Question 4: What design lessons do the published architecture write-ups offer, stated as concrete patterns Contexer could adopt?

### Takeaway
The write-ups agree on five ideas:
1. **Deterministic code owns control flow, and the agent is a bounded node inside it** (Stripe blueprints, Spotify, Symphony, 12-factor).
2. **Verification must be executable, run by the harness rather than trusted from the agent, and the agent must not be able to edit the verifier** (Anthropic's "unacceptable to remove or edit tests", Spotify's stop-hook verifiers, Claude Code's Stop hook and `/goal`).
3. **Cap retries hard and hand off to a human** (Stripe: at most 2 CI rounds; Symphony: `max_turns` 20 and backoff; 12-factor: about 3 consecutive errors).
4. **Keep context small and stable** (trimmed verifier output, error compaction, append-only and cache-friendly prefixes, file-based progress notes, single-threaded agents).
5. **An LLM judge after deterministic checks catches scope creep, not correctness** (Spotify: vetoes about 25% of sessions).

Spec-driven tools (Spec Kit, Kiro) confirm "requirements → properties → tests" as a direction. But Spec Kit's `converge` is LLM-judged, not executable, and that gap is Contexer's opening.

### Cited Findings

**Anthropic: "Building effective agents" (2024-12-19)** — https://www.anthropic.com/engineering/building-effective-agents
- Workflows (predefined code paths) vs agents (the LLM directs its own process). Start with the simplest solution.
- Five workflow patterns: prompt chaining with programmatic "gate" checks, routing, parallelization (sectioning or voting), orchestrator-workers, and **evaluator-optimizer** (one LLM generates, another evaluates in a loop; fits when evaluation criteria are clear).
- Agents need "ground truth" from the environment at each step. Include human checkpoints and stopping conditions "such as a maximum number of iterations".
- Invest in the agent-computer interface: requiring absolute file paths fixed SWE-bench agent errors. Start with direct API calls; frameworks obscure prompts.

**Anthropic: "Effective harnesses for long-running agents" (2025-11-26)** — https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- Initializer agent (writes `init.sh`, a progress log and the first git commit) then coding agents that make incremental progress.
- Feature list in **JSON with a `passes` field**: more than 200 features, all initially failing. Agents may change only `passes`. JSON was chosen because the model is less likely to overwrite it than Markdown.
- Agents were told it is "unacceptable to remove or edit tests".
- One feature at a time. Each session starts by reading git log and the progress file, running `init.sh` and a basic end-to-end check.
- Without prompting, Claude used unit tests or curl and missed end-to-end failures; browser automation (Puppeteer MCP) testing "as a human user would" caught them. Native browser `alert` modals were not visible to the agent.
- Failure modes: declaring victory early, marking features done without testing, leaving the environment broken, wasting time working out how to run the app.

**Anthropic: "Writing effective tools for agents" (2025-09-11)** — https://www.anthropic.com/engineering/writing-tools-for-agents
- Consolidate tools around workflows (`search_contacts`, not `list_contacts`). Namespace tools (`asana_search`). Return high-signal fields, not UUIDs. Offer `response_format` concise or detailed (concise used about 1/3 of the tokens in their example). Paginate and truncate with defaults. Write actionable error messages. Build evals of multi-step tasks with verifiable outcomes. Use unambiguous parameter names (`user_id`, not `user`).

**Claude Code best practices (code.claude.com, read 2026-10-14)** — https://code.claude.com/docs/en/best-practices
- "Give Claude a check it can run". Without one, "looks done" is the only signal.
- Four gate strengths: in-prompt; a `/goal` condition re-checked by a separate evaluator each turn; **a Stop hook as a deterministic gate**, which blocks the turn from ending until the check passes and has a cap on consecutive blocks; and a verification subagent or workflow so the worker isn't its own grader.
- Have Claude show evidence (command and output, screenshot) rather than assert success.
- After two failed corrections, `/clear` and restart with a better prompt.
- Headless `claude -p` with `--output-format json` or `stream-json`. `--permission-mode dontAsk` plus `--allowedTools` for unattended runs.
- Adversarial reviewers over-report gaps, so tell them to flag only correctness or requirement gaps.
- Claude Code now ships a `/verify` skill to confirm a change against the running app. That overlaps with Contexer's `/verify` command name and positioning.

**OpenAI: "Harness engineering" (Feb 2026, Ryan Lopopolo) and Symphony**
- Primary post (https://openai.com/index/harness-engineering/) returned HTTP 403 to fetch. Points below are from secondary summaries. Reportedly: a product built with no hand-written code; AGENTS.md as a short map into a structured `docs/` directory; layered architecture enforced by custom linters and structural tests; recurring "garbage collection" passes for drift; Chrome DevTools Protocol wired in for UI validation; per-worktree ephemeral observability (LogQL, PromQL); agent-to-agent review with human review optional; about 1,500 merged PRs, about 3.5 PRs per engineer per day, 3 → 7 engineers, 6+ hour agent sessions — [rywalker.com summary](https://rywalker.com/research/openai-harness) (secondary; the author discloses he is Tembo's CEO); [36kr](https://eu.36kr.com/en/p/3715546375188870)
- **Symphony** (open-sourced by OpenAI, repo created 2026-02-26): monitors a Linear board, spawns agents per task, and requires "proof of work": CI status, PR review feedback, complexity analysis and walkthrough videos. Accepted work lands safely. Workflow policy lives in-repo as `WORKFLOW.md`. Successful runs may end at a handoff state such as `Human Review`, not `Done`. The agent is driven via `codex app-server` over stdio with continuation turns on the same thread — [openai/symphony README](https://github.com/openai/symphony); [SPEC.md](https://github.com/openai/symphony/blob/main/SPEC.md)
- "Unrolling the Codex agent loop" (2026-01-23, Michael Bolin): primary not fetchable (403). Secondary write-ups say compaction replaces history via a `/responses/compact` endpoint and resets the cache prefix, and that changing tools or AGENTS.md mid-session breaks prompt caching — [OpenAI (index)](https://openai.com/index/unrolling-the-codex-agent-loop); [codex.danielvaughan.com](https://codex.danielvaughan.com/2026/04/21/codex-cli-prompt-caching-maximise-cache-hits-cost-reduction/) (secondary, unverified)

**Cognition: "Don't build multi-agents" (2025-06-12, Walden Yan)** — https://cognition.com/blog/dont-build-multi-agents
- Principle 1: share full agent traces, not just messages. Principle 2: actions carry implicit decisions, and conflicting decisions produce bad results (the Flappy Bird example).
- Default to a single-threaded linear agent. For very long tasks, use a context-compression model.
- Subagents should mostly answer well-scoped questions, not write code in parallel.

**HumanLayer: 12-factor agents** — https://github.com/humanlayer/12-factor-agents (last push 2025-09-21)
- Factors: 1 NL→tool calls; 2 own your prompts; 3 own your context window; 4 tools are structured outputs; 5 unify execution and business state; 6 launch/pause/resume with simple APIs; 7 contact humans with tool calls; 8 own your control flow; 9 compact errors into context; 10 small, focused agents; 11 trigger from anywhere; 12 stateless reducer.
- Factor 9 suggests an error counter limiting about 3 attempts of a tool, with escalation to a human "via deterministic takeover of the control flow" — [factor-09](https://github.com/humanlayer/12-factor-agents/blob/main/content/factor-09-compact-errors.md)

**Manus: "Context Engineering for AI Agents" (2025-07-18, Yichao "Peak" Ji)** — https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus
- KV-cache hit rate is the key production metric. Input:output ratio is about 100:1. Cached vs uncached Sonnet input is $0.30 vs $3 per MTok.
- Stable prompt prefix (no second-precision timestamps), append-only context, deterministic serialization.
- Mask tools via logits or state rather than removing them.
- File system as restorable external memory. Recite goals via a rewritten `todo.md` (about 50 tool calls per task).
- Keep errors in context. Add controlled variation to avoid few-shot ruts.

**Stripe Minions**
- Part 1 (2026-02-09, Alistair Gray) — https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents
  - "Over a thousand" fully minion-written PRs merged weekly, all human-reviewed.
  - Mostly started from Slack. Devboxes are pre-warmed in about 10 seconds and isolated from production and the internet, so no permission prompts are needed.
  - Local lint on push takes under 5 seconds. CI selects tests from more than 3M. Autofixable failures are fixed automatically; others go back to the agent.
  - **CI capped at 2 rounds per task** for token, compute and time cost.
  - Core loop is a fork of Block's goose. Toolshed MCP has more than 400 tools.
- Part 2 (2026-02-19) — https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2
  - More than 1,300 PRs per week.
  - **Blueprints** are code-defined workflows mixing deterministic nodes ("Run configured linters", "Push changes"; no LLM) with agent nodes ("Implement task", "Fix CI failures").
  - Rule files are scoped to subdirectories or file patterns and synced from Cursor format to Claude Code format.
  - Toolshed has nearly 500 tools, but minions get a small curated subset.
  - After the second CI run the branch goes to a human operator.

**Spotify Honk, Part 3 (2025-12-09, Max Charas and Marc Bruggmann)** — https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3
- Failure modes ranked: no PR (tolerable) < PR fails CI < **PR passes CI but is functionally wrong** (worst; erodes trust).
- Verifiers are deterministic and auto-activated by repo contents (for example Maven when `pom.xml` exists). They are exposed to the agent as abstract MCP tools.
- Output is regex-trimmed: short success messages and only the relevant error lines.
- All verifiers run in a **Claude Code stop hook**, and a failure blocks PR creation.
- An LLM judge (diff plus original prompt) runs after the verifiers, vetoes about a quarter of sessions, and the agent course-corrects about half the time. The top trigger is going beyond the prompt's scope. No evals exist for the judge yet.
- The agent cannot push, talk on Slack or author prompts; the surrounding infrastructure does those. It runs in a limited-permission container.

**Ramp Inspect** (Ramp Builders; publication date not shown on page) — https://builders.ramp.com/post/why-we-built-our-background-agent
- Modal VMs with the full dev environment. Per-repo images are rebuilt every 30 minutes, and sessions start from a snapshot.
- OpenCode chosen for its server-first design and typed SDK. A plugin blocks edits until repo sync finishes.
- Verification includes tests, telemetry (Sentry, Datadog), feature flags (LaunchDarkly) and visual checks (screenshots, live previews).
- The success metric is the share of merged PRs, about 30% of frontend and backend PRs at writing.
- Ramp published the post as a spec others can paste into a coding agent. Later coverage cites figures above 50% (Modal) — [Modal blog](https://modal.com/blog/how-ramp-built-a-full-context-background-coding-agent-on-modal); [InfoQ 2026-01](https://infoq.com/news/2026/01/ramp-coding-agent-platform/) (secondary; numbers vary over time)
- Open-source derivative: https://github.com/ColeMurray/background-agents (MIT, 3,358 stars, pushed 2026-10-14, TypeScript). Modal's blog frames it as "Open-Inspect".

**Factory: "Agent Readiness" (2026-01-20)** — https://factory.com/news/agent-readiness
- Eight pillars: Style & Validation, Build System, Testing, Documentation, Dev Environment, Code Quality, Observability, Security & Governance.
- Five levels: Functional, Documented, Standardized, Optimized, Autonomous. A level needs 80% of its criteria plus all earlier levels, and Level 3 is the recommended target.
- 60+ binary criteria. Score variance fell from about 7% to 0.6% after grounding each evaluation on the prior report.
- Examples: CockroachDB L4 (74%), FastAPI L3 (53%), Express L2 (28%) (vendor data).
- Thesis (vendor framing): the agent isn't broken, the environment is.

**Every: "Compound engineering" (2025-12-11, Dan Shipper and Kieran Klaassen)** — https://every.to/chain-of-thought/compound-engineering-how-every-codes-with-agents
- Loop: Plan → Work → Review → Compound. Compounding means recording bugs and fixes as reusable prompts or plugins, "the money step".
- Claims about 80% of effort goes to plan and review.
- The review step runs 12 parallel reviewer subagents (security, performance, over-engineering…) and synthesizes them for a human decision.
- Work uses Playwright or XcodeBuildMCP to test like a user.

**Spec-driven approaches**
- **GitHub Spec Kit** — https://github.com/github/spec-kit (MIT, 141,251 stars per gh, v1.2.0 released 2026-10-13, Python CLI)
  - Flow: `/speckit-constitution` once, then per feature `specify → plan → tasks → implement → converge`, repeating implement → converge until it reports "Converged". Also bug (`/speckit-bug-assess|fix|test`) and idea-assessment flows — [README](https://github.com/github/spec-kit)
  - `converge` "assess[es] the current codebase against the feature's spec, plan, and tasks" and appends unbuilt work to `tasks.md`. It is LLM reading, not executable checks — [templates/commands/converge.md](https://github.com/github/spec-kit/blob/main/templates/commands/converge.md)
  - Commands support **extension hooks** from `.specify/extensions.yml` (`before_/after_specify`, `before_/after_tasks`, `before_/after_implement`, `before_converge`, …). `optional: false` hooks are executed automatically — [converge.md](https://github.com/github/spec-kit/blob/main/templates/commands/converge.md); [docs/reference/extensions.md](https://github.com/github/spec-kit/blob/main/docs/reference/extensions.md)
- **Kiro** — https://kiro.dev/docs/specs/ ; https://kiro.dev/docs/specs/correctness/
  - Specs produce `requirements.md` (or `bugfix.md` with current, expected and *unchanged* behaviour), `design.md` and `tasks.md`. Tasks run in dependency "waves".
  - Correctness properties are extracted from **EARS** requirements ("THE System SHALL …") and turned into "for any…" properties. Property-based tests run hundreds or thousands of cases, with shrinking to a minimal counterexample.
  - On failure, Kiro offers to fix the implementation, the test or the spec. Properties link back to requirements and tasks. PBT is IDE-only and described as evidence, not proof.
- Kiro PBT blog (2025-11-17, Aaron Eline): acceptance criteria → textual properties (invariants, round-trips, idempotence) → Hypothesis tests (100 cases by default) under pytest. Shrinking found a duplicate-handling bug from a two-node counterexample — [Kiro blog: Property-based testing](https://kiro.dev/blog/property-based-testing/)

### Inferences: patterns Contexer could adopt
1. **Blueprint the loop.** Treat Contexer's state machine as a Stripe-style blueprint. Deterministic nodes (compile checks, start app, lint, run checks, snapshot git, push, post check run) wrap exactly two agent nodes, "implement" and "repair from failing checks". Only deterministic nodes push, comment or set statuses (Spotify: the agent cannot push or talk to users).
2. **Tamper-proof contracts.** Store approved checks outside the agent's write scope, or hash them and fail the run if they change. Anthropic's JSON `passes` file and "unacceptable to remove or edit tests" show the risk; Spotify's judge catches "disabling flaky tests". Approved contracts should be immutable to the executor.
3. **Verifier as gate, not suggestion.** Install a Claude Code **Stop hook** (or the agent's equivalent) in the executor's workspace that runs Contexer's fast checks and blocks "done" until they pass. Mind the documented cap on consecutive blocks. Then re-verify independently in Contexer's own browser run before reporting (the worker must not grade itself).
4. **Hard retry caps with human handoff.** Default to at most 2 repair rounds per run, as Stripe does, and stop early when the same check fails twice with the same error class (12-factor about 3 errors; Claude Code's "after two failed corrections, clear"). Escalate with a `needs_human` terminal state and an `action_required` check conclusion.
5. **Compact, trimmed feedback.** Feed the repair agent only the failing check, expected vs observed, a screenshot path and the top relevant log lines, regex-trimmed as Spotify does. Keep successes to one line. Keep errors in context but append-only (Manus), and start a fresh agent session rather than accumulating failed attempts once the cap nears.
6. **Scope-creep judge after deterministic checks.** An optional LLM judge on the diff vs the approved goal, labelled as judgment, matches Contexer's "labelled judgment fallback". Expect it to veto about 25% of runs (Spotify). Eval the judge on M0 before trusting it.
7. **Distinct terminal reasons and stall detection** (Symphony): kill and retry on agent inactivity; use per-attempt timeouts that reset on events; preserve workspaces between attempts.
8. **Handoff state, not "Done".** A successful run ends at "Ready for human review" with proof of work (Symphony): evidence report, check run, screenshots or video.
9. **Repo-owned policy file.** A `CONTEXER.md`/`contexer.yaml` in the repo (like `WORKFLOW.md`, Spec Kit's constitution, or CodeRabbit's `.coderabbit.yaml`) versions check modes (`warning`/`error`), budgets, start commands and hooks with the code.
10. **Environment readiness first.** Before running the loop, score the repo for "can Contexer run and verify this?" (start command, seed data, test login, health URL), following Factory's agent-readiness and Anthropic's `init.sh` lesson. Fail fast with setup guidance, because unverifiable environments drive false results.
11. **Single-threaded executor, parallel verifiers.** Don't parallelize code-writing agents on one change (Cognition). Parallelize read-only verification and review (Every's 12 reviewers; Claude Code subagents for investigation).
12. **Cache-friendly prompts.** Keep a stable system prefix and tool set for the executor across repair turns, and put per-attempt failure data at the end (Manus; Codex caching notes).
13. **Compound learnings.** Saved checks become regression tests, and repeated failure classes become repo rules or hooks (Every's "compound" step; Stripe's scoped rule files).
14. **Spec-tool interop.** Register Contexer as a mandatory Spec Kit `after_implement` / `before_converge` extension hook, so Spec Kit users get executable acceptance evidence instead of LLM-judged convergence. Accept Kiro/EARS-style "WHEN … THE SYSTEM SHALL …" criteria as input to the check compiler, and consider property-style checks (any input in a class) where browser checks allow.

### Gaps
- OpenAI's harness-engineering and Codex agent-loop posts were not readable (HTTP 403). Their patterns come from secondary summaries and should be checked against the originals before quoting.
- Spotify Honk Parts 1–2 and Stripe-specific retry numbers beyond the 2-CI-round cap were not read in full. Spotify's Part 3 gives no retry or turn caps.
- The Ramp post shows no date on the page. Adoption numbers differ across secondary sources (about 30%, about 40%, over 50%).
- No primary source found for Kiro's PBT outcome statistics. The blog states none.
- Factory's agent-readiness data is vendor-reported, with no independent replication found.
