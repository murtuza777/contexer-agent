# Phase 5: Ready for users

Goal: safe, affordable and proven on a real app, then released. See
[architecture.md](architecture.md) §12.

Phase is done when: the three tickets pass and the release is published.

---

## T5.1 Security pass

**Goal.** Nothing an agent reads can make Contexer do something the user did
not ask for.

**Scope.**
- Page text, issue text, file contents and tool results are wrapped as data in
  every prompt; a test suite of injection strings runs against each agent with
  the scripted model and one live model.
- Tool audit: which agent has which tool; no agent has a write tool except the
  external coding agent.
- Tamper guard widened to `contexer.toml` and `.contexer/intent/`.
- Codex and OpenCode adapters get the same `.contexer/**` deny rule Claude
  Code has, where the agent supports it.
- Risk scan before a run: `.env` not ignored, committed files with
  password-like keys or cookies.
- `/security-review` on the full diff of Phases 0–4.

**Acceptance.**
- The tool audit table is in `docs/architecture.md` and enforced by a test.
- The injection suite passes with the scripted model; live results published.
- A coding-agent turn that edits `contexer.toml` ends the run as `tampered`.

**Verify.** `pytest tests/test_security.py`; the review report.

---

## T5.2 Cost controls

**Goal.** A user knows the cost before and after, and can cap it.

**Scope.**
- `[agents]` in `contexer.toml`: model per agent, step caps, a run budget that
  covers Contexer's own agents and the coding agent together.
- A cheaper model for Triage and the Reviewer pre-pass when configured.
- Estimate shown before a run; actual cost per agent in the summary and in
  `result.json`.
- Free-tier check uses the estimated request count.

**Acceptance.**
- A run stops with `budget_exhausted` when the combined budget is reached, and
  restores the best attempt.
- The summary's total equals the sum of the per-agent transcripts.

**Verify.** `pytest tests/test_budget.py`.

---

## T5.3 Live runs, docs, release

**Goal.** Measured on a real app; documented; shipped.

**Scope.**
- BurryAI, three levels: `contexer test` on an existing flow; `contexer run`
  on a one-screen change; `contexer run --pr` on a change that touches the
  frontend and the Worker.
- Results (pass or fail, attempts, cost, time) in the changelog.
- `README.md`, `contexer-agent/README.md`, `docs/architecture.md`,
  `docs/try-it.md` rewritten for the new flow; `docs/multi-agent/` removed or
  archived.
- Classic engine removed if Phase 3's gate was met.
- Version bump and release.

**Acceptance.**
- All three BurryAI runs are recorded with their real outcome.
- A new user following `docs/try-it.md` reaches a first `contexer test` result
  without help.
- CI green on the release commit.

**Verify.** The recorded runs; CI. The release tag is pushed by you.
