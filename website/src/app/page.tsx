import Image from "next/image";
import { CopyCommand } from "@/components/CopyCommand";
import { Terminal, type TerminalLine } from "@/components/Terminal";
import { DOCS_URL, INSTALL, REPO_URL, RESULTS_URL } from "@/lib/site";

// Real output of `contexer demo --fix` (2026-10-26).
const DEMO: TerminalLine[] = [
  { text: "$ contexer demo --fix", tone: "cmd" },
  { text: "Contract: todo-basics (approved)", tone: "dim" },
  { text: "App: http://127.0.0.1:49737/ (static)", tone: "dim" },
  { text: "" },
  { text: "  ✓ add-shows-task  Adding a task shows it in the list · proven", tone: "pass" },
  { text: "  ✓ add-clears-input  The input is cleared after adding a task · proven", tone: "pass" },
  { text: "  ✓ empty-not-added  Submitting an empty task adds nothing · proven", tone: "pass" },
  { text: "  ✓ count-tracks-adds  The remaining count goes up with each task added · proven", tone: "pass" },
  { text: "  ✗ complete-decrements  Completing a task lowers the remaining count · proven", tone: "fail" },
  { text: '        expected: text of [data-testid="remaining-count"] equals "1 left"', tone: "plain" },
  { text: '        actual:   "2 left"', tone: "fail" },
  { text: "        uncaught exception: refesh is not defined", tone: "fail" },
  { text: "  ✓ delete-removes-right-task  Deleting a task removes that task · proven", tone: "pass" },
  { text: "  ✓ loads-clean  The app loads without errors · proven", tone: "pass" },
  { text: "FAIL: 6 verified, 1 refuted, 0 unverified", tone: "fail" },
  { text: "" },
  { text: "Attempt 1: implementing", tone: "plain" },
  { text: "Attempt 1: proving 7 checks in Chromium", tone: "plain" },
  { text: "Attempt 1: PASS: 7 verified, 0 refuted, 0 unverified", tone: "pass" },
  { text: "SUCCEEDED — Every check proven in the browser.", tone: "pass" },
];

// Real progress lines from a live run (OpenCode with a free OpenRouter model, 2026-10-26).
const RUN: TerminalLine[] = [
  { text: '$ contexer run "Users can see how many notes are pinned" --pr', tone: "cmd" },
  { text: "Attempt 1: implementing with opencode", tone: "plain" },
  { text: "  read app.js", tone: "dim" },
  { text: "  edit index.html", tone: "dim" },
  { text: "  edit app.js", tone: "dim" },
  { text: "Agent done — 2 file(s) changed (74s)", tone: "plain" },
  { text: "Attempt 1: NEEDS ACTION: 6 verified, 0 refuted, 2 unverified", tone: "plain" },
  { text: "Attempt 2: repairing", tone: "plain" },
  { text: "  edit app.js", tone: "dim" },
  { text: "Attempt 2: PASS: 8 verified, 0 refuted, 0 unverified", tone: "pass" },
  { text: "SUCCEEDED — Every check proven in the browser. (111s)", tone: "pass" },
];

const GATE: TerminalLine[] = [
  { text: "# .github/workflows/acceptance.yml", tone: "dim" },
  { text: "on: [pull_request]" },
  { text: "permissions: { contents: read, statuses: write }" },
  { text: "jobs:" },
  { text: "  gate:" },
  { text: "    runs-on: ubuntu-latest" },
  { text: "    steps:" },
  { text: "      - uses: actions/checkout@v7.0.1" },
  { text: "      - uses: murtuza777/contexer-agent@main" },
];

const STEPS = [
  {
    title: "Describe the goal",
    body: "Contexer starts your app, drafts checks a browser can execute, and tries each one on the app as it is today, so you see which already pass and which describe new behaviour.",
  },
  {
    title: "Approve what “done” means",
    body: "You read the checklist and approve it. The contract is hashed: if the coding agent edits it, the run is refuted and the contract is put back.",
  },
  {
    title: "Your agent builds it",
    body: "Claude Code, Codex or OpenCode makes the change. Its own report is recorded and never counted as a pass.",
  },
  {
    title: "Contexer proves it",
    body: "Every check runs in Chromium against your running app. Failures go back to the agent with expected and actual values; an attempt that makes things worse is rolled back.",
  },
];

const PROVIDERS = [
  "OpenRouter (free models)",
  "Anthropic",
  "OpenAI",
  "Google Gemini",
  "Groq",
  "DeepSeek",
  "Mistral",
  "Together AI",
  "xAI",
  "Fireworks",
  "Cerebras",
  "NVIDIA",
  "Ollama (local)",
  "Any OpenAI-compatible endpoint",
];

const FAQ = [
  {
    q: "How is this different from the tests my agent writes?",
    a: "The agent that wrote the code doesn't decide whether it passed. A person approves the checks before any code changes, the agent can't edit them, and Contexer runs them in its own browser.",
  },
  {
    q: "Which apps does it work with?",
    a: "Web apps it can start: static sites, Vite and Next.js, or any start command you put in contexer.toml. That includes apps behind a sign-in and apps that keep data on a server.",
  },
  {
    q: "Do I need a paid model?",
    a: "No. With an OpenRouter key, drafting and building run on free models (OpenRouter allows 50 free requests a day; a small change took about 15). A stronger model drafts better checks.",
  },
  {
    q: "Where does my code go?",
    a: "Contexer runs on your machine or in your CI. Your code goes only to the model provider you choose, through the coding agent you already use.",
  },
  {
    q: "What doesn't it do yet?",
    a: "Visual design checks, a GitHub App with an approve button, and a published accuracy figure for paid drafting models.",
  },
];

function Section({ id, title, lead, children }: { id: string; title: string; lead?: string; children: React.ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="border-t border-zinc-200 py-20">
      <div className="mx-auto max-w-5xl px-6">
        <h2 id={`${id}-title`} className="text-3xl font-semibold text-balance">
          {title}
        </h2>
        {lead ? <p className="mt-4 max-w-2xl text-lg text-pretty text-zinc-600">{lead}</p> : null}
        <div className="mt-10">{children}</div>
      </div>
    </section>
  );
}

export default function Home() {
  return (
    <>
      <header className="border-b border-zinc-200">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-6">
          <a href="#top" className="font-semibold">
            Contexer
          </a>
          <nav aria-label="Main" className="flex items-center gap-6 text-sm text-zinc-600">
            <a href="#how" className="hidden hover:text-zinc-950 sm:inline">
              How it works
            </a>
            <a href="#numbers" className="hidden hover:text-zinc-950 sm:inline">
              Accuracy
            </a>
            <a href="#start" className="hover:text-zinc-950">
              Get started
            </a>
            <a href={REPO_URL} className="hover:text-zinc-950">
              GitHub
            </a>
          </nav>
        </div>
      </header>

      <main id="top">
        <section aria-labelledby="hero-title" className="py-20">
          <div className="mx-auto max-w-5xl px-6">
            <p className="text-sm text-zinc-600">Open source · MIT license · Works with Claude Code, Codex and OpenCode</p>
            <h1 id="hero-title" className="mt-4 max-w-3xl text-5xl leading-tight font-semibold text-balance sm:text-6xl">
              Proof that your coding agent is actually done.
            </h1>
            <p className="mt-6 max-w-2xl text-lg text-pretty text-zinc-600">
              Contexer turns a goal into checks you approve, has your coding agent build it, and runs every check in a
              real browser. What reaches review has been proven, and every check you approve keeps guarding later
              changes.
            </p>
            <div className="mt-8">
              <CopyCommand command={INSTALL} />
              <p className="mt-3 text-sm text-zinc-600">
                Then run <code className="font-mono text-zinc-900">contexer setup</code>. Python 3.11+.{" "}
                <a href={DOCS_URL} className="font-medium text-zinc-950 underline underline-offset-4">
                  Read the docs
                </a>
              </p>
            </div>
            <div className="mt-14">
              <Terminal title="contexer demo --fix · real output, no API key needed" lines={DEMO} />
              <p className="mt-3 text-sm text-zinc-600">
                The demo repairs the bug with a simulated agent; <code className="font-mono">contexer run</code> drives
                a real one.
              </p>
            </div>
          </div>
        </section>

        <Section
          id="how"
          title="How a run goes"
          lead="You make two decisions: what done means, and whether to merge. Contexer does the rest, and stops at a fixed number of repair rounds or at a budget."
        >
          <ol className="grid gap-x-10 gap-y-8 sm:grid-cols-2">
            {STEPS.map((step, i) => (
              <li key={step.title}>
                <p className="font-mono text-sm text-zinc-500 tabular-nums">0{i + 1}</p>
                <h3 className="mt-1 text-lg font-semibold">{step.title}</h3>
                <p className="mt-2 text-pretty text-zinc-600">{step.body}</p>
              </li>
            ))}
          </ol>
          <div className="mt-12">
            <Terminal title="A live run: OpenCode on a free model, one repair round" lines={RUN} />
            <p className="mt-3 text-sm text-zinc-600">
              With <code className="font-mono">--pr</code> the run ends in a pull request that lists every check with
              its verdict, the attempts and the cost. If something still fails, it opens as a draft that says what.
            </p>
          </div>
        </Section>

        <Section
          id="evidence"
          title="Evidence you can read"
          lead="Every run writes one self-contained report: the verdict and why, expected against actual for every failed check, the screenshot each check was judged on, and the agent's diff."
        >
          <figure>
            <Image
              src="/report.png"
              alt="A Contexer report: 6 checks verified and 1 refuted, with the reason: expected “1 left”, got “2 left”."
              width={2160}
              height={1350}
              className="rounded-xl border border-zinc-200"
              sizes="(min-width: 1024px) 976px, 100vw"
            />
            <figcaption className="mt-3 text-sm text-zinc-600">The report from the demo above.</figcaption>
          </figure>
        </Section>

        <Section
          id="issues"
          title="Hand it GitHub issues"
          lead="contexer init --issues adds a workflow that takes an issue to a proven pull request."
        >
          <ol className="grid gap-8 sm:grid-cols-3">
            <li>
              <h3 className="font-semibold">Label the issue</h3>
              <p className="mt-2 text-pretty text-zinc-600">
                Contexer posts the checks it drafted from the issue and how each fares on the app today. You can edit
                them in the comment.
              </p>
            </li>
            <li>
              <h3 className="font-semibold">Reply /contexer approve</h3>
              <p className="mt-2 text-pretty text-zinc-600">
                Only someone with write access can approve. One comment on the issue follows the run as it goes.
              </p>
            </li>
            <li>
              <h3 className="font-semibold">Review the pull request</h3>
              <p className="mt-2 text-pretty text-zinc-600">
                It closes the issue and carries the evidence. The coding agent never gets a GitHub token; Contexer
                pushes.
              </p>
            </li>
          </ol>
        </Section>

        <Section
          id="gate"
          title="Guard every later change"
          lead="Approved checks replay on every pull request, by any agent or person, with no model involved. Make contexer/acceptance a required check and nothing merges until the behaviour is proven again."
        >
          <Terminal title="GitHub Actions · about 40 seconds per pull request" lines={GATE} />
        </Section>

        <Section
          id="numbers"
          title="Measured, not claimed"
          lead="contexer bench runs contracts against 7 fixture apps with 40 seeded bugs, and against harmless variants that must still pass."
        >
          <div className="overflow-x-auto">
            <table className="w-full min-w-[36rem] text-left text-sm">
              <thead className="border-b border-zinc-200 text-zinc-600">
                <tr>
                  <th scope="col" className="py-3 pr-6 font-medium">
                    Contracts
                  </th>
                  <th scope="col" className="py-3 pr-6 font-medium">
                    Seeded bugs caught
                  </th>
                  <th scope="col" className="py-3 font-medium">
                    False failures on correct code
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 tabular-nums">
                <tr>
                  <td className="py-3 pr-6">Written by hand</td>
                  <td className="py-3 pr-6 font-medium">40 of 40</td>
                  <td className="py-3 font-medium">0 of 278 checks</td>
                </tr>
                <tr>
                  <td className="py-3 pr-6">Drafted from one-line goals by a free model</td>
                  <td className="py-3 pr-6 font-medium">33 of 40</td>
                  <td className="py-3 font-medium">0 of 164 checks</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p className="mt-4 max-w-2xl text-sm text-pretty text-zinc-600">
            The hand-written contracts and the bugs come from the same author, so that row measures the runner, not
            drafting.{" "}
            <a href={RESULTS_URL} className="font-medium text-zinc-950 underline underline-offset-4">
              Method and per-run results
            </a>
          </p>
        </Section>

        <Section
          id="models"
          title="Bring your own model"
          lead="contexer setup asks for a provider, your key and a model, and sends one real request before saving anything. The coding agent uses the same key."
        >
          <ul className="grid grid-cols-2 gap-x-6 gap-y-2 text-zinc-700 sm:grid-cols-3">
            {PROVIDERS.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </Section>

        <Section id="start" title="Get started" lead="In about five minutes, on your own app.">
          <ol className="max-w-3xl space-y-6">
            <li>
              <p className="mb-2 text-zinc-700">1. Install Contexer (Python 3.11 or newer).</p>
              <CopyCommand command={INSTALL} />
            </li>
            <li>
              <p className="mb-2 text-zinc-700">2. Choose a model and a coding agent. It tests both and offers to install Chromium.</p>
              <CopyCommand command="contexer setup" />
            </li>
            <li>
              <p className="mb-2 text-zinc-700">3. See it catch a bug, with no key and no agent.</p>
              <CopyCommand command="contexer demo --fix" />
            </li>
            <li>
              <p className="mb-2 text-zinc-700">4. In your app&apos;s folder, describe what must be true.</p>
              <CopyCommand command='contexer run "Users can export their data as CSV" --pr' />
            </li>
          </ol>
          <p className="mt-8 max-w-2xl text-sm text-pretty text-zinc-600">
            Needs git, and Node.js for JavaScript apps. <code className="font-mono">contexer doctor</code> checks
            everything and prints the fix for each problem.
          </p>
        </Section>

        <Section id="faq" title="Questions">
          <dl className="max-w-3xl space-y-8">
            {FAQ.map((item) => (
              <div key={item.q}>
                <dt className="font-semibold">{item.q}</dt>
                <dd className="mt-2 text-pretty text-zinc-600">{item.a}</dd>
              </div>
            ))}
          </dl>
        </Section>
      </main>

      <footer className="border-t border-zinc-200">
        <div className="mx-auto flex max-w-5xl flex-col gap-2 px-6 py-10 text-sm text-zinc-600 sm:flex-row sm:justify-between">
          <p>Contexer is open source under the MIT license.</p>
          <a href={REPO_URL} className="hover:text-zinc-950">
            github.com/murtuza777/contexer-agent
          </a>
        </div>
      </footer>
    </>
  );
}
