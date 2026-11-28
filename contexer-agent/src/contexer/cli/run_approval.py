"""Asking a person to approve the checks: the one decision in a run that is theirs alone.

Nothing here approves by accident. Only ``y`` approves; a stray word is asked about again; an edit made in
the editor is shown and asked about, never taken as approval. Where there is no terminal the callers
approve nothing (``cli/run_cli.py``), and ``--yes`` is recorded as not reviewed by a person.
"""

from __future__ import annotations

import os
import shlex
import subprocess

import typer
from rich.console import Console
from rich.markup import escape

from contexer.cli import term
from contexer.contract import Contract, ContractError, ContractStore

APPROVE_QUESTION = "Approve these checks as the definition of done?"


def read_decision(typed: str) -> tuple[str, str]:
    """What a line typed at the approval prompt means: approve, reject, edit, correction (with its text) or unclear.

    Only ``y`` approves. An empty line is a no. One word that is not a key is nothing at all: a sentence is a
    correction, a slip of the finger is not, and it must not cost a redraft.
    """
    text = typed.strip()
    low = text.lower()
    if low in ("y", "yes"):
        return "approve", ""
    if low in ("n", "no", ""):
        return "reject", ""
    if low in ("e", "edit"):
        return "edit", ""
    if len(text.split()) < 2:
        return "unclear", text
    return "correction", text


def _ask_approval(console: Console, *, can_correct: bool = True) -> tuple[str, str]:
    """Show the keys and ask until the answer is one of them, or a sentence where a sentence can be used."""
    keys = "y approve · n do not approve · e edit the checks in your editor"
    console.print(f"  [dim]{keys}{' · or type what to change' if can_correct else ''}[/]")
    while True:
        kind, text = read_decision(typer.prompt(APPROVE_QUESTION, default="", show_default=False))
        if kind == "unclear":
            console.print(f"  '{escape(text)}' is not one of the keys. Nothing was approved.")
        elif kind == "correction" and not can_correct:
            console.print("  No model is set up to redraft the checks from a sentence. `e` opens them in your editor.")
        else:
            return kind, text


def _not_at_a_terminal(contract_id: str) -> tuple[str, str]:
    """Why nothing was approved where no person can read the checks, and the two ways on."""
    return (
        "this is not a terminal, so nobody read the checks",
        f"read them, then `contexer contract approve {contract_id}`. Or pass --yes: "
        "that approves without a reading and is recorded as not reviewed by a person.",
    )


def _numbered(console: Console, lines: list[str]) -> None:
    """The checks as a numbered list, each check's steps under it. A correction can name a check by its number."""
    number = 0
    for line in lines:
        if line.startswith(" "):
            console.print(f"      [dim]{escape(line.strip())}[/]", highlight=False)
        else:
            number += 1
            console.print(f"  [dim]{number:>2}[/]  {escape(line)}", highlight=False)


def _editor_argv(command: str) -> list[str]:
    """``$VISUAL`` or ``$EDITOR`` as a program and its arguments (``code --wait``). No shell reads it."""
    try:
        parts = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        return []
    return [part.strip('"') for part in parts] if os.name == "nt" else parts


def _edit_contract(console: Console, store: ContractStore, contract_id: str) -> Contract | None:
    """Open the contract's file in the person's editor. The edited contract, or None when there is none to show.

    The editor is started as a program with the file as its last argument; nothing from the project is part
    of the command. What comes back is read like any contract file, and one that is not this contract, or has
    no check that can be run, is put back as it was. An edit never approves: the question is asked again.
    """
    path = store.path_for(contract_id)
    argv = _editor_argv(os.environ.get("VISUAL") or os.environ.get("EDITOR") or "")
    if not argv:
        term.note(
            console,
            "warn",
            f"No editor is set. Set EDITOR (for example to `code --wait`) and press e again, or answer n and edit {escape(str(path))}.",
        )
        return None
    try:
        was = store.load(contract_id)
        before = path.read_bytes()
        subprocess.run([*argv, str(path)], check=False)
    except (ContractError, OSError) as exc:
        term.note(console, "fail", f"The editor `{escape(argv[0])}` was not used: {escape(str(exc))}. Nothing changed.")
        return None
    problem = ""
    edited: Contract | None = None
    try:
        edited = store.load(contract_id)
    except ContractError as exc:
        problem = f"it is not a valid contract ({str(exc).splitlines()[0]})"
    if edited is not None and edited.id != contract_id:
        problem = f"its id changed from '{contract_id}' to '{edited.id}'"
    elif edited is not None and not any(c.check for c in edited.criteria):
        problem = "it has no check that can be run"
    if problem or edited is None:
        path.write_bytes(before)
        term.note(console, "fail", f"The edit was not kept: {escape(problem)}. The contract was put back as it was.")
        return None
    if edited.content_hash() == was.content_hash():
        console.print("  The editor changed no check.")
        return None
    return edited
