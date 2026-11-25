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

## Using Contexer safely

- Use a dedicated test account for `[auth]`, never a real one.
- Keep keys in the environment or `~/.contexer/`, not in the repository.
- Give CI the smallest GitHub token permissions the workflow needs.
