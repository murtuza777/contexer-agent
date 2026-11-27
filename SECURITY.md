# Security policy

## Reporting a vulnerability

Please report it privately:
[open a private security advisory](https://github.com/murtuza777/contexer-agent/security/advisories/new).
Do not open a public issue or pull request for it.

Include what you found, how to reproduce it, and the version or commit. You
should get a reply within 7 days. Once a fix is released, the advisory is
published and you are credited unless you ask not to be.

## Supported versions

Only the latest release and `main` receive security fixes.

## What counts

Contexer runs coding agents and a browser on a developer's machine and in CI.
Reports in these areas are especially useful:

- a way for a coding agent, a web page or a GitHub issue to make Contexer
  report a pass that no check proved;
- a way to edit an approved contract without the run being refused;
- a secret reaching a prompt, a log, a report, a transcript or a commit;
- a GitHub token or model key reaching a coding agent;
- text from a page, an issue or a repository file being followed as an
  instruction by one of Contexer's agents;
- a run leaving processes behind or changing files outside the project.

The measures in place are listed in
[docs/architecture.md](contexer-agent/docs/architecture.md) §17.

## What leaves the machine

[What Contexer sends, and what it does not do](contexer-agent/docs/data-and-limits.md)
lists, per command, which model is called and what text each prompt holds,
every other network destination, and what is kept on disk. It also states
what the masking misses and what Contexer does not control about the coding
agent it starts. Read it before allowing Contexer on a repository.

## What is masked, and what is not

Contexer sends prompts to the model provider you configure. Before a prompt
is sent, and before the app's log is kept, three kinds of value are replaced:

- the password, token or one-time code the `[auth]` sign-in types;
- the exact values of the provider keys and tokens Contexer knows by
  variable name (the model provider keys, `GITHUB_TOKEN`, `GH_TOKEN`,
  `CONTEXER_GITHUB_TOKEN`, `CODEX_API_KEY`, the Langfuse keys);
- anything shaped like an OpenRouter, OpenAI-style (`sk-...`) or Google
  (`AIza...`) key.

This covers the dev server's log (in `server.log`, `result.json`, the report
and every prompt that quotes it), the task each of Contexer's agents is
given, what their tools return, and their transcripts.

The prompt sent to the coding agent is masked too: the first instruction and
every repair prompt pass through the same replacement before they are sent,
and the copy kept in the run folder (`attempt-<n>/prompt.md`) is the text
that was sent. A repair prompt quotes the page, so this is where an `[auth]`
password or a key the app displays would otherwise reach the coding agent
and its provider. A password that is also an ordinary word is replaced
wherever that word stands in the prompt.

Nothing else is recognised. A secret of your app under another variable name
(`DATABASE_URL`, `STRIPE_SECRET_KEY`), a key of another shape (AWS, a GitHub
`ghp_...` token, a JWT), or a value that is encoded or split over lines
passes unchanged if the app prints it, shows it on a page, or keeps it in a
file an agent reads. Masking is a second line, not a guarantee: the first is
a test environment that holds no real secret. The details are in
[docs/architecture.md](contexer-agent/docs/architecture.md), "Masking".

## Using Contexer safely

- Use a dedicated test account for `[auth]`, never a real one.
- Run the app Contexer starts with test data and test keys only: what it
  prints and shows can reach the model provider.
- Keep keys in the environment or `~/.contexer/`, not in the repository.
- Give CI the smallest GitHub token permissions the workflow needs.
