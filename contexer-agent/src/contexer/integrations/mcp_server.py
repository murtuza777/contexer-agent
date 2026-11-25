"""``contexer mcp``: Contexer as a Model Context Protocol server, over stdio.

A coding agent a person is already working in (Claude Code, Codex, OpenCode,
Cursor) starts this as a subprocess and gets four tools:

* ``contexer_checks``: the approved contract, as the agent should read it.
* ``contexer_verify``: replay it in a real browser and say, per check, whether
  it passed or what the browser saw.
* ``contexer_brief``: the instruction a Contexer run would give for it.
* ``contexer_status``: how the last run in this project ended.

The proof rule holds here as everywhere: a check counts when code replayed
it. The agent asks; it does not decide. No tool approves a contract, edits
one or changes a setting, and a contract is named by its id only, never by a
path. Approval stays with a person, in the terminal or on the pull request.

Nothing but the protocol may reach stdout, so nothing in this module prints.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

import anyio
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from contexer import __version__
from contexer.checkpoint.lock import LOCK_FILE, RunLocked, run_lock
from contexer.contract import Contract, ContractError, ContractStore
from contexer.contract.store import CONTEXER_DIR
from contexer.controller.prompts import implement_prompt
from contexer.evidence.rundir import RUNS_DIR
from contexer.gate import RunResult
from contexer.integrations.replay import replay, verdict
from contexer.verification.models import format_contract
from contexer.verification.runner import CheckRunner
from contexer.workflow.inspector import RepositoryInspector

TOOL_NAMES = ("contexer_checks", "contexer_verify", "contexer_brief", "contexer_status")

_INSTRUCTIONS = (
    "Contexer holds the acceptance checks a person approved for this project, and replays them in a real "
    "browser. Those checks decide whether the work is done; your own judgement does not. Call contexer_checks "
    "before you start so you know what will be checked. Call contexer_verify when you think you are finished, "
    "fix what it reports, and call it again until every check passes. You cannot approve, edit or skip a check: "
    "if a check looks wrong, say so to the person and let them decide."
)

_APPROVAL = (
    "You cannot approve it: a person does, with `contexer contract approve {id}` in a terminal, after reading it."
)


def build_server(project_dir: str | Path, *, runner: CheckRunner | None = None) -> MCPServer:
    """The server for one project. ``runner`` is for tests; a real one records traces of failing checks."""
    project = Path(project_dir).resolve()
    server = MCPServer("contexer", instructions=_INSTRUCTIONS, version=__version__)
    reads = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
    # It starts the app, may run the project's own `[app] reset`, and writes evidence under .contexer/runs.
    replays = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

    @server.tool(name="contexer_checks", annotations=reads, structured_output=False)
    def contexer_checks(contract: str = "") -> str:
        """The acceptance checks a person approved for this project: each one's steps and what it expects.

        Read them before you start work. They are replayed verbatim in a real browser and decide whether the
        work is done. `contract` is a contract id; leave it empty for all of them.
        """
        return _checks(project, contract)

    @server.tool(name="contexer_verify", annotations=replays, structured_output=False)
    async def contexer_verify(contract: str = "") -> str:
        """Replay the approved checks against the app in a real browser and report each one.

        Call it when you think the work is finished. For every check it says whether it passed, or what the
        check expected and what the browser saw instead. It starts the app itself and can take a minute.
        `contract` is a contract id; leave it empty to replay every approved contract.
        """
        chosen = _approved(project, contract)

        def make_runner() -> CheckRunner:
            return runner or CheckRunner(trace="on-failure")

        try:
            result = await anyio.to_thread.run_sync(lambda: _replay_locked(project, chosen, make_runner))
        except RunLocked as exc:
            raise ToolError(f"Not replayed: {exc}") from None
        return verdict(result, then="Then call contexer_verify again.")

    @server.tool(name="contexer_brief", annotations=reads, structured_output=False)
    def contexer_brief(contract: str = "") -> str:
        """The instruction Contexer gives a coding agent for an approved contract: the goal, the checks, the rules.

        `contract` is a contract id; leave it empty when the project has one approved contract.
        """
        chosen = _approved(project, contract)
        if len(chosen) > 1:
            names = ", ".join(c.id for c in chosen)
            raise ToolError(f"This project has {len(chosen)} approved contracts ({names}). Name one in `contract`.")
        [target] = chosen
        others = [c for c in _contracts(project) if c.status == "approved" and c.id != target.id]
        return implement_prompt(target, RepositoryInspector().inspect(project), others)

    @server.tool(name="contexer_status", annotations=reads, structured_output=False)
    def contexer_status(contract: str = "") -> str:
        """How the last Contexer run in this project ended: its attempts, what was proven, and why it stopped.

        Also says whether a run is working in the project right now. `contract` narrows it to runs of one
        contract id.
        """
        return _status(project, contract)

    return server


def serve(project_dir: str | Path) -> None:
    """Serve one project over stdio until the client closes the connection."""
    from contexer.config.project import load_project_env

    project = Path(project_dir).resolve()
    load_project_env(project)  # what `[auth]` names: test accounts for the sign-in, through the filtered loader
    build_server(project).run("stdio")


# -- what the tools say -----------------------------------------------------------------------------


def _contracts(project: Path) -> list[Contract]:
    try:
        return ContractStore(project).list()
    except ContractError as exc:
        raise ToolError(f"A contract in this project cannot be read: {exc}") from None


def _named(project: Path, contract: str) -> list[Contract]:
    """Every contract, or the one with this id. An id is matched against what the project holds, never opened as a path."""
    known = _contracts(project)
    wanted = contract.strip()
    if not wanted:
        return known
    found = [c for c in known if c.id == wanted]
    if not found:
        names = ", ".join(c.id for c in known) or "none"
        raise ToolError(f"This project has no contract with the id '{wanted[:80]}'. Its contracts: {names}.")
    return found


def _approved(project: Path, contract: str) -> list[Contract]:
    named = _named(project, contract)
    approved = [c for c in named if c.status == "approved"]
    if approved:
        return approved
    if named:
        waiting = named[0]
        raise ToolError(
            f"'{waiting.id}' is not approved (it is {waiting.status}), so it does not define done yet. "
            + _APPROVAL.format(id=waiting.id)
        )
    raise ToolError(
        "This project has no contract yet. A person writes one with `contexer run \"<goal>\"` or "
        "`contexer contract draft \"<goal>\"` and approves it."
    )


def _checks(project: Path, contract: str) -> str:
    named = _named(project, contract)
    if not named:
        return (
            "This project has no contract yet, so nothing is checked. A person writes one with "
            '`contexer run "<goal>"` or `contexer contract draft "<goal>"` and approves it.'
        )
    parts: list[str] = []
    for item in named:
        if item.status == "approved":
            parts.append(
                f"Contract {item.id} (approved). Goal: {item.goal}\n"
                "Each 'do:' step and 'expect:' line is executed verbatim in a real browser:\n"
                + format_contract(item.criteria)
            )
        else:
            parts.append(
                f"Contract {item.id} is a {item.status}, not approved: it does not define done yet and is not "
                f"replayed. Goal: {item.goal}\n" + _APPROVAL.format(id=item.id)
            )
    return "\n\n".join(parts)


def _replay_locked(project: Path, contracts: list[Contract], make_runner: Callable[[], CheckRunner]) -> RunResult:
    """Replay in a thread of its own: starting the app blocks, and the server must go on answering."""
    with run_lock(project, "contexer mcp (verify)"):
        return asyncio.run(replay(project, contracts, make_runner()))


def _status(project: Path, contract: str) -> str:
    lines: list[str] = []
    holder = _lock_holder(project)
    if holder:
        lines.append(f"Working in this project right now: {holder}.")
    wanted = contract.strip()
    runs = project / CONTEXER_DIR / RUNS_DIR
    latest: dict[str, object] | None = None
    for folder in sorted((p for p in runs.iterdir() if p.is_dir()), reverse=True) if runs.is_dir() else []:
        try:
            data = json.loads((folder / "run.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # a `contexer verify`, or a run still going: it has no run.json
        if isinstance(data, dict) and (not wanted or data.get("contract_id") == wanted):
            latest = data
            break
    if latest is None:
        lines.append("No run has finished in this project yet" + (f" for the contract '{wanted[:80]}'." if wanted else "."))
        return "\n".join(lines)
    lines.append(f"Last run {latest.get('run_id')} of contract {latest.get('contract_id')}: {latest.get('terminal')}.")
    if latest.get("reason"):
        lines.append(str(latest["reason"]))
    attempts = latest.get("attempts")
    for attempt in attempts if isinstance(attempts, list) else []:
        if isinstance(attempt, dict):
            lines.append(
                f"- attempt {attempt.get('n')} ({attempt.get('kind')}): {attempt.get('outcome')}, "
                f"{attempt.get('verified', 0)} verified, {attempt.get('refuted', 0)} refuted, "
                f"{attempt.get('unverified', 0)} unverified"
            )
    return "\n".join(lines)


def _lock_holder(project: Path) -> str:
    try:
        data = json.loads((project / LOCK_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("run") or "a run") if isinstance(data, dict) else ""
