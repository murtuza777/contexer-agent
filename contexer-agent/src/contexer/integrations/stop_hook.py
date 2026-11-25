"""The stop hook: a coding agent may not end its turn while an approved check fails.

An agent that may call a verifier may also not call it. A rule in a prompt is advice; a hook is code. The
agent's own harness (Claude Code, Codex) runs ``contexer hook stop`` when the agent says it is done. This
module replays the approved contracts and answers: let it stop, or keep it working with what the browser
saw.

Three things keep it from being a trap or a tax:

* a cap on blocks in a row per session, after which the stop goes through and the person is told the work
  is not proven;
* nothing is replayed when no file and no contract changed since the last replay passed, so a turn that
  only answered a question costs a hash, not a browser;
* any failure of Contexer itself lets the stop through and says so.

It never approves, edits or skips a check, and it writes only under ``.contexer/``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from contexer.checkpoint.lock import RunLocked, run_lock
from contexer.checkpoint.shadow import ShadowRepo, SnapshotError
from contexer.contract import Contract, ContractError, ContractStore
from contexer.contract.store import CONTEXER_DIR
from contexer.evidence.rundir import write_whole
from contexer.integrations.replay import replay, verdict
from contexer.verification.runner import CheckRunner

MAX_BLOCKS = 3
STATE_FILE = str(Path(CONTEXER_DIR) / "hook-state.json")
HOOK_COMMAND = "contexer hook stop"
# A replay starts the app and a browser. Both Claude Code and Codex count this in seconds.
HOOK_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class StopAnswer:
    """Whether the agent must keep working, and what it (``block``) or the person (otherwise) is told."""

    block: bool
    message: str = ""


_ALLOW = StopAnswer(block=False)


def answer_stop(
    project_dir: str | Path,
    payload: dict[str, Any],
    *,
    max_blocks: int = MAX_BLOCKS,
    make_runner: Callable[[], CheckRunner] | None = None,
) -> StopAnswer:
    """Decide one stop. ``payload`` is what the agent's harness sent; only ``session_id`` is read."""
    project = Path(project_dir).resolve()
    store = ContractStore(project)
    if not store.root.is_dir():
        return _ALLOW  # not a Contexer project: nothing to hold, and nothing is written
    try:
        approved = [c for c in store.list() if c.status == "approved"]
    except ContractError as exc:
        return StopAnswer(block=False, message=f"Contexer checked nothing: a contract cannot be read. {exc}")
    if not approved:
        return _ALLOW
    session = str(payload.get("session_id") or "")
    try:
        with run_lock(project, "contexer hook (stop)"):
            return _decide(project, approved, session, max(0, max_blocks), make_runner or _default_runner)
    except RunLocked:
        return _ALLOW  # a Contexer run is working here and has its own verdict


def claude_code_output(answer: StopAnswer) -> str:
    """What the hook prints for Claude Code. Codex reads the same shape."""
    if answer.block:
        return json.dumps({"decision": "block", "reason": answer.message})
    if answer.message:
        return json.dumps({"systemMessage": answer.message})
    return ""


def main(raw: str, project_dir: str | Path | None, *, cwd_from_env: str = "", max_blocks: int = MAX_BLOCKS) -> str:
    """The whole command: read the harness's JSON, decide, return what to print. Never raises."""
    try:
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        project = Path(project_dir or cwd_from_env or str(payload.get("cwd") or "") or ".").resolve()
        from contexer.config.project import load_project_env

        load_project_env(project)  # what `[auth]` names: test accounts for the sign-in
        return claude_code_output(answer_stop(project, payload, max_blocks=max_blocks))
    except Exception as exc:  # noqa: BLE001 - a hook that breaks must not trap the agent
        from contexer.llm.chat import clean_error

        text = clean_error(exc)
        return json.dumps({"systemMessage": f"Contexer's stop hook failed, so nothing was checked: {text}"})


# -- internals ----------------------------------------------------------------------------------------


def _default_runner() -> CheckRunner:
    return CheckRunner(trace="on-failure")


def _decide(project: Path, approved: list[Contract], session: str, max_blocks: int, make_runner: Callable[[], CheckRunner]) -> StopAnswer:
    state = _read_state(project)
    same_session = state.get("session") == session
    blocks = int(state.get("blocks") or 0) if same_session else 0
    seen = _fingerprint(project, approved)
    if seen and state.get("fingerprint") == seen:
        if state.get("outcome") == "pass" or (same_session and state.get("outcome") == "gave_up"):
            return _ALLOW  # nothing changed since Contexer last answered

    result = asyncio.run(replay(project, approved, make_runner()))
    if result.decision.outcome == "pass":
        _write_state(project, session, 0, seen, "pass")
        return _ALLOW
    evidence = f" Evidence: {Path(result.run_dir) / 'report.html'}" if result.run_dir else ""
    if blocks >= max_blocks:
        _write_state(project, session, 0, seen, "gave_up")
        return StopAnswer(
            block=False,
            message=(
                f"Contexer: the approved checks still fail after {max_blocks} "
                f"{'try' if max_blocks == 1 else 'tries'} in a row ({result.decision.headline()}), so the agent "
                f"was allowed to stop. The work is NOT proven.{evidence}"
            ),
        )
    blocks += 1
    _write_state(project, session, blocks, seen, "fail")
    head = (
        f"Contexer replayed the approved checks in a real browser and they do not pass (try {blocks} of "
        f"{max_blocks}). You are not done.\n"
    )
    return StopAnswer(block=True, message=head + verdict(result, then="Contexer replays the checks when you stop again."))


def _fingerprint(project: Path, approved: list[Contract]) -> str:
    """The project's files and its approved contracts as one id; empty when it cannot be taken."""
    try:
        tree = ShadowRepo(project).tree()
    except SnapshotError:
        return ""
    digest = hashlib.sha256(tree.encode())
    for item in approved:  # `.contexer/` is outside the tree, and a newly approved contract must be replayed
        digest.update(json.dumps(item.to_file_dict(), sort_keys=True, ensure_ascii=False).encode())
    return digest.hexdigest()


def _read_state(project: Path) -> dict[str, Any]:
    try:
        data = json.loads((project / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(project: Path, session: str, blocks: int, fingerprint: str, outcome: str) -> None:
    state = {"session": session, "blocks": blocks, "fingerprint": fingerprint, "outcome": outcome}
    write_whole(project / STATE_FILE, json.dumps(state, indent=2) + "\n")
