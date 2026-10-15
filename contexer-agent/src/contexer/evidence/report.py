"""Self-contained HTML evidence report and machine-readable result for a run.

The report is what a reviewer opens instead of re-testing by hand, so it puts
the verdict and the failures first, shows expected vs. actual for every
refuted check, and inlines the screenshot each check was judged on. It needs
no network access: styles are inline and images are data URIs.
"""

from __future__ import annotations

import base64
import html
import json
from pathlib import Path
from typing import Optional

from contexer.evidence.rundir import RunDir
from contexer.gate.models import ContractOutcome, RunResult
from contexer.verification.models import CriterionResult

_METHOD_LABELS = {"assertion": "proven", "judgment": "LLM-judged", "heuristic": "heuristic"}
_VERDICT_ICONS = {"verified": "✓", "refuted": "✗", "unverified": "?"}
_OUTCOME_LABELS = {"pass": "Pass", "fail": "Fail", "needs_action": "Needs action", "error": "Error"}
_LOG_TAIL_LINES = 80


def write_evidence(result: RunResult, run: RunDir) -> tuple[Path, Path]:
    """Write ``result.json`` and ``report.html`` into the run directory."""
    run.result_json.write_text(result_json(result), encoding="utf-8")
    run.report_html.write_text(render_report(result), encoding="utf-8")
    return run.result_json, run.report_html


def result_json(result: RunResult) -> str:
    """JSON without the bulky page capture (full HTML and inline screenshot)."""
    data = result.model_dump(
        mode="json",
        exclude={"load": {"html", "screenshot_base64", "visible_text"}},
    )
    for outcome in data.get("contracts", []):
        for c in outcome.get("contract", {}).get("criteria", []):
            if c.get("check") is None:
                c.pop("check", None)
    return json.dumps(data, indent=2, ensure_ascii=False)


def render_report(result: RunResult) -> str:
    decision = result.decision
    project = Path(result.project_dir).name or result.project_dir
    outcome = decision.outcome
    sections = [
        _header(result, project),
        _reasons(result),
        *(_contract_section(o) for o in _ordered(result.contracts)),
        _load_section(result),
        _log_section(result),
        _footer(result),
    ]
    body = "\n".join(s for s in sections if s)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Contexer · {_e(project)} · {_e(_OUTCOME_LABELS[outcome])}</title>
<style>{_CSS}</style>
</head>
<body class="outcome-{outcome}">
<main>
{body}
</main>
</body>
</html>
"""


# -- sections ----------------------------------------------------------------


def _header(result: RunResult, project: str) -> str:
    d = result.decision
    stats = [
        ("Verified", d.verified, "ok"),
        ("Refuted", d.refuted, "bad"),
        ("Unverified", d.unverified, "warn"),
        ("Advisory", d.advisory, "muted"),
    ]
    stat_html = "".join(
        f'<div class="stat stat-{cls}"><span class="num">{n}</span><span class="lbl">{label}</span></div>'
        for label, n, cls in stats
    )
    mode = "gate" if result.require_approval else "ad-hoc goal"
    meta = [
        ("App", f'<a href="{_e(result.app_url)}">{_e(result.app_url)}</a>' if result.app_url else "—"),
        ("Started", _e(result.started_at)),
        ("Duration", f"{result.duration_seconds:.1f}s"),
        ("Mode", mode),
        ("Run", f"<code>{_e(result.run_id)}</code>"),
    ]
    meta_html = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in meta)
    return f"""<header class="hero">
  <div class="hero-top">
    <div>
      <p class="eyebrow">Contexer acceptance report</p>
      <h1>{_e(project)}</h1>
    </div>
    <span class="badge badge-{d.outcome}">{_e(_OUTCOME_LABELS[d.outcome])}</span>
  </div>
  <div class="stats">{stat_html}</div>
  <dl class="meta">{meta_html}</dl>
</header>"""


def _reasons(result: RunResult) -> str:
    reasons = result.decision.reasons
    if result.error:
        reasons = [result.error, *reasons]
    if not reasons:
        return ""
    items = "".join(f"<li>{_e(r)}</li>" for r in reasons[:30])
    more = f"<li class='muted'>… and {len(reasons) - 30} more</li>" if len(reasons) > 30 else ""
    return f'<section class="card reasons"><h2>Why</h2><ul>{items}{more}</ul></section>'


def _contract_section(outcome: ContractOutcome) -> str:
    contract = outcome.contract
    status = outcome.status
    if status == "approved" and contract.approval:
        approval = contract.approval
        status_html = (
            f'<span class="pill pill-ok">approved</span> by {_e(approval.by)} · {_e(approval.at[:10])} · '
            f"<code>{_e(approval.sha256[:12])}</code>"
        )
    elif status == "modified":
        status_html = '<span class="pill pill-warn">modified after approval</span>'
    else:
        status_html = '<span class="pill pill-warn">draft — not approved</span>'

    rows: list[str] = []
    if outcome.error:
        rows.append(f'<p class="bad">{_e(outcome.error)}</p>')
    verification = outcome.verification
    results = {r.criterion_id: r for r in verification.criteria_results} if verification else {}
    for criterion in contract.criteria:
        result = results.get(criterion.id)
        steps = criterion.check.describe_lines() if criterion.check else []
        rows.append(_criterion_row(criterion.id, criterion.description, steps, result))
    if verification and not verification.criteria_results and verification.reason:
        rows.append(f'<p class="bad">{_e(verification.reason)}</p>')

    return f"""<section class="card contract">
  <div class="contract-head">
    <h2>{_e(contract.goal)}</h2>
    <p class="muted"><code>{_e(contract.id)}</code> · {status_html}</p>
  </div>
  <ol class="criteria">{''.join(rows)}</ol>
</section>"""


def _criterion_row(cid: str, description: str, steps: list[str], result: Optional[CriterionResult]) -> str:
    if result is None:
        return (
            f'<li class="crit crit-unverified"><div class="crit-line"><span class="icon">?</span>'
            f'<span class="desc">{_e(description)}</span><span class="tag">not run</span></div></li>'
        )
    verdict = result.verdict
    method = _METHOD_LABELS.get(result.method, result.method)
    method_cls = "proven" if result.proven else "judged"
    check = result.check_result
    duration = f"{check.duration_seconds:.1f}s" if check else ""

    details: list[str] = []
    if steps:
        details.append("<pre class='steps'>" + _e("\n".join(steps)) + "</pre>")
    if check is not None:
        if check.failed_step:
            details.append(f"<p class='warn'>Could not perform {_e(check.failed_step)}</p>")
        failed = [o for o in check.outcomes if not o.passed]
        if failed:
            table = "".join(
                f"<tr><td>{_e(o.description)}</td><td class='bad'>{_e(o.actual)}</td></tr>" for o in failed
            )
            details.append(f"<table class='diff'><tr><th>Expected</th><th>Actual</th></tr>{table}</table>")
        if check.page_errors:
            errs = "".join(f"<li>{_e(e)}</li>" for e in check.page_errors[:5])
            details.append(f"<p class='bad'>Uncaught exceptions:</p><ul class='errors'>{errs}</ul>")
        if check.ui_at_failure:
            details.append(
                "<details><summary>What the page offered instead</summary>"
                f"<pre>{_e(check.ui_at_failure)}</pre></details>"
            )
        image = _data_uri(check.screenshot)
        if image:
            details.append(f'<figure><img src="{image}" alt="Page when {_e(cid)} was judged" loading="lazy"></figure>')
        if check.trace:
            details.append(
                f"<p class='muted'>Trace: <code>{_e(check.trace)}</code> — open with "
                f"<code>npx playwright show-trace</code></p>"
            )
    elif result.evidence:
        details.append(f"<p class='muted'>{_e(result.evidence)}</p>")

    open_attr = " open" if verdict != "verified" else ""
    return f"""<li class="crit crit-{verdict}">
  <details{open_attr}>
    <summary class="crit-line">
      <span class="icon">{_VERDICT_ICONS[verdict]}</span>
      <span class="desc"><code>{_e(cid)}</code> {_e(description)}</span>
      <span class="tag tag-{method_cls}">{_e(method)}</span>
      <span class="dur">{duration}</span>
    </summary>
    <div class="crit-body">{''.join(details)}</div>
  </details>
</li>"""


def _load_section(result: RunResult) -> str:
    load = result.load
    if load is None:
        return ""
    parts: list[str] = []
    title = f"“{_e(load.page_title)}”" if load.page_title else "untitled page"
    status = f"HTTP {load.status_code}" if load.status_code else ("unreachable" if not load.success else "")
    parts.append(f"<p class='muted'>{title} · {_e(status)}</p>")
    if load.page_errors:
        errs = "".join(f"<li>{_e(e)}</li>" for e in load.page_errors[:5])
        parts.append(f"<p class='bad'>Uncaught exceptions on load:</p><ul class='errors'>{errs}</ul>")
    image = _data_uri(load.screenshot_path)
    if image:
        parts.append(f'<figure><img src="{image}" alt="Page on load" loading="lazy"></figure>')
    return (
        "<section class='card'><details><summary><h2 class='inline'>Page on load</h2></summary>"
        f"{''.join(parts)}</details></section>"
    )


def _log_section(result: RunResult) -> str:
    tail = result.server_log_tail.strip()
    if not tail:
        return ""
    lines = tail.splitlines()[-_LOG_TAIL_LINES:]
    return (
        "<section class='card'><details><summary><h2 class='inline'>Server log (last lines)</h2></summary>"
        f"<pre class='log'>{_e(chr(10).join(lines))}</pre></details></section>"
    )


def _footer(result: RunResult) -> str:
    return (
        "<footer><p><strong>proven</strong> verdicts come from executing the check in Chromium. "
        "<strong>LLM-judged</strong> and <strong>heuristic</strong> verdicts are advisory and never pass the gate "
        f"on their own.</p><p class='muted'>Contexer {_e(result.contexer_version)} · "
        f"<code>{_e(result.run_dir)}</code></p></footer>"
    )


# -- helpers -----------------------------------------------------------------


def _ordered(outcomes: list[ContractOutcome]) -> list[ContractOutcome]:
    """Contracts with failures first, so the reader starts where the problem is."""

    def rank(o: ContractOutcome) -> int:
        if o.error:
            return 0
        v = o.verification
        if v is None:
            return 0
        verdicts = {r.verdict for r in v.criteria_results}
        if "refuted" in verdicts:
            return 1
        if "unverified" in verdicts or o.status != "approved":
            return 2
        return 3

    return sorted(outcomes, key=rank)


def _data_uri(path: Optional[str]) -> str:
    if not path:
        return ""
    file = Path(path)
    try:
        data = file.read_bytes()
    except OSError:
        return ""
    mime = "image/png" if file.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


_CSS = """
:root {
  --bg: #f6f7f9; --card: #ffffff; --text: #16181d; --muted: #5f6672; --border: #e3e6eb;
  --ok: #157f3b; --ok-bg: #e5f5ea; --bad: #b42318; --bad-bg: #fdecea; --warn: #9a5b00; --warn-bg: #fdf3e1;
  --code-bg: #f0f2f5; --accent: #2f5bd3;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1115; --card: #171a21; --text: #e7e9ee; --muted: #9aa3b2; --border: #272c36;
    --ok: #4cc27a; --ok-bg: #12301f; --bad: #ff6b5e; --bad-bg: #3a1714; --warn: #f0b04a; --warn-bg: #3a2a10;
    --code-bg: #1f232c; --accent: #7c9cff;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
main { max-width: 980px; margin: 0 auto; padding: 24px 16px 48px; }
a { color: var(--accent); }
code, pre { font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; font-size: 13px; }
code { background: var(--code-bg); padding: 1px 5px; border-radius: 4px; }
pre { background: var(--code-bg); padding: 10px 12px; border-radius: 8px; overflow-x: auto; white-space: pre-wrap; }
h1 { font-size: 26px; margin: 2px 0 0; }
h2 { font-size: 17px; margin: 0; }
h2.inline { display: inline; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; margin-top: 16px; }
.hero { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px 18px; }
.hero-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
.eyebrow { margin: 0; color: var(--muted); font-size: 13px; text-transform: uppercase; letter-spacing: .06em; }
.badge { font-weight: 700; padding: 6px 14px; border-radius: 999px; font-size: 15px; white-space: nowrap; }
.badge-pass { background: var(--ok-bg); color: var(--ok); }
.badge-fail { background: var(--bad-bg); color: var(--bad); }
.badge-needs_action { background: var(--warn-bg); color: var(--warn); }
.badge-error { background: var(--bad-bg); color: var(--bad); }
.stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 16px; }
.stat { border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; display: flex; flex-direction: column; }
.stat .num { font-size: 22px; font-weight: 700; }
.stat .lbl { color: var(--muted); font-size: 13px; }
.stat-ok .num { color: var(--ok); } .stat-bad .num { color: var(--bad); } .stat-warn .num { color: var(--warn); }
.stat-muted .num { color: var(--muted); }
.meta { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 8px 16px; margin: 16px 0 0; }
.meta dt { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .05em; }
.meta dd { margin: 0; overflow-wrap: anywhere; }
.reasons ul { margin: 8px 0 0; padding-left: 20px; }
.reasons li { margin: 4px 0; overflow-wrap: anywhere; }
.contract-head p { margin: 4px 0 0; }
.pill { padding: 1px 8px; border-radius: 999px; font-size: 12px; font-weight: 600; }
.pill-ok { background: var(--ok-bg); color: var(--ok); } .pill-warn { background: var(--warn-bg); color: var(--warn); }
.criteria { list-style: none; padding: 0; margin: 12px 0 0; }
.crit { border-top: 1px solid var(--border); }
.crit > details > summary { list-style: none; cursor: pointer; }
.crit > details > summary::-webkit-details-marker { display: none; }
.crit-line { display: flex; align-items: baseline; gap: 10px; padding: 10px 2px; }
.crit-line .icon { width: 20px; flex: none; font-weight: 700; text-align: center; }
.crit-line .desc { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.crit-verified .icon { color: var(--ok); } .crit-refuted .icon { color: var(--bad); } .crit-unverified .icon { color: var(--warn); }
.tag { font-size: 12px; padding: 1px 8px; border-radius: 999px; border: 1px solid var(--border); white-space: nowrap; }
.tag-proven { color: var(--ok); border-color: var(--ok); }
.tag-judged { color: var(--warn); border-color: var(--warn); }
.dur { color: var(--muted); font-size: 12px; width: 44px; text-align: right; flex: none; }
.crit-body { padding: 0 2px 12px 30px; }
.diff { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 14px; }
.diff th, .diff td { text-align: left; border: 1px solid var(--border); padding: 6px 8px; vertical-align: top; overflow-wrap: anywhere; }
.diff th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; }
figure { margin: 10px 0 0; }
figure img { max-width: 100%; border: 1px solid var(--border); border-radius: 8px; display: block; }
.errors { margin: 4px 0; padding-left: 20px; }
.ok { color: var(--ok); } .bad { color: var(--bad); } .warn { color: var(--warn); } .muted { color: var(--muted); }
.log { max-height: 360px; overflow-y: auto; }
footer { margin-top: 24px; color: var(--muted); font-size: 13px; }
@media (max-width: 560px) {
  .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .crit-body { padding-left: 4px; }
  .dur { display: none; }
}
"""
