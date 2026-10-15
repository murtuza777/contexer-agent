# Runtime and environments: starting AI-written web apps reliably and in isolation (state as of 2026-10-14)

Method note: all GitHub metadata (stars, license SPDX id, last push, archived flag) was pulled with `gh api repos/OWNER/REPO` on 2026-10-14. Python SDK versions and `requires_python` came from `https://pypi.org/pypi/<pkg>/json` and npm versions from `https://registry.npmjs.org/<pkg>/latest` on the same day. "Vendor claim" means the number comes from the vendor's own marketing or docs and was not measured independently. Verdicts (BUILD ON / BORROW IDEAS / AVOID) are this researcher's judgement for Contexer and appear only in the Inferences sections.

## Q1. Sandboxes and isolated environments: which are free locally and in CI, and which are worth offering as an optional hosted backend?

### Takeaway
No sandbox is needed for Contexer's default path. Running the app as plain host processes in a per-attempt git worktree works free on Windows, macOS, Linux and CI. E2B is the best optional hosted backend because it has a Python SDK, Firecracker microVMs, public per-port URLs, start/ready-command templates, an Apache-2.0 runtime you can self-host on Linux, and a $100 one-time free credit. Docker plus the devcontainers CLI is the free local and Linux-CI isolation option. Avoid these as foundations: Daytona (its core went closed-source in June 2026), Cloudflare (TypeScript and Workers only), Coder and Ona (whole platforms), and raw Firecracker or gVisor (you would be building a fleet).

### Cited Findings

**E2B (hosted, with an open-source runtime)**
- `e2b-dev/E2B` (SDKs/CLI): 14,347 stars, Apache-2.0, last push 2026-10-13, Python, "Open-source, secure environment with real-world tools for enterprise-grade agents" — [GitHub](https://github.com/e2b-dev/E2B)
- `e2b-dev/infra` has been renamed `e2b-dev/runtime`: 1,716 stars, Apache-2.0, last push 2026-10-14, Go, "The runtime behind every E2B stack: Cloud, Enterprise, and your own machine" — [GitHub](https://github.com/e2b-dev/runtime)
- Architecture: one Firecracker microVM per sandbox. Creating a sandbox restores a pre-booted snapshot instead of booting a kernel. Memory is loaded lazily via `userfaultfd` and the root filesystem is copy-on-write. Each sandbox has an nftables egress firewall with domain allow/deny lists. Any listening port is reachable at `https://<port>-<sandbox>.<domain>` with per-sandbox access tokens. Sandboxes support pause/resume and fork (up to 100 per request) — [runtime README](https://github.com/e2b-dev/runtime)
- Self-hosting: "E2B Embed runs the whole E2B stack, every feature included, on a single machine". The options are a Linux host via Docker Compose (`docker compose up -d --wait`) or one VM on GCP or AWS via Terraform — [Embed README](https://github.com/e2b-dev/runtime/blob/main/embed/README.md)
- Pricing (2026-10-14):
  - Hobby: $0 with a one-time $100 credit, no card, 20 concurrent sandboxes, 1-hour max session.
  - Pro: $150/month plus usage, 100 concurrent, 24-hour sessions. Pro+ allows 600 concurrent for $650/month. Enterprise has a $3,000/month minimum.
  - Usage: $0.000014 per vCPU-second and $0.0000045 per GiB-second. Storage is free.
  - Sizes: 1–8 vCPU and 1–8 GiB, default 2 vCPU / 4 GiB, CPU only.
  — [E2B pricing](https://e2b.dev/pricing)
- Python SDK: `e2b` 2.56.0, uploaded 2026-10-13, `requires_python >=3.11`. The pricing page still says Python 3.10+, so the PyPI metadata is newer — [PyPI](https://pypi.org/project/e2b/); [pricing](https://e2b.dev/pricing)
- Web apps: `sandbox.get_host(3000)` returns `https://3000-<id>.e2b.app`. URLs are public by default, and the docs warn to "Treat a public URL like a credential" unless public access is restricted — [docs: public URL](https://docs.e2b.dev/network/public-url.md)
- Dev servers: `sandbox.commands.run(cmd, background=True)` streams stdout/stderr and returns a handle with `.kill()`. A later process can reconnect with `Sandbox.connect(id)` and `commands.connect(pid)` — [docs: background commands](https://docs.e2b.dev/commands/background.md)
- Templates: `Template().set_start_cmd("npm start", wait_for_port(3000))`, `wait_for_url(...)`, or a shell ready-command runs at template build time and snapshots the running process. "When you later create a sandbox from that template, the snapshotted process is **already running**." Env vars passed to `Sandbox.create()` are not visible to the start command — [docs: start & ready commands](https://docs.e2b.dev/template/start-ready-command.md)
- The docs index lists a Next.js template, a Docker/Docker Compose template, a GitHub Actions CI/CD use case, snapshots, fork, internet access allow/deny lists and egress secret injection — [docs index](https://docs.e2b.dev/llms.txt)

**Daytona (hosted; core development went closed-source)**
- `daytonaio/daytona`: 71,552 stars, **archived**, last push 2026-07-24. The GitHub API reports no SPDX license. README: "As of June 2026, Daytona's core development has moved to a private codebase. This repository will receive no further updates, fixes, or releases." The repo remains usable "as is" under its LICENSE at v0.190.0 — [GitHub](https://github.com/daytonaio/daytona)
- The new org's `daytona/clients` ("Official SDKs, API clients, and CLI/MCP tools") has 14 stars, license "Other", last push 2026-10-14 — [GitHub](https://github.com/daytona/clients)
- The Python SDK is still published: `daytona` 0.224.0 (2026-10-12), Python >=3.10. Calls include `Daytona(...)`, `daytona.create()` and `sandbox.process.code_run(...)` — [PyPI](https://pypi.org/project/daytona/); [docs](https://www.daytona.io/docs/en/)
- Pricing: $0.0504 per vCPU-hour, $0.0162 per GiB-hour of memory, and $0.000108 per GiB-hour of storage after the first 5 GiB free. Billing is per second, with "$200 in free compute". Vendor claim: "Sub 90ms sandbox creation" — [pricing](https://www.daytona.io/pricing)
- Previews: any port from 1 to 65535 at `https://{port}-{sandboxId}.{daytonaProxyDomain}`. Private sandboxes need the `x-daytona-preview-token` header. Signed URLs expire after 60 s by default (max 24 h) — [docs](https://www.daytona.io/docs/en/preview-and-authentication/)

**Modal Sandboxes (hosted, Python-native)**
- `modal-labs/modal-client`: 524 stars, Apache-2.0, last push 2026-10-14. PyPI `modal` 1.6.1 (2026-10-03) supports Python 3.10–3.14 — [GitHub](https://github.com/modal-labs/modal-client); [PyPI](https://pypi.org/project/modal/)
- API and limits:
  - Calls: `modal.Sandbox.create(app=..., image=..., runtime="gvisor"|"vm")`, `sb.exec(...)` and `sb.terminate()`.
  - Lifetime: 5 minutes by default, raisable to 24 h with `timeout`. `idle_timeout` is also available.
  - Readiness: `modal.Probe.with_tcp(8080)` or `Probe.with_exec(...)` plus `wait_until_ready()`. The probe times out after 5 minutes and does not terminate the sandbox.
  - Other: tunnels expose ports, and filesystem snapshots are recommended for work longer than 24 h.
  — [docs](https://modal.com/docs/guide/sandboxes)
- Pricing:
  - Starter: $0 with $30/month credits and 100 concurrent containers.
  - Team: $250/month with $100 credits.
  - Sandbox rates: $0.00003942 per core-second of CPU and $0.00000667 per GiB-second of memory, roughly 3x the standard Functions rates.
  — [pricing](https://modal.com/pricing)
- Architecture reference, Ramp "Inspect" (Modal blog, 2026-02-19):
  - A Modal Cron job runs every 30 minutes. It clones each repo, installs dependencies, runs initial builds and snapshots the filesystem. Snapshots are stored as diffs from the base image.
  - Each session starts from the latest snapshot, so syncing to HEAD is "nearly instant" and sessions start "in a few seconds".
  - The sandbox contains Postgres, Redis, Temporal, RabbitMQ, OpenCode, a VS Code server, a VNC stack and Chromium. The agent takes before/after screenshots, and tests run in the same sandbox.
  - About half of merged PRs were started by Inspect.
  — [Modal blog](https://modal.com/blog/how-ramp-built-a-full-context-background-coding-agent-on-modal)

**microsandbox (local microVMs, open source)**
- `superradcompany/microsandbox` (the old `microsandbox/microsandbox` and `zerocore-ai/microsandbox` URLs redirect here): 8,679 stars, Apache-2.0, last push 2026-10-14, Rust — [GitHub](https://github.com/superradcompany/microsandbox)
- What it does: runs OCI images as local microVMs, can fork and snapshot live sandboxes, and is embeddable with "No setup server. No long-running daemon."
  - Vendor claim: "Average boot times under 100 milliseconds."
  - Platforms: Linux with KVM, macOS on Apple Silicon, Windows with WHP enabled. Windows installs via `irm https://install.microsandbox.dev/windows | iex`.
  - SDKs: TypeScript, Rust, Python and Go.
  - "Microsandbox is still **beta software**."
  — [README](https://github.com/superradcompany/microsandbox)
- PyPI `microsandbox` 0.7.8 (2026-10-09), Python >=3.10 — [PyPI](https://pypi.org/project/microsandbox/)

**Vercel Sandbox (hosted)**
- `vercel/sandbox` (SDK + CLI): 210 stars, Apache-2.0, last push 2026-10-14 — [GitHub](https://github.com/vercel/sandbox)
- What it is:
  - Isolation: Firecracker microVMs. Listed uses include "Run development servers: Spin up and test applications with live previews."
  - SDKs and CLI: `@vercel/sandbox` (JS), the `vercel.sandbox` module in the `vercel` Python package, and a `sandbox` CLI.
  - Auth: Vercel OIDC tokens (`vercel link` plus `vercel env pull`) or access tokens "in external CI/CD systems or non-Vercel environments".
  - Default image: Node LTS, Python 3.14 and coding agents.
  - Vendor claim: sandboxes "start in milliseconds".
  — [docs, updated 2026-09-22](https://vercel.com/docs/sandbox)
- Pricing and limits:
  - Hobby (free): 5 h of Active CPU, 420 GB-h of memory, 5,000 creations, 10 concurrent sandboxes and 45-minute max sessions. Creation pauses once you exceed the quota.
  - Pro: $0.128 per Active CPU hour and $0.0212 per GB-hour, with 24-hour sessions.
  - Max 15 open ports per sandbox. The default timeout is 5 min. Snapshots expire 30 days after last use.
  - Vercel's example "AI code validation" (5 min, 2 vCPU) costs about $0.0092.
  — [pricing, updated 2026-09-10](https://vercel.com/docs/sandbox/pricing)
- PyPI `vercel` 0.11.6 (2026-10-07), Python >=3.10 — [PyPI](https://pypi.org/project/vercel/)

**Cloudflare Containers / Sandbox SDK (hosted)**
- `cloudflare/containers`: 275 stars, Apache-2.0, last push 2026-08-24. `cloudflare/sandbox-sdk`: 1,150 stars, last push 2026-10-13. The GitHub API reports NOASSERTION, but the LICENSE file is Apache 2.0 — [containers](https://github.com/cloudflare/containers); [sandbox-sdk](https://github.com/cloudflare/sandbox-sdk)
- The Sandbox SDK is `@cloudflare/sandbox` 0.x, driven from TypeScript inside a Worker. The page mentions no Python SDK. "Available on Workers Paid plan." — [docs](https://developers.cloudflare.com/sandbox/)
- Previews: call `sandbox.exposePort(port, {hostname})` and `proxyToSandbox()` in the Worker. URLs look like `https://{port}-{sandbox-id}-{token}.yourdomain.com`. Production "needs a custom domain with wildcard DNS routing". Tokens are a random 16 characters by default — [docs](https://developers.cloudflare.com/sandbox/concepts/preview-urls/)
- Containers pricing:
  - Plan: Workers Paid at $5/month includes 25 GiB-hours of memory, 375 vCPU-minutes and 200 GB-hours of disk.
  - Overage: $0.000020 per vCPU-second, billed per 10 ms of active time.
  - Instance types range from lite (1/16 vCPU, 256 MiB) to standard-4 (4 vCPU, 12 GiB).
  - The pricing page makes no cold-start claim.
  — [pricing](https://developers.cloudflare.com/containers/pricing/)

**Docker + Dev Containers (local and CI, free)**
- `devcontainers/cli`: 2,985 stars, MIT, last push 2026-10-08, TypeScript. npm `@devcontainers/cli` 0.89.0.
  - Implemented: `devcontainer build`, `up`, `run-user-commands`, `read-configuration` and `exec`. Not yet implemented: `devcontainer stop` and `devcontainer down`.
  - The install script bundles Node and covers Linux and macOS only. `npm install -g` needs Python and a C/C++ toolchain.
  — [GitHub](https://github.com/devcontainers/cli)
- `devcontainers/spec`: 5,767 stars, CC-BY-4.0, last push 2026-03-20 — [GitHub](https://github.com/devcontainers/spec)
- Docker Desktop is free for "Small businesses (fewer than 250 employees AND less than $10 million in" annual revenue) — [Docker docs](https://docs.docker.com/subscription/desktop-license/)
- GitHub Actions: "If your workflows use Docker container actions, job containers, or service containers, then you must use a Linux runner". On GitHub-hosted runners that means Ubuntu — [GitHub docs](https://docs.github.com/en/actions/tutorials/use-containerized-services/use-docker-service-containers)
- `docker/docker-py`: 7,217 stars, Apache-2.0, last push 2026-10-14. PyPI `docker` 7.2.0 (2026-07-09) — [GitHub](https://github.com/docker/docker-py)

**Coder; Gitpod/Ona (cloud dev-environment platforms)**
- `coder/coder`: 17,011 stars, AGPL-3.0, last push 2026-10-14, "Secure environments for developers and their agents" — [GitHub](https://github.com/coder/coder)
- `gitpod-io/gitpod`: 13,800 stars, AGPL-3.0, last push 2026-10-14 — [GitHub](https://github.com/gitpod-io/gitpod)
- Gitpod rebranded as Ona on 2025-09-02 and pivoted to a software-engineering-agent platform — [The Register](https://www.theregister.com/2025/09/03/gitpod_rebrands_as_ona/)
- Gitpod Classic pay-as-you-go was sunset on 2025-10-15 (Enterprise excluded). Configuration moved from `.gitpod.yml` to `devcontainer.json` plus `automations.yml` — [Ona post (mirror)](https://www.plushcap.com/content/ona/blog/ona-gitpod-classic-payg-sunset-on-october-15th). A third-party review gives a September date instead, so the sources conflict ([aicoolies](https://aicoolies.com/reviews/gitpod-review)).

**Anthropic sandbox-runtime (`srt`)**
- `anthropics/sandbox-runtime` (moved from `anthropic-experimental`): 5,542 stars, Apache-2.0, last push 2026-10-14, TypeScript. npm `@anthropic-ai/sandbox-runtime` — [GitHub](https://github.com/anthropics/sandbox-runtime)
- How it works:
  - It enforces filesystem and network limits on a whole process tree "without requiring a container".
  - macOS uses `sandbox-exec` Seatbelt profiles. Linux uses bubblewrap and removes the network namespace. Windows runs the process as a dedicated `srt-sandbox` local user, with a Windows Filtering Platform egress fence and per-session ACEs.
  - Network is allow-only through host HTTP and SOCKS5 proxies. Writes are denied by default.
  - "Beta Research Preview".
  — [README](https://github.com/anthropics/sandbox-runtime)

**Codex local sandboxing**
- `openai/codex`: 129,198 stars, Apache-2.0, last push 2026-10-14, Rust — [GitHub](https://github.com/openai/codex)
- Linux: the `codex-linux-sandbox` helper "uses bubblewrap for filesystem and namespace isolation, and seccomp for syscall filtering" and keeps a legacy Landlock implementation — [README](https://github.com/openai/codex/blob/main/codex-rs/linux-sandbox/README.md)
- Windows: the native MXC sandbox routes into Microsoft's MXC `BaseContainerRunner`. The child is created suspended and assigned a "kill-on-close job". Loopback is allowed and direct non-loopback egress is denied. The older Windows sandboxes remain separate backends — [README](https://github.com/openai/codex/blob/main/codex-rs/mxc-sandbox/README.md)

**Other primitives and patterns**
- `dagger/container-use`: 4,069 stars, Apache-2.0, last push 2026-09-21, "Development environments for coding agents. Enable multiple agents to work safely and independently with your preferred stack." — [GitHub](https://github.com/dagger/container-use)
- `firecracker-microvm/firecracker` has 37,369 stars and `google/gvisor` has 19,674. Both are Apache-2.0 and both were pushed 2026-10-14 — [Firecracker](https://github.com/firecracker-microvm/firecracker); [gVisor](https://github.com/google/gvisor)
- Stripe Minions (stripe.dev, 2026-02-09, Alistair Gray):
  - Devboxes are "pre-warmed so one can be spun up in 10 seconds" and are cut off from production and the internet.
  - Engineers run agents in parallel without git worktrees, which the author says "wouldn't scale at Stripe".
  - Lints run on each push in "less than five seconds", and agents get "at most two" CI runs.
  — [stripe.dev](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)

### Inferences
- Verdicts:
  | Candidate | Verdict | Why (for Contexer) |
  |---|---|---|
  | Host processes + git worktree (no sandbox) | BUILD ON (default) | Free everywhere, including Windows and macOS CI runners. The coding agent already ran on the same host, so a sandbox adds little security for the user's own repo. |
  | E2B | BUILD ON (optional hosted backend) | Python SDK; `get_host(port)` public URLs; background commands with log streaming; start/ready templates that pre-boot the dev server; pause/resume; Apache-2.0 runtime self-hostable on one Linux box. Cost per check run is cents. |
  | Docker + devcontainers CLI | BUILD ON (optional `--isolate docker` mode) | Uses the repo's own `devcontainer.json` if present, and is free for the target users. Downsides: Node-based CLI, no `stop`/`down` (use `docker` directly), and GitHub-hosted CI needs Linux runners. |
  | microsandbox | BORROW IDEAS (watch) | The only local microVM option that supports Windows (WHP) and has a Python SDK, but it is beta. Revisit as a local isolation backend once it reaches 1.0. |
  | Modal Sandboxes | BORROW IDEAS (possible 2nd hosted backend) | Ramp's cron-built snapshot pattern is the key idea. The Python-native SDK is good, but sandbox CPU costs about 3x Functions and port exposure needs tunnels. |
  | Vercel Sandbox | BORROW IDEAS (optional later) | Python SDK and a generous Hobby tier, but 45-minute Hobby sessions and Vercel account/OIDC auth tie it to Vercel users. Natural fit only for Vercel-hosted teams. |
  | Daytona | AVOID (for now) | Core moved to a private codebase in June 2026 and the OSS repo is archived. The SDK is still alive, but platform-direction risk is high for a small team. |
  | Cloudflare Containers / Sandbox SDK | AVOID | TypeScript Worker-only control plane, no Python SDK, a paid plan and a wildcard custom domain for previews. |
  | Coder, Gitpod/Ona | AVOID | Full CDE/agent platforms (AGPL or commercial) and overlapping products, not primitives. |
  | Anthropic `srt` | BORROW IDEAS (optional hardening) | Could wrap the dev server to block egress except allowlisted Supabase/Stripe hosts. It is beta and Node-based, and its network proxying may break dev-server HMR websockets (untested). |
  | Codex sandbox | BORROW IDEAS | The Windows kill-on-close job-object pattern is directly reusable for process cleanup (Q3). It is not usable as a library. |
  | dagger/container-use | BORROW IDEAS | Container plus git branch per agent matches Contexer's per-attempt model. Not researched in depth. |
  | Firecracker / gVisor | AVOID | Building a fleet is explicitly out of scope. |
- Free locally and in CI: host processes; Docker + devcontainers (Linux runners only on GitHub-hosted CI; Windows and macOS hosted runners cannot run service containers); `srt`; microsandbox (needs KVM/WHP/Apple Silicon); self-hosted E2B Embed (Linux only). Hosted options with free tiers: E2B ($100 one-time), Daytona ($200 credit), Modal ($30/month recurring), Vercel Sandbox Hobby (5 CPU-hours/month, 45-minute sessions). Cloudflare requires the $5/month Workers Paid plan.
- Hosted sandboxes serve the app on a non-localhost hostname, such as `3000-<id>.e2b.app`. Vite rejects unknown hosts by default (see Q3), and Supabase Auth redirect URLs must allow that host. Contexer must either run Playwright inside the sandbox against `localhost`, or set the right `--host` / `allowedHosts` and auth redirect configuration. Running the browser checks inside the sandbox (as Ramp does) avoids both problems and keeps logs local to the sandbox.
- The Ramp and Stripe lesson for a small team is pre-baked environments, not fleets. Contexer can get most of the benefit by caching dependency installs keyed by lockfile hash. With E2B, it can also build a per-repo template whose start command already runs `npm ci` (and possibly the dev server) and use `wait_for_url` as the ready command.

### Gaps
- No official startup-latency figure was found for E2B or Modal sandboxes this session. Daytona (<90 ms), microsandbox (<100 ms) and Vercel ("milliseconds") are vendor claims, and none were measured. Stripe's 10 s devbox figure comes from a pre-warmed pool.
- Whether GitHub-hosted Linux runners expose `/dev/kvm` for microsandbox was not checked.
- The archived Daytona repo's license (historically AGPL-3.0, from memory) was not verified because the GitHub API returns no SPDX id.
- Ona's current pricing and unit rates were not found in primary sources.
- Cloudflare Sandbox SDK GA/beta status is not stated on its overview page.

## Q2. Detecting how to start an arbitrary web app: how do Vercel, Netlify, Railpack/Nixpacks, Buildpacks, ni, devcontainer.json and Procfile choose the dev command and port?

### Takeaway
The best open data source is Vercel's `@vercel/frameworks`. It has 75 framework entries, each with `detectors` (package.json dependency or file-content matches) and a `devCommand` that usually injects `--port $PORT`. Netlify's `@netlify/build-info` adds a default dev port, a TCP readiness strategy and an accuracy ranking per framework, plus a ranked choice among `package.json` scripts. Railpack and Buildpacks target production images (`start`, Caddy for SPAs) rather than dev servers, and Nixpacks is in maintenance mode. Contexer should port the Vercel and Netlify rules into a small Python table and let explicit config win (Contexer config > devcontainer.json > Procfile > detection). It must handle two Lovable shapes: the classic Vite SPA, and TanStack Start SSR projects created since 2026-05-13.

### Cited Findings

**Vercel `@vercel/frameworks` + `@vercel/fs-detectors`**
- `vercel/vercel` monorepo: 16,394 stars, Apache-2.0, last push 2026-10-14. Its packages include `frameworks`, `fs-detectors` and `static-build`. npm `@vercel/frameworks` 3.35.0 and `@vercel/fs-detectors` 7.9.7 are both Apache-2.0 — [GitHub](https://github.com/vercel/vercel); [npm frameworks](https://www.npmjs.com/package/@vercel/frameworks)
- `packages/frameworks/src/frameworks.ts` has 4,878 lines and 75 `slug:` entries. Detectors are `matchPackage` (a package.json dependency) or `matchContent` (a regex over a file path's contents), combined with `every` and `some` — [frameworks.ts](https://github.com/vercel/vercel/blob/main/packages/frameworks/src/frameworks.ts)
- `devCommand` values in that file (2026-10-14):
  - nextjs `next dev --port $PORT`; vite `vite --port $PORT`; astro `astro dev --port $PORT`; sveltekit-1 `vite dev --port $PORT`; gatsby `gatsby develop --port $PORT`; angular `ng serve --port $PORT`; vue `vue-cli-service serve --port $PORT`; docusaurus-2 `docusaurus start --port $PORT`; storybook `storybook dev -p $PORT`.
  - Some entries have no port flag: create-react-app `react-scripts start`, remix `remix dev`, react-router `react-router dev`, nuxtjs `nuxt dev`, solidstart `solid-start dev`, parcel `parcel`.
  - Backend presets (express, hono, fastapi, flask, django, node, python) have `devCommand: null`.
  — [frameworks.ts](https://github.com/vercel/vercel/blob/main/packages/frameworks/src/frameworks.ts)
- There is a Lovable-specific entry, `tanstack-start-lovable` (platform "lovable"). It is detected when `@lovable.dev/vite-tanstack-config` is present together with either `@tanstack/react-start` or `@tanstack/solid-start`. It supersedes `tanstack-start`, `ionic-react` and `vite`, and its devCommand is `vite --port $PORT` — [frameworks.ts](https://github.com/vercel/vercel/blob/main/packages/frameworks/src/frameworks.ts)
- `fs-detectors/src` contains `detect-framework.ts`, `detect-builders.ts`, `monorepos/`, `package-managers/`, `workspaces/` and `services/` — [GitHub](https://github.com/vercel/vercel/tree/main/packages/fs-detectors/src)

**Netlify `@netlify/build-info` (successor of framework-info)**
- `netlify/framework-info` is **archived** (last push 2023-01-10; npm 10.0.5). Detection lives in `netlify/build` (260 stars, MIT, last push 2026-10-13) as npm `@netlify/build-info` 11.3.0 — [framework-info](https://github.com/netlify/framework-info); [netlify/build](https://github.com/netlify/build)
- About 60 framework classes, including vite, next, tanstack-start, tanstack-router, react-router, remix, astro, nuxt, svelte-kit, vike, waku, hono, mastra and expo — [frameworks dir](https://github.com/netlify/build/tree/main/packages/build-info/src/frameworks)
- Each framework declares `dev = { command, port, pollingStrategies }`:
  - Vite: `vite`, port 5173, TCP polling. It is excluded when Remix, SvelteKit, TanStack Router/Start, Solid, Qwik, React Router or Vike packages are present. With `vite-plus` it switches to `vp dev`.
  - Next: `next`, port 3000, TCP polling.
  — [vite.ts](https://github.com/netlify/build/blob/main/packages/build-info/src/frameworks/vite.ts); [next.ts](https://github.com/netlify/build/blob/main/packages/build-info/src/frameworks/next.ts)
- Detection accuracy is ranked: Forced=5, NPM=4, ConfigOnly=3, Config=2, NPMHoisted=1 — [framework.ts](https://github.com/netlify/build/blob/main/packages/build-info/src/frameworks/framework.ts)
- Script choice: scripts whose value contains the framework's dev command are preferred. Otherwise scripts named `dev`, `serve`, `develop`, `start`, `run` or `web` (also `x:dev`-style names) are ranked in that order. Scripts containing `netlify dev` are excluded — [get-commands.ts](https://github.com/netlify/build/blob/main/packages/build-info/src/get-commands.ts)

**Railpack and Nixpacks (Railway)**
- `railwayapp/railpack`: 1,231 stars, MIT, last push 2026-10-14, Go. v0.41.0 (2026-10-13) ships Windows x86_64 and arm64 binaries. Building images requires a BuildKit container — [GitHub](https://github.com/railwayapp/railpack); [release](https://github.com/railwayapp/railpack/releases/tag/v0.41.0)
- The CLI has `build`, `plan`, `prepare` and `info`. `info` will "get as much information as possible about an app", with `--format json` and `--show-plan`. Providers: node, python, staticfile, procfile, shell, golang, php, ruby, rust, java, deno, dotnet, elixir, gleam and cpp — [cli/info.go](https://github.com/railwayapp/railpack/blob/main/cli/info.go); [providers](https://github.com/railwayapp/railpack/tree/main/core/providers)
- Node rules:
  - Package manager: the `packageManager` field, then mise, then lockfiles (`pnpm-lock.yaml`, `bun.lock(b)`, `.yarnrc.yml`, `yarn.lock`), then `engines`, then npm.
  - Start command: `scripts.start`, then `main`, then root `index.js` or `index.ts`.
  - Vite is detected via `vite.config.*` or `vite build` in the build script. Static SPA output is served by Caddy.
  - Next.js counts as static only with `output: 'export'`.
  - The page does not describe PORT handling.
  — [railpack.com/languages/node](https://railpack.com/languages/node)
- `railwayapp/nixpacks`: 3,555 stars, MIT, last push 2026-10-02. "**Maintenance Mode:** ... We recommend using Railpack as a replacement." — [GitHub](https://github.com/railwayapp/nixpacks)

**Cloud Native Buildpacks and similar**
- `buildpacks/pack`: 3,013 stars, Apache-2.0, last push 2026-10-14. `paketo-buildpacks/nodejs`: 65 stars, Apache-2.0 — [pack](https://github.com/buildpacks/pack); [paketo nodejs](https://github.com/paketo-buildpacks/nodejs)
- `zeabur/zbpack`: 327 stars, MPL-2.0, last push 2026-08-26, "Build your project into static assets, serverless function or container image" — [GitHub](https://github.com/zeabur/zbpack)

**Package-manager detection (antfu)**
- `antfu-collective/ni`: 8,312 stars, MIT, last push 2026-10-09. npm `@antfu/ni` 30.6.0. It supports npm, yarn, pnpm, bun, deno, nub and aube, with `defaultAgent` as the fallback "when no lock found" — [GitHub](https://github.com/antfu-collective/ni)
- `antfu-collective/package-manager-detector`: 171 stars, MIT, last push 2026-10-05. Order: lockfiles, then `packageManager` field, then `devEngines.packageManager`, then walk up to parent directories — [GitHub](https://github.com/antfu-collective/package-manager-detector)
- In Windows PowerShell 5.1 on the dev machine, `ni` is a built-in alias for `New-Item` (`Get-Alias ni` → `New-Item`), so a bare `ni` binary is shadowed there — local check, 2026-10-14.

**Procfile and devcontainer.json as explicit start declarations**
- `nickstenning/honcho` (Python Foreman clone for Procfile apps): 1,716 stars, MIT, last push 2025-06-03. PyPI 2.0.0 (2024-10-06). `ddollar/foreman`: 6,163 stars, MIT — [honcho](https://github.com/nickstenning/honcho); [foreman](https://github.com/ddollar/foreman)
- `devcontainer.json` declares `forwardPorts`, `portsAttributes`, `postStartCommand` ("each time the container is successfully started") and Compose `runServices` — [containers.dev](https://containers.dev/implementors/json_reference/)

**Lovable / Bolt exports (target-user specifics)**
- Lovable: "Starting May 13, new projects are Server-Side Rendered (SSR) and powered by TanStack Start". The runtime is Cloudflare Workers (edge Worker deploys). "Existing projects keep working as before" (post dated 2026-06-01) — [Lovable blog](https://lovable.dev/blog/building-apps-using-tanstack-start)
- Vercel says Lovable projects use TanStack Start with Nitro. Zero-config detection "requires `@lovable.dev/vite-tanstack-config` version `^2.6.2` or higher" — [Vercel docs](https://vercel.com/docs/integrations/lovable) (updated 2026-07-10)
- Third-party sources:
  - Classic Lovable projects show `lovable-tagger` and a plain Vite + React setup. New ones need a server build; static hosts may show a blank page — [snapdeploy](https://snapdeploy.dev/blog/deploy-lovable-app-own-hosting-2026)
  - Lovable exports don't include secrets — [BrainGrid](https://www.braingrid.ai/blog/how-to-download-lovable-project)
  - A Lovable Vite config example uses `port: Number(process.env.PORT) || 8080` — [Scalingo](https://doc.scalingo.com/tutorials/lovable)
- Bolt (third-party sources only): ZIP or GitHub export, `npm run dev`, and secrets are not exported — [Rapid Developers](https://www.rapidevelopers.com/md/bolt-ai-integrations/visual-studio-code). No official Bolt documentation was found.

### Inferences
- Verdicts:
  | Candidate | Verdict | Why |
  |---|---|---|
  | `@vercel/frameworks` data | BORROW IDEAS (vendor a curated subset as JSON, with Apache-2.0 attribution) | Best coverage, including the Lovable entry, and the `$PORT` convention lets Contexer assign the port. Calling Node packages from Python adds an npm install, so port the data instead. |
  | `@netlify/build-info` | BORROW IDEAS | Default ports, TCP polling, the accuracy ranking, the script ranking, and exclusion lists (Vite vs meta-frameworks) are exactly the tie-break logic Contexer needs. |
  | Railpack | BORROW IDEAS (optional fallback: `railpack info --format json`) | Good package-manager and start rules and ships Windows binaries, but it is production-oriented (start command, Caddy) and builds need BuildKit. Whether `info` runs without BuildKit was not verified. |
  | Nixpacks | AVOID | Maintenance mode. |
  | Cloud Native Buildpacks / zbpack | AVOID | Production image builders; slow and heavy for repeated dev-server restarts. |
  | ni / package-manager-detector | BORROW IDEAS (reimplement in Python) | The logic is about 30 lines (lockfile → `packageManager` → `devEngines` → walk up). Don't shell out to `ni`, because of the PowerShell alias clash and the extra Node dependency. |
  | devcontainer.json / Procfile | BUILD ON (as explicit overrides) | Both are already the declared intent in many repos. Honcho shows Procfile parsing is trivial. |
- Suggested resolution order: Contexer config (`contexer.toml`/CLI flags) > `devcontainer.json` (`postStartCommand` + `forwardPorts`) > Procfile `web:` > framework detection (Vercel-style detector table plus Netlify-style script ranking) > static-site fallback (serve `index.html` or the build output with Contexer's own static server).
- Port control: use the framework flag where known (`--port $PORT` for Vite, Next, Astro and the TanStack/Lovable Vite entry), and also set `PORT`, because Next reads it (Q3). Add `--strictPort` for Vite so a taken port fails loudly instead of silently moving (Q3). For entries without a port flag (CRA uses `PORT`; Nuxt and Remix have their own conventions), parse the URL the server prints. Playwright's `wait.stdout` regex with named groups is a good model (Q3).
- Lovable split:
  - Classic Vite SPA: `vite`, port fallback often 8080, needs `VITE_SUPABASE_*` env.
  - TanStack Start SSR (since 2026-05-13): `@lovable.dev/vite-tanstack-config`, dev via `vite`. A production build targets Cloudflare Workers or Nitro and may break on static hosting.
  - Contexer should test via the dev server for both and detect missing env and secrets up front, because exports omit them.

### Gaps
- `@vercel/fs-detectors` monorepo and workspace selection logic was not read in detail.
- The full Railpack CLI output schema and PORT behaviour were not checked.
- No official Bolt docs were found on export structure or the "Bolt Database" backend, so Bolt specifics rest on third-party tutorials.
- No dataset was found on what share of Lovable/Bolt exports run with `npm install && npm run dev` unmodified.

## Q3. Process lifecycle: readiness checks, free ports, port flags, killing process trees on Windows vs POSIX, log capture, and existing "start, wait, tear down" libraries

### Takeaway
Playwright Test's `webServer` is the reference design. It spawns the server in its own process group (POSIX `detached`), polls `127.0.0.1` and `::1` with backoff, and treats 2xx, 3xx and 400–403 responses as ready. It can also wait for a stdout regex, and kills with `kill(-pid)` on POSIX and `taskkill /pid N /T /F` on Windows. It is Node-only, so Contexer should reimplement the same contract in Python on `subprocess` + `psutil`. On Windows, add a kill-on-close Job Object, which is what Codex's MXC sandbox does. Mirakuru lacks Windows support, and start-server-and-test / wait-on are Node CLIs that don't fit a Python orchestrator.

### Cited Findings

**Playwright Test `webServer` (Node test runner)**
- Options and defaults:
  - `command`, `cwd` (defaults to the config file's directory), and `env` (inherits `process.env` plus `PLAYWRIGHT_TEST=1`).
  - `url` is ready when it returns "a 2xx, 3xx, 400, 401, 402, or 403". `port` is deprecated.
  - `reuseExistingServer`, `timeout` ("Defaults to 60000"), `stdout` (default `"ignore"`), `stderr` (default `"pipe"`).
  - `wait` takes `stdout`/`stderr` regexes. "Named capture groups in the regex are stored in the environment", e.g. `(?<my_server_port>\d+)` becomes `MY_SERVER_PORT`.
  - `gracefulShutdown: {signal: 'SIGTERM'|'SIGINT', timeout}`. Unset means SIGKILL to the process group. "Windows doesn't support `SIGTERM` and `SIGINT` signals, so this option is ignored on Windows."
  — [playwright.dev](https://playwright.dev/docs/test-webserver)
- Implementation:
  - POSIX spawns with `detached: true` so the child leads a new process group, and kills with `process.kill(-pid, 'SIGKILL')`.
  - Windows runs `taskkill /pid ${pid} /T /F` with `windowsHide: true`.
  — [processLauncher.ts](https://github.com/microsoft/playwright/blob/main/packages/utils/processLauncher.ts)
- Readiness checks both `127.0.0.1` and `::1` for port probes and backs off 100, 250, 500, then 1000 ms — [webServerPlugin.ts](https://github.com/microsoft/playwright/blob/main/packages/playwright/src/plugins/webServerPlugin.ts)
- `microsoft/playwright`: 97,700 stars, Apache-2.0. `microsoft/playwright-python`: 15,041 stars, Apache-2.0, last push 2026-10-13. PyPI `playwright` 1.64.0 (2026-10-13), Python >=3.10 — [GitHub](https://github.com/microsoft/playwright-python); [PyPI](https://pypi.org/project/playwright/)

**start-server-and-test, wait-on, tree-kill, concurrently, get-port (Node)**
- `bahmutov/start-server-and-test`: 1,584 stars, MIT, last push 2026-10-12. npm 3.0.13.
  - Uses `wait-on` under the hood.
  - Default expected status is 200 (`--expect` overrides it).
  - Default timeout is 5 minutes (`WAIT_ON_TIMEOUT`) and default interval 2 s (`WAIT_ON_INTERVAL`).
  - Stops the server with tree-kill.
  - Uses `http-get://` when servers reject HEAD.
  — [README](https://github.com/bahmutov/start-server-and-test)
- `jeffbski/wait-on`: 1,984 stars, MIT, last push 2026-09-30. npm 9.5.1.
  - Waits on `http:` (HEAD, 2XX), `http-get:`, `tcp:`, `socket:` and `file:`.
  - `--status-codes 200-499` widens the accepted range.
  - "Cross-platform - runs everywhere Node.js runs (linux, unix, mac OS X, windows)".
  — [README](https://github.com/jeffbski/wait-on)
- `pkrumins/node-tree-kill`: 359 stars, last push 2020-06-17. `open-cli-tools/concurrently`: 7,859 stars. `sindresorhus/get-port`: 929 stars — [tree-kill](https://github.com/pkrumins/node-tree-kill); [concurrently](https://github.com/open-cli-tools/concurrently); [get-port](https://github.com/sindresorhus/get-port)

**Python options**
- `giampaolo/psutil`: 11,292 stars, BSD-3-Clause, last push 2026-10-13. PyPI 7.2.2 (2026-01-28). Platforms: Linux, Windows, macOS, FreeBSD, OpenBSD, NetBSD, Solaris and AIX. The docs recipe `kill_proc_tree(pid, sig=signal.SIGTERM, include_parent=True, timeout=None, on_terminate=None)` uses `parent.children(recursive=True)` and then waits — [GitHub](https://github.com/giampaolo/psutil); [psutil.io](https://psutil.io/); [recipes](https://psutil.io/recipes/)
- `dbfixtures/mirakuru` (formerly ClearcodeHQ): 91 stars, LGPL-3.0, last push 2026-10-12. PyPI 3.0.4. Executors: Simple, Output, TCP, UnixSocket, HTTP and Pid. "Windows support: Frankly, there's none" — [README](https://github.com/dbfixtures/mirakuru)
- `pytest-dev/pytest-xprocess`: 108 stars, MIT, a pytest plugin for external processes — [GitHub](https://github.com/pytest-dev/pytest-xprocess)
- `fizyk/port-for` (formerly kmike): 32 stars, MIT, PyPI 1.1.1 (2026-10-05). `google/python_portpicker` is archived (last push 2023-08-15) — [port-for](https://github.com/fizyk/port-for); [portpicker](https://github.com/google/python_portpicker)
- Python stdlib:
  - POSIX: "If start_new_session is true the setsid() system call will be made in the child process".
  - Windows: "CTRL_BREAK_EVENT can be sent to processes started with a creationflags parameter which includes CREATE_NEW_PROCESS_GROUP."
  — [docs.python.org](https://docs.python.org/3/library/subprocess.html)
- Windows Job Objects: `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (0x2000) "Causes all processes associated with the job to terminate when the last handle to the job is closed." — [Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information). Codex's Windows MXC path assigns a kill-on-close job before resuming the child — [codex mxc README](https://github.com/openai/codex/blob/main/codex-rs/mxc-sandbox/README.md)

**Framework port and host behaviour**
- Vite:
  - `server.port` defaults to 5173. "if the port is already being used, Vite will automatically try the next available port". `server.strictPort` makes it exit instead.
  - `server.host` defaults to `'localhost'`. Node's DNS result ordering means "browsers may use a different resolved address than the one Vite is listening to".
  - `server.allowedHosts`: only "`localhost` and domains under `.localhost` and all IP addresses are allowed by default". `__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS` adds hosts.
  — [Vite docs](https://github.com/vitejs/vite/blob/main/docs/config/server-options.md)
- Next.js `next dev`: "`-p` or `--port <port>` ... Default: 3000, env: PORT". `-H/--hostname` defaults to 0.0.0.0. Turbopack is the default bundler — [Next.js CLI docs](https://github.com/vercel/next.js/blob/canary/docs/01-app/03-api-reference/06-cli/next.mdx)
- Netlify's dev metadata pairs each framework with a default port (Vite 5173, Next 3000) and a TCP polling strategy — [vite.ts](https://github.com/netlify/build/blob/main/packages/build-info/src/frameworks/vite.ts)

### Inferences
- Verdicts:
  | Candidate | Verdict | Why |
  |---|---|---|
  | Playwright Test `webServer` | BORROW IDEAS | Copy its contract: ready on 2xx/3xx/400–403, dual-stack probe, backoff, stdout-regex readiness with captured port, process-group kill, `taskkill /T /F` on Windows. It can't be used from Python, and pytest-playwright has no equivalent (inference). |
  | psutil | BUILD ON | Cross-platform tree enumeration and kill, `wait_procs`, and port-to-PID lookup for diagnosing "port already in use". |
  | stdlib `subprocess` (+ `start_new_session` / `CREATE_NEW_PROCESS_GROUP`) | BUILD ON | Process-group spawn on POSIX; new process group plus CTRL_BREAK for a graceful stop attempt on Windows. |
  | Windows Job Object (kill-on-close via `pywin32` or `ctypes`) | BUILD ON | The only reliable way to guarantee `npm run dev` → `cmd.exe` → `node` → esbuild grandchildren die even if Contexer crashes. `taskkill /T` alone misses re-parented orphans. |
  | start-server-and-test / wait-on / concurrently | AVOID (as dependencies) | Node CLIs that hide the PID tree and logs from Python. Their readiness semantics (HEAD vs GET, status ranges) are worth copying. |
  | mirakuru | AVOID | No Windows support. Its executor taxonomy (TCP / HTTP / Output / Pid) is a useful design reference. |
  | pytest-xprocess, port-for | AVOID / optional | `socket.bind(('127.0.0.1', 0))` is enough to pick a free port. port-for adds little. |
- Recommended Contexer `AppServer` contract:
  1. Pick a free port by binding to port 0.
  2. Start with the framework port flag and `PORT=<n>`, plus `--strictPort` for Vite. Use `--host 127.0.0.1` unless the app is accessed remotely.
  3. Spawn in a new session/process group, and on Windows inside a kill-on-close Job Object.
  4. Tee stdout and stderr into a timestamped per-attempt log file as evidence, and keep a ring buffer for the repair prompt.
  5. Treat the server as ready when the first of these happens: an HTTP probe on 127.0.0.1 and ::1 returns 2xx/3xx/400–403, or a stdout regex such as `Local:\s+(http://\S+)` or `ready in` matches. Fail fast when the process exits early or an error regex (`EADDRINUSE`, `Cannot find module`) matches.
  6. Stop with a graceful signal (SIGTERM on POSIX, CTRL_BREAK on Windows), then after a timeout use `psutil` tree kill or close the Job Object. Finally verify the port is free before the next attempt.
- Dev-server ready does not mean the app is ready. Vite and Next compile routes lazily, so the first browser navigation can be slow or show a compile overlay. A warm-up GET of `/` (and key routes) before running checks reduces flakiness.

### Gaps
- No measured cold-start times for `vite` vs `next dev` (Turbopack) on Windows vs Linux were found. Contexer should measure them itself.
- How often `taskkill /T` leaves orphans for npm/pnpm shims on Windows was not quantified. The recommendation for Job Objects is based on the Windows API semantics and Codex's design, not measurements.
- No maintained Python library was found that already packages "spawn, wait, tree-kill, Windows Job Object".

## Q4. Local backend services and test data: Supabase local, Firebase emulators, Stripe CLI, MSW, Testcontainers, WireMock, seeded accounts and Playwright storageState

### Takeaway
Supabase CLI is the key dependency for Lovable/Bolt-style apps. `supabase start` (Docker) gives a full local stack on fixed ports 54321–54324, with seeds from `supabase/seed.sql` applied by `supabase db reset`. Since CLI v2.119.0 the experimental `stack` mode isolates one local Supabase per git worktree on auto-assigned ports. A new experimental `--runtime native` runs the stack without Docker on Linux and macOS but not Windows. Create test users through the Auth Admin API with `email_confirm: true`, then reuse Playwright `storage_state`. Use Stripe CLI `listen --forward-to` with `--print-secret` and `stripe trigger` against a Stripe sandbox. `stripe sandbox create` now provisions an anonymous 7-day sandbox with keys and no signup. Prefer Playwright `route` mocking over MSW, WireMock or stripe-mock for third-party APIs.

### Cited Findings

**Supabase local development**
- `supabase/cli`: 2,436 stars, last push 2026-10-14, now TypeScript. The GitHub API reports no license and the repo root has no LICENSE file as of 2026-10-14. Latest release v2.120.0 (2026-10-06) includes Windows amd64/arm64 zips — [GitHub](https://github.com/supabase/cli); [release](https://github.com/supabase/cli/releases/tag/v2.120.0). `supabase/supabase`: 111,533 stars, Apache-2.0 — [GitHub](https://github.com/supabase/supabase)
- Install and requirements:
  - Windows: Scoop (`scoop install supabase`). Any OS: `npx supabase` with Node 20+.
  - Needs a Docker-compatible runtime (Docker Desktop, OrbStack, Rancher Desktop, Podman, colima).
  - "The first run takes time while the CLI downloads the Docker images."
  - Local endpoints: API `http://localhost:54321`, Postgres `54322`, Studio `54323`, Mailpit `54324`.
  - `supabase stop --no-backup` deletes local data.
  — [Supabase getting started](https://supabase.com/docs/guides/local-development/cli/getting-started)
- `supabase start` flags:
  - `-x/--exclude` takes container names (gotrue, realtime, storage-api, imgproxy, kong, mailpit, postgrest, postgres-meta, studio, edge-runtime, logflare, vector, supavisor). `--ignore-health-check` is available.
  - The docs recommend "at least 7GB of RAM to start all services".
  - `supabase status -o env|json|...` exports JWT_SECRET, ANON_KEY and SERVICE_ROLE_KEY.
  — [CLI reference](https://supabase.com/docs/reference/cli/supabase-start)
- Native runtime (experimental):
  - Started with `supabase start --runtime native` once `[experimental] stack` is on. "The default `supabase start` command always uses Docker."
  - Platforms: Linux amd64/arm64 with glibc ≥2.35, and macOS 14+ on Apple silicon. **Windows: "Not supported. Use Docker."**
  - Cannot run as root unless `SUPABASE_NATIVE_POSTGRES_USER` is set. Downloads archives from `supabase/slim-services` releases; `supabase stack prepare --runtime native` pre-bakes them into images.
  - Postgres starts at once; other services start on first request and idle-stop after 60 s (`--eager` disables this).
  - Runtime auto-selection: Docker, then Podman, then native. Each check waits up to 10 s.
  — [Docker and native runtimes](https://supabase.com/docs/guides/local-development/docker-and-native-runtimes); described as "public alpha" for coding-agent sandboxes and CI in [Supabase feature page](https://supabase.com/features/native-local-runtime)
- Multiple local projects (CLI ≥ v2.119.0, experimental):
  - Enabled with `[experimental] stack = true` or `SUPABASE_EXPERIMENTAL_STACK=1`.
  - A project's identity is its root, the current git branch and an optional `--stack` name. You get "a separate local project for each ... Git worktree".
  - Ports are auto-assigned from 20000–32767 and stay stable across restarts, but only if fixed ports are removed from `config.toml`.
  — [Running multiple local projects](https://supabase.com/docs/guides/local-development/running-multiple-local-projects)
- Seeding:
  - Default file is `supabase/seed.sql`, or `[db.seed] sql_paths` (globs allowed, sorted).
  - Seeds run "the first time you run `supabase start`" and "every time you run `supabase db reset`", after migrations.
  - `@snaplet/seed` is now community-maintained with occasional fixes.
  — [Seeding docs](https://supabase.com/docs/guides/local-development/seeding-your-database); [supabase-community/seed](https://github.com/supabase-community/seed) (788 stars, MIT, last push 2026-10-01)
- Test users:
  - JS: `supabase.auth.admin.createUser({ email, password, email_confirm: true })` with the service-role key, server-side only — [JS reference](https://supabase.com/docs/reference/javascript/auth-api-createuser)
  - Python equivalent: `auth.admin.create_user` — [Python reference](https://supabase.com/docs/reference/python/auth-admin-createuser). PyPI `supabase` 2.32.0 (2026-10-02).
  - Community threads report that raw `auth.users` inserts in seed.sql are fragile — [discussion #9251](https://github.com/orgs/supabase/discussions/9251)

**Firebase Emulator Suite**
- `firebase/firebase-tools`: 4,472 stars, MIT, last push 2026-10-14 — [GitHub](https://github.com/firebase/firebase-tools)
- Requirements: the page states Node 16.0+ and JDK 11+ (possibly stale) and CLI 8.14.0+.
- Default ports: Auth 9099, Firestore 8080, RTDB 9000, Storage 9199, Functions 5001, Hosting 5000, UI 4000.
- Commands: `emulators:exec <script>` stops the emulators when the script finishes. `--import` / `--export-on-exit` load and save seed data.
- CI: JARs are cached at `~/.cache/firebase/emulators/`.
— [Firebase docs](https://firebase.google.com/docs/emulator-suite/install_and_configure)

**Stripe test mode / sandboxes**
- `stripe/stripe-cli`: 2,203 stars, Apache-2.0, last push 2026-10-14. v1.53.1 (2026-10-07) ships Windows x86_64/i386 zips — [GitHub](https://github.com/stripe/stripe-cli)
- Local webhooks: `stripe listen --forward-to localhost:4242/webhook` prints the `whsec_...` signing secret, and `stripe trigger payment_intent.succeeded` fires a test event. "We retry event deliveries created in a sandbox three times over the course of a few hours." — [Stripe webhooks docs](https://docs.stripe.com/webhooks)
- `listen` flags include `--print-secret` ("Only print the webhook signing secret and exit"), `--events`, `--forward-to`, `--skip-verify` and `--format`. The global `--api-key` flag (or `STRIPE_API_KEY`) replaces a logged-in session — [listen.go](https://github.com/stripe/stripe-cli/blob/master/pkg/cmd/listen.go); [root.go](https://github.com/stripe/stripe-cli/blob/master/pkg/cmd/root.go)
- Sandboxes: "Use separate sandboxes for local development and continuous integration (CI)". "Coding agents should ... run the command `stripe sandbox create --help` to provision an anonymous Stripe sandbox with working API keys. No account registration required." — [Stripe sandboxes](https://docs.stripe.com/sandboxes)
- The CLI source shows claimable sandboxes expire "in 7 days" unless claimed via `stripe sandbox claim` — [sandbox.go](https://github.com/stripe/stripe-cli/blob/master/pkg/cmd/sandbox.go)
- `stripe/stripe-mock`: 1,656 stars, MIT. It "does not attempt to reproduce the _behavior_ of the real Stripe API at all", is stateless with hardcoded responses, and "If you have more sophisticated testing needs, you shouldn't use stripe-mock" — [README](https://github.com/stripe/stripe-mock)

**API mocking**
- `mswjs/msw`: 18,288 stars, MIT, last push 2026-10-10, JavaScript only — [GitHub](https://github.com/mswjs/msw)
- Playwright Python provides `page.route()` with `route.fulfill(json=...)` and `route.fetch()` (modify the real response), plus `page.route_from_har(..., update=True)` to record and replay. HAR replay "matches URL and HTTP method strictly". `page.route_web_socket()` covers WebSockets — [Playwright Python mock docs](https://playwright.dev/python/docs/mock)
- `wiremock/wiremock`: 7,399 stars, Apache-2.0, Java. `wiremock/python-wiremock`: 81 stars, PyPI 2.7.0 (2025-07-28), a Testcontainers module — [GitHub](https://github.com/wiremock/wiremock); [python-wiremock](https://github.com/wiremock/python-wiremock)
- `testcontainers/testcontainers-python`: 2,313 stars, Apache-2.0, last push 2026-10-09. PyPI `testcontainers` 4.15.0 (2026-07-24), Python >=3.10. It needs Docker (e.g. `PostgresContainer("postgres:16")`) — [GitHub](https://github.com/testcontainers/testcontainers-python)

**Logged-in sessions**
- Playwright Python saves state with `context.storage_state(path="state.json")` and reuses it with `browser.new_context(storage_state=...)`.
  - The state covers cookies, local storage and passkeys, and IndexedDB can be included.
  - Session storage is not persisted; the workaround is `add_init_script`.
  - Keep files in `playwright/.auth` and gitignore them, because they hold "sensitive cookies and headers".
  — [Playwright auth docs](https://playwright.dev/python/docs/auth)

### Inferences
- Verdicts:
  | Candidate | Verdict | Why |
  |---|---|---|
  | Supabase CLI (`start`, `db reset`, `status -o json`) | BUILD ON | Default backend for Lovable/Bolt apps. Read keys and URLs from `status -o json` and inject them as `VITE_SUPABASE_URL` / publishable key env vars into the dev server. Run `db reset` per attempt for deterministic data. |
  | Supabase `stack` mode (per-worktree isolation) | BUILD ON, behind a flag | Matches the per-attempt worktree design (Q6) with no port clashes, but it is experimental and requires removing fixed ports from the user's `config.toml`. Contexer should not edit that file silently. |
  | Supabase native runtime | BORROW IDEAS / Linux-CI option | Useful for Linux CI runners and E2B-style sandboxes without Docker. Windows developers still need Docker. |
  | Supabase Auth Admin API test users | BUILD ON | Deterministic seeded accounts (`email_confirm: true`). Log in once through the UI, save `storage_state`, and reuse it per check. |
  | Firebase Emulator Suite | BUILD ON only if `firebase.json` detected | `emulators:exec` maps onto Contexer's start/wait/stop model. JDK requirement adds friction. |
  | Stripe CLI (`listen --forward-to`, `--print-secret`, `trigger`, `sandbox create`) | BUILD ON | Gives real test-mode behaviour. Webhook forwarding needs the CLI as a managed child process. Anonymous sandboxes reduce onboarding friction but expire in 7 days. |
  | stripe-mock | AVOID | Stateless and hardcoded, so it can't verify checkout flows. |
  | MSW | AVOID (for Contexer core) | Requires changes to the app code. |
  | Playwright `route` / HAR | BUILD ON | Mocks browser-side third-party calls with no app changes. It does **not** intercept server-side calls (Next.js route handlers, Supabase edge functions), so those need real test-mode services. |
  | Testcontainers-python / WireMock | AVOID for now | Docker-only and aimed at backend integration tests. Supabase CLI already covers Postgres for the target stack. Revisit for plain Postgres or Redis apps. |
- Never place test credentials in prompts or logs. Contexer should generate test user passwords, store them in the project's local Contexer config (gitignored), and redact `SERVICE_ROLE_KEY` and `whsec_` values from evidence logs.
- Email-confirmation flows can be verified locally through Mailpit on port 54324 (its HTTP API is an untested assumption). This beats disabling confirmations, because it exercises the real signup path.

### Gaps
- No measured `supabase start` cold and warm times were found. Only "first run takes time" and the 7 GB RAM guidance are documented.
- The current license of the TypeScript `supabase/cli` repo is unconfirmed (historically MIT from memory; not verified).
- Firebase's current minimum JDK may be higher than the JDK 11 stated on the page fetched.
- Bolt's own database product ("Bolt Database") and how it exports were not documented in primary sources.

## Q5. Preview deployments as test targets: Vercel, Netlify and Cloudflare preview URLs, GitHub deployment_status, and Vercel's protection bypass for automation

### Takeaway
Preview URLs are a cheap second target for Contexer in CI, and need no runtime management. Vercel provides `deployment_status` events, `repository_dispatch` events (`vercel.deployment.success` with `client_payload.url`) and a protection bypass header that works on all plans. Netlify uses `deploy-preview-<PR>--<site>.netlify.app` and now also previews agent runs. Cloudflare Pages uses hash and branch aliases, protected by Cloudflare Access with service-token headers. They suit a "verify the PR" GitHub Action, not the inner repair loop, because each deploy takes minutes and Contexer can't capture server logs.

### Cited Findings
- Vercel Protection Bypass for Automation:
  - "Available on all plans". It bypasses Password Protection, Vercel Authentication, Trusted IPs, bot protection and some firewall mitigations, but not active DDoS mitigations.
  - Send the header `x-vercel-protection-bypass: <secret>` (recommended) or the same name as a query param.
  - `x-vercel-set-bypass-cookie: true` (or `samesitenone` for iframes) sets a cookie for in-browser navigation.
  - Multiple secrets per project are allowed; one is exposed as `VERCEL_AUTOMATION_BYPASS_SECRET`. Regenerating a secret invalidates previous deployments.
  - The docs include a Playwright `extraHTTPHeaders` example.
  — [Vercel docs (updated 2026-09-16)](https://vercel.com/docs/deployment-protection/methods-to-bypass-deployment-protection/protection-bypass-automation)
- Vercel ↔ GitHub:
  - Vercel notifies GitHub through `deployment_status` by default, and this can be turned off per project.
  - It also sends `repository_dispatch` types `vercel.deployment.ready|success|error|canceled|ignored|skipped|pending|failed|promoted`, with `github.event.client_payload.url`. These only trigger if the workflow file exists on the default branch.
  - Vercel's migration example replaces `github.event.deployment_status.environment_url` with `client_payload.url`.
  — [Vercel for GitHub](https://vercel.com/docs/git/vercel-for-github)
- Netlify:
  - "a Deploy Preview for pull / merge request #42 will deploy to `deploy-preview-42--mysitename.netlify.app`".
  - Agent-run previews use `agent-<runid>--site`, and permalinks use `<deployid>--site`.
  - Previews can be password-protected. The page mentions no automation bypass.
  — [Netlify docs](https://docs.netlify.com/deploy/deploy-types/deploy-previews/)
- Cloudflare Pages: previews live at `<hash>.<project>.pages.dev`, with branch aliases at `<branch>.<project>.pages.dev`. They are "public by default" and can be restricted with an Access policy — [Cloudflare docs](https://developers.cloudflare.com/pages/configuration/preview-deployments/). Cloudflare Access service tokens authenticate automation via the `CF-Access-Client-Id` and `CF-Access-Client-Secret` headers — [Cloudflare One docs](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/)
- Helpers:
  - `patrickedqvist/wait-for-vercel-preview` (GitHub Action): 160 stars, MIT, last push 2026-10-12 — [GitHub](https://github.com/patrickedqvist/wait-for-vercel-preview)
  - `amondnet/vercel-action`: 764 stars, MIT — [GitHub](https://github.com/amondnet/vercel-action)
  - `cloudflare/wrangler-action`: 1,973 stars, Apache-2.0 — [GitHub](https://github.com/cloudflare/wrangler-action)
- Lovable's new stack publishes as a Cloudflare edge Worker — [Lovable blog](https://lovable.dev/blog/building-apps-using-tanstack-start)

### Inferences
- Verdicts:
  | Candidate | Verdict | Why |
  |---|---|---|
  | Vercel bypass header + `repository_dispatch` / `deployment_status` | BUILD ON (CI mode) | In Python, pass `extra_http_headers={"x-vercel-protection-bypass": secret, "x-vercel-set-bypass-cookie": "true"}` to `browser.new_context`. Trigger the Contexer GitHub Action on `vercel.deployment.success`. |
  | Netlify deploy previews | BUILD ON (URL input only) | Accept a URL. The PR-number naming makes it derivable. Password-protected previews need a manual path. |
  | Cloudflare Pages previews + Access service tokens | BUILD ON (URL + optional headers) | The same generic "extra headers" mechanism covers it. |
  | wait-for-vercel-preview action | BORROW IDEAS | Polling the GitHub deployments API is simple to reimplement. |
- Generalise as `--target-url URL --header K:V`. This covers Vercel, Cloudflare Access and basic proxies with one feature.
- Previews can't provide server logs, restarts or reverts. They should validate the final PR or catch environment-specific breaks (env vars, edge runtime), not drive the repair loop. Previews also hit real (preview-environment) Supabase and Stripe test projects, so test accounts there must be seeded separately.

### Gaps
- Whether Netlify emits GitHub `deployment_status` events, or only commit statuses and checks, was not confirmed.
- No primary documentation was found on how often preview URLs are protected by default for Lovable- or Bolt-originated projects.

## Q6. Per-attempt checkpoint and revert: git worktrees, `git stash create` and temporary-index snapshots, Jujutsu, Claude Code checkpoints and rewind, Codex undo, and agent-checkpoint libraries

### Takeaway
Contexer must own checkpointing in plain git. Agent-native mechanisms are incomplete or gone: Claude Code checkpoints skip Bash-made changes, most subagent edits and hard-linked files, and Codex removed its git "ghost snapshot" undo on 2026-04-28. The proven technique is Codex's ghost-snapshot v2: build a temporary index from `git status --porcelain=2 -z`, then `write-tree` and a detached `commit-tree` without touching the user's refs or index. Use git worktrees when attempts must run in parallel or need isolated Supabase stacks. Jujutsu is elegant but can't be assumed installed.

### Cited Findings
- Git primitives:
  - `git stash create`: "Create a stash entry (which is a regular commit object) and return its object name, without storing it anywhere in the ref namespace. This is intended to be useful for scripts." — [git-scm](https://git-scm.com/docs/git-stash)
  - `git worktree add [--detach] [--lock]`: each is a "linked worktree", cleaned up by `git worktree prune` and protectable with `lock` — [git-scm](https://git-scm.com/docs/git-worktree)
- Codex ghost snapshots:
  - "ghost snapshot v2" (PR #8055, 2025-12-15): "Snapshot creation now builds a temporary index from `git status --porcelain=2 -z`, writes a tree and detached commit without touching refs, and records any ignored large files/dirs in the snapshot report. Undo uses that metadata to preserve large local artifacts while still cleaning up new transient files." — [PR #8055](https://github.com/openai/codex/pull/8055)
  - "Remove ghost snapshots" (PR #19481, merged 2026-04-28): "make undo a no-op that reports the feature is unavailable" — [PR #19481](https://github.com/openai/codex/pull/19481)
  - Legacy `ghost_snapshot` items are now deserialized as "other" — [models.rs](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/models.rs)
- Claude Code checkpointing:
  - A checkpoint is taken "before each prompt you send that starts a turn". Snapshots are kept for the 100 most recent checkpoints and deleted after about 30 days by default.
  - `/rewind` or Esc Esc offers "Restore code and conversation / conversation / code".
  - Limitations: "Checkpointing does not track files modified by Bash commands". Most subagent edits are not restored. External and concurrent-session edits are not tracked. "Checkpointing doesn't rewind symlinked or hard-linked files ... files pnpm hard-links into place". "Not a replacement for version control".
  — [Claude Code docs](https://code.claude.com/docs/en/checkpointing)
- `RonitSachdev/ccundo`: 1,401 stars, last push 2025-07-27. Its description says "[claude now natively supports this feature]" — [GitHub](https://github.com/RonitSachdev/ccundo)
- Jujutsu:
  - `jj-vcs/jj`: 32,044 stars, Apache-2.0, last push 2026-10-14. v0.46.0 (2026-10-07) ships Windows x86_64/aarch64 binaries — [GitHub](https://github.com/jj-vcs/jj)
  - "Each operation object contains a snapshot of how the repo looked at the end of the operation". Operations can be undone with `jj undo` or restored with `jj op restore`. The working copy is snapshotted automatically — [jj docs](https://jj-vcs.github.io/jj/latest/operation-log/)
- Other:
  - `gitbutlerapp/gitbutler`: 21,809 stars, license NOASSERTION — [GitHub](https://github.com/gitbutlerapp/gitbutler)
  - `dagger/container-use` (container plus branch per agent environment): 4,069 stars — [GitHub](https://github.com/dagger/container-use)
  - GitHub searches for "agent checkpoint git snapshot" libraries found no maintained library with meaningful adoption (`gh search repos`, 2026-10-14).
- Stripe avoids git worktrees for parallel agents at its scale and uses devboxes instead — [stripe.dev](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)
- Supabase `stack` mode gives "a separate local project for each ... Git worktree" — [Supabase docs](https://supabase.com/docs/guides/local-development/running-multiple-local-projects)

### Inferences
- Verdicts:
  | Candidate | Verdict | Why |
  |---|---|---|
  | Temp-index snapshot commits (Codex v2 technique) | BUILD ON | Implement in Python: set `GIT_INDEX_FILE` to a temp path, `git read-tree HEAD`, `git add -A` (respecting `.gitignore`, skipping large untracked files), `git write-tree`, then `git commit-tree -p HEAD`. Store under `refs/contexer/<run>/<attempt>` so objects survive gc but never appear on user branches. Revert with `git read-tree -u --reset <tree>` plus removal of files created after the snapshot. This captures Bash-made changes that Claude Code checkpoints miss. |
  | git worktrees (one per attempt or per run) | BUILD ON (for parallel attempts or isolation) | Isolates the dev server, `.next`/`.vite` caches and Supabase stacks per attempt. Cost: `node_modules` per worktree means a re-install per worktree (pnpm's store helps). Windows path-length limits and OneDrive-synced folders are risks. |
  | `git stash create` | BORROW IDEAS | Ref-less commits are the right idea, but its synopsis takes only a message, so untracked files are not captured (an inference from the documented synopsis). The temp-index approach does capture them. |
  | Jujutsu | AVOID as a requirement | Users won't have it installed. The operation-log model (every command snapshots, `undo`, `op restore`) is the design to imitate in the attempt ledger. |
  | Claude Code checkpoints / `/rewind` | AVOID relying on | Session-scoped, misses Bash and most subagent edits, skips hard links. Can't be driven by an external orchestrator per attempt. |
  | Codex undo | AVOID | Removed in April 2026. |
  | ccundo, GitButler | AVOID | Obsolete or a full client. Not primitives. |
- Recommended per-attempt protocol:
  1. Before an attempt, snapshot the working tree to a hidden ref and record the attempt's base tree, dev-server log path and check results in an attempt ledger (the jj "operation log" idea).
  2. Run the coding agent and restart the app server.
  3. On failure or regression, restore the snapshot tree. Preserve ignored heavy directories (`node_modules`, `.next`), as Codex v2 did, so the dev server restarts fast.
  4. On success, offer the user a normal commit or branch.
  - Use separate worktrees only for parallel attempts. Each gets its own port and its own Supabase `--stack`.
- Never run `git clean -fdx`, which would delete `.env` files that Lovable/Bolt exports need and that aren't in git. Restores should only delete files created after the snapshot.

### Gaps
- The exact reason Codex removed ghost snapshots (beyond the PR summary) was not found. Performance on large repos or OneDrive-synced folders is a plausible cause, but unverified.
- No benchmarks were found for temp-index snapshot cost on large JS repos, or for worktree creation plus `npm ci` time on Windows.
- Claude Code's Agent SDK may expose programmatic file checkpointing, but the checkpointing page fetched does not document an SDK API, so this was not verified.
