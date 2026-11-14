## What and why

<!-- One or two sentences. Link the ticket: Closes #123 -->

## How it was verified

<!-- Commands you ran and what they showed. Benchmark numbers if accuracy could change. -->

- [ ] `pytest` passes locally
- [ ] `contexer bench` unchanged, or the new numbers are in this description
- [ ] Live run (only if the change needs one): <!-- app, agent, model, result -->

## Checklist

- [ ] One ticket, one logical change
- [ ] No model output is labelled `proven`; no agent decides a run succeeded
- [ ] No secret in prompts, logs, transcripts or fixtures
- [ ] Docs and `CHANGELOG.md` (Unreleased) updated where the change touches them
