"""The evidence for one ``contexer test`` run: ``result.json`` and a self-contained ``report.html``."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from contexer.evidence.report import _CSS, _data_uri, _e
from contexer.evidence.rundir import RunDir

Outcome = Literal["no_bugs", "bugs", "could_not_test", "error"]

_BADGE = {
    "no_bugs": ("pass", "No confirmed bugs"),
    "bugs": ("fail", "Bugs confirmed"),
    "could_not_test": ("needs_action", "Could not test"),
    "error": ("error", "Error"),
}
EXIT_CODES: dict[str, int] = {"no_bugs": 0, "bugs": 1, "could_not_test": 2, "error": 3}


class ConfirmedFinding(BaseModel):
    """A finding the replay reproduced."""

    title: str
    description: str = ""
    severity: str = "medium"
    criterion_id: str
    # The recorded steps and the expectation, as a person reads them.
    check: list[str] = Field(default_factory=list)
    # What the replay saw.
    evidence: str = ""
    screenshot: Optional[str] = None


class AgentUsage(BaseModel):
    """What one of Contexer's agents used in a run."""

    agent: str
    steps: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Optional[float] = None


class ExplorationResult(BaseModel):
    """Everything ``contexer test`` reports. Only replayed findings are listed."""

    intent: str
    outcome: Outcome
    bugs: list[ConfirmedFinding] = Field(default_factory=list)
    works: list[ConfirmedFinding] = Field(default_factory=list)
    # Findings that did not reproduce: counted here, detailed in unconfirmed.json, never listed as results.
    unconfirmed: int = 0
    steps: int = 0
    tool_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Optional[float] = None
    tester_status: str = ""
    tester_error: str = ""
    summary: str = ""
    # Behaviour the intent does not settle, as the tester's questions. Not findings.
    questions: list[str] = Field(default_factory=list)
    model: str = ""
    app_url: str = ""
    project_dir: str = ""
    run_id: str = ""
    run_dir: str = ""
    # The draft contract's id, when it was saved among the project's contracts (--save).
    contract: Optional[str] = None
    # What each agent used; tokens_in, tokens_out and cost_usd above are their sums.
    agents: list[AgentUsage] = Field(default_factory=list)
    # The token budget this run had.
    budget_tokens: Optional[int] = None
    # The stored intent this run tested against (.contexer/intent/<id>.md).
    intent_id: str = ""
    # fix-prompt.md in the run folder, when there is something to fix.
    fix_prompt: Optional[str] = None
    # --again: how many saved checks were replayed, and how many still fail.
    replayed: int = 0
    still_failing: int = 0
    # Draft checks from the Intent agent that were not valid, each with the reason.
    dropped_checks: list[str] = Field(default_factory=list)
    # What the Tester proposed to remember about operating the app: saved, and refused (a secret in it).
    skills_saved: list[str] = Field(default_factory=list)
    skills_rejected: list[str] = Field(default_factory=list)
    started_at: str = ""
    duration_seconds: float = 0.0
    error: str = ""
    contexer_version: str = ""

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.outcome]


def write_test_evidence(result: ExplorationResult, run: RunDir) -> tuple[Path, Path]:
    run.result_json.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    run.report_html.write_text(render_test_report(result), encoding="utf-8")
    return run.report_html, run.result_json


def render_test_report(result: ExplorationResult) -> str:
    project = Path(result.project_dir).name or result.project_dir
    badge, label = _BADGE[result.outcome]
    stats = [
        ("Confirmed bugs", len(result.bugs), "bad"),
        ("Working, confirmed", len(result.works), "ok"),
        ("Unconfirmed", result.unconfirmed, "warn"),
        ("Tester steps", result.steps, "muted"),
    ]
    stat_html = "".join(
        f'<div class="stat stat-{cls}"><span class="num">{n}</span><span class="lbl">{name}</span></div>'
        for name, n, cls in stats
    )
    cost = f"${result.cost_usd:.4f}" if result.cost_usd is not None else "not reported by the provider"
    meta = [
        ("App", f'<a href="{_e(result.app_url)}">{_e(result.app_url)}</a>' if result.app_url else "—"),
        ("Model", _e(result.model or "—")),
        ("Started", _e(result.started_at)),
        ("Duration", f"{result.duration_seconds:.1f}s"),
        ("Cost", _e(cost)),
        ("Run", f"<code>{_e(result.run_id)}</code>"),
    ]
    meta_html = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in meta)
    notes = [n for n in (result.error, result.tester_error) if n]
    if result.tester_status and result.tester_status not in ("ok", "model_error"):
        notes.append(f"The tester stopped early ({result.tester_status}); what it had found was still replayed.")
    notes_html = (
        '<section class="card reasons"><h2>Notes</h2><ul>' + "".join(f"<li>{_e(n)}</li>" for n in notes) + "</ul></section>"
        if notes
        else ""
    )
    unconfirmed_html = (
        f'<section class="card"><h2>Unconfirmed</h2><p>{result.unconfirmed} finding(s) did not reproduce when replayed '
        "and are not shown. They are in <code>unconfirmed.json</code> with the reason.</p></section>"
        if result.unconfirmed
        else ""
    )
    summary_html = (
        f'<section class="card"><h2>The tester\'s summary</h2><p>{_e(result.summary)}</p>'
        '<p class="muted">An opinion, for context. Only the replayed findings above are evidence.</p></section>'
        if result.summary
        else ""
    )
    questions_html = (
        '<section class="card reasons"><h2>Not settled by the intent</h2><p class="muted">The tester saw these and the '
        "intent does not say which is right. They are questions for you, not bugs.</p><ul>"
        + "".join(f"<li>{_e(q)}</li>" for q in result.questions)
        + "</ul></section>"
        if result.questions
        else ""
    )
    prompt_text = ""
    if result.fix_prompt:
        try:
            prompt_text = Path(result.fix_prompt).read_text(encoding="utf-8")
        except OSError:
            prompt_text = ""
    prompt_html = (
        '<section class="card"><h2>Fix prompt</h2><p class="muted">Paste it into your coding agent, then run '
        f"<code>contexer test --again</code>. Also saved as <code>fix-prompt.md</code>.</p><pre>{_e(prompt_text)}</pre></section>"
        if prompt_text
        else ""
    )
    body = "\n".join(
        part
        for part in (
            f"""<header class="hero">
  <div class="hero-top">
    <div>
      <p class="eyebrow">Contexer test report</p>
      <h1>{_e(project)}</h1>
      <p>{_e(result.intent)}</p>
    </div>
    <span class="badge badge-{badge}">{_e(label)}</span>
  </div>
  <div class="stats">{stat_html}</div>
  <dl class="meta">{meta_html}</dl>
</header>""",
            notes_html,
            _findings("Bugs", "refuted", "✗", result.bugs, "Nothing the tester reported as a bug reproduced."),
            prompt_html,
            _findings("Working behaviours", "verified", "✓", result.works, ""),
            unconfirmed_html,
            questions_html,
            summary_html,
            f'<footer class="card"><p class="muted">Contexer {_e(result.contexer_version)}. Every finding listed '
            "here was confirmed by replay: its recorded steps were run again in a fresh browser by code, with no "
            "model involved.</p></footer>",
        )
        if part
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Contexer test · {_e(project)} · {_e(label)}</title>
<style>{_CSS}</style>
</head>
<body class="outcome-{badge}">
<main>
{body}
</main>
</body>
</html>
"""


def _findings(title: str, verdict: str, icon: str, items: list[ConfirmedFinding], empty: str) -> str:
    if not items:
        return f'<section class="card"><h2>{title}</h2><p class="muted">{_e(empty)}</p></section>' if empty else ""
    rows = []
    for item in items:
        lines = "\n".join(item.check)
        image = _data_uri(item.screenshot)
        figure = f'<figure><img src="{image}" alt="The page as the replay saw it" style="max-width:100%"></figure>' if image else ""
        description = f"<p>{_e(item.description)}</p>" if item.description else ""
        rows.append(
            f"""<li class="crit crit-{verdict}"><details{" open" if verdict == "refuted" else ""}>
<summary><div class="crit-line"><span class="icon">{icon}</span><span class="desc">{_e(item.title)}</span>
<span class="tag tag-proven">confirmed by replay</span><span class="tag">{_e(item.severity)}</span></div></summary>
<div class="crit-body">{description}<pre>{_e(lines)}</pre><p>Replay: {_e(item.evidence)}</p>{figure}</div>
</details></li>"""
        )
    return f'<section class="card"><h2>{title}</h2><ul class="criteria">{"".join(rows)}</ul></section>'
