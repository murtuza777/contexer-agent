"""Interactive command safety classifier and tool approval management.

Adapted from AgentForge (MIT License, Copyright (c) 2026 Mohit Goyal).
Categorizes commands as safe, dangerous, or mutating, and manages user confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import inspect
import re
from typing import Any, Awaitable, Callable, Optional, Union
from contexer.tools.base import ToolConfirmation


class ApprovalDecision(str, Enum):
    """The decision reached for a tool execution request."""

    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CONFIRMATION = "needs_confirmation"


class ApprovalPolicy(str, Enum):
    """Policy governing whether tool executions require interactive confirmation."""

    AUTO = "auto"              # Auto-approves safe commands and standard safe file edits
    AUTO_EDIT = "auto_edit"    # Auto-approves file writes, asks confirmation for shell commands
    NEVER = "never"            # Rejects unapproved mutating actions; allows only known-safe commands
    YOLO = "yolo"              # Approves all commands without prompting (unattended mode)


@dataclass
class ApprovalContext:
    """Context details evaluated during tool confirmation."""

    tool_name: str
    params: dict[str, Any]
    is_mutating: bool
    affected_paths: list[Path] = field(default_factory=list)
    command: Optional[str] = None
    is_dangerous: bool = False


# Commands known to cause system-wide destruction or severe harm
DANGEROUS_PATTERNS = [
    # Filesystem destruction
    r"rm\s+(-rf?|--recursive)\s+[/~]",
    r"rm\s+-rf?\s+\*",
    r"rmdir\s+[/~]",
    # Raw disk writes
    r"dd\s+if=",
    r"mkfs",
    r"fdisk",
    r"parted",
    # System power state
    r"shutdown",
    r"reboot",
    r"halt",
    r"poweroff",
    r"init\s+[06]",
    # Dangerous permission alterations
    r"chmod\s+(-R\s+)?777\s+[/~]",
    r"chown\s+-R\s+.*\s+[/~]",
    # Network listener/exposure
    r"nc\s+-l",
    r"netcat\s+-l",
    # Remote script piping to shell
    r"curl\s+.*\|\s*(bash|sh)",
    r"wget\s+.*\|\s*(bash|sh)",
    # Fork bomb
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;",
]

# Commands known to be purely informational and safe for auto-approval
SAFE_PATTERNS = [
    # Directory & file queries
    r"^(ls|dir|pwd|echo|cat|head|tail|less|more|wc)(\s|$)",
    r"^(find|locate|which|whereis|file|stat)(\s|$)",
    # Read-only Git inspection
    r"^git\s+(status|log|diff|show|branch|remote|tag)(\s|$)",
    # Language & dependency queries
    r"^(npm|yarn|pnpm)\s+(list|ls|outdated)(\s|$)",
    r"^pip\s+(list|show|freeze)(\s|$)",
    r"^cargo\s+(tree|search)(\s|$)",
    # Text search & formatting
    r"^(grep|rg|awk|sed|cut|sort|uniq|tr|diff|comm)(\s|$)",
    # Environment & diagnostics
    r"^(date|cal|uptime|whoami|id|groups|hostname|uname)(\s|$)",
    r"^(env|printenv|set)$",
    r"^(ps|top|htop|pgrep)(\s|$)",
    r'^(?:"[^"]*"|\S+)?(?:\b(?:python\d*|node|cargo|go|rustc)(?:\.exe)?"?)\s+(--version|-v)(\s|$)',
    r'^(?:(?:"[^"]*"|\S+)\s+-m\s+pytest|pytest(?:\.exe)?)(\s|$)',
]


def is_dangerous_command(command: str) -> bool:
    """Return True if command matches known destructive system patterns."""
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return True
    return False


def is_safe_command(command: str) -> bool:
    """Return True if command matches recognized safe inspection patterns."""
    clean = command.strip()
    for pattern in SAFE_PATTERNS:
        if re.search(pattern, clean, re.IGNORECASE):
            return True
    return False


class ApprovalManager:
    """Evaluates tool execution requests against configured approval policies."""

    def __init__(
        self,
        policy: ApprovalPolicy | str = ApprovalPolicy.AUTO,
        workspace_root: Optional[Path] = None,
        confirmation_callback: Optional[Callable[[Any], Awaitable[bool]]] = None,
    ) -> None:
        if isinstance(policy, str):
            clean_policy = policy.lower().replace("-", "_")
            try:
                self.policy = ApprovalPolicy(clean_policy)
            except ValueError:
                self.policy = ApprovalPolicy.AUTO
        else:
            self.policy = policy
        self.workspace_root = workspace_root or Path.cwd()
        self.confirmation_callback = confirmation_callback

    def assess_command_safety(self, command: str) -> ApprovalDecision:
        """Evaluate a shell command against danger patterns and policy."""
        if self.policy == ApprovalPolicy.YOLO:
            return ApprovalDecision.APPROVED

        if is_dangerous_command(command):
            return ApprovalDecision.REJECTED

        if self.policy == ApprovalPolicy.NEVER:
            if is_safe_command(command):
                return ApprovalDecision.APPROVED
            return ApprovalDecision.REJECTED

        if self.policy in (ApprovalPolicy.AUTO, ApprovalPolicy.AUTO_EDIT):
            if is_safe_command(command):
                return ApprovalDecision.APPROVED
            return ApprovalDecision.NEEDS_CONFIRMATION

        return ApprovalDecision.NEEDS_CONFIRMATION

    def assess_tool_safety(
        self,
        tool_name: str,
        params: dict[str, Any],
        is_mutating: bool,
    ) -> ApprovalDecision:
        """Evaluate tool execution safety."""
        if not is_mutating or self.policy == ApprovalPolicy.YOLO:
            return ApprovalDecision.APPROVED

        if tool_name in ("execute_command", "shell"):
            cmd = str(params.get("command", ""))
            return self.assess_command_safety(cmd)

        if self.policy == ApprovalPolicy.AUTO:
            return ApprovalDecision.APPROVED

        if self.policy == ApprovalPolicy.NEVER:
            return ApprovalDecision.REJECTED

        return ApprovalDecision.NEEDS_CONFIRMATION

    def decide(
        self,
        is_mutating: bool,
        confirmation: ToolConfirmation | ApprovalContext,
    ) -> ApprovalDecision:
        """Evaluate whether a tool invocation is approved, rejected, or needs confirmation."""
        if not is_mutating or self.policy == ApprovalPolicy.YOLO:
            return ApprovalDecision.APPROVED

        if confirmation.command:
            return self.assess_command_safety(confirmation.command)

        if confirmation.is_dangerous:
            return ApprovalDecision.NEEDS_CONFIRMATION

        # Check path boundary containment if paths are specified
        paths = getattr(confirmation, "affected_paths", ())
        ws_root = self.workspace_root.resolve()
        for p in paths:
            resolved = (p if p.is_absolute() else (self.workspace_root / p)).resolve()
            if not resolved.is_relative_to(ws_root):
                return ApprovalDecision.NEEDS_CONFIRMATION

        if self.policy in (ApprovalPolicy.AUTO, ApprovalPolicy.AUTO_EDIT):
            return ApprovalDecision.APPROVED

        if self.policy == ApprovalPolicy.NEVER:
            return ApprovalDecision.REJECTED

        return ApprovalDecision.NEEDS_CONFIRMATION

    def check_approval(self, context: ApprovalContext | ToolConfirmation) -> ApprovalDecision:
        """Alias for decide matching AgentForge API."""
        is_mutating = getattr(context, "is_mutating", True)
        return self.decide(is_mutating=is_mutating, confirmation=context)

    async def request_confirmation(self, confirmation: ToolConfirmation | ApprovalContext) -> bool:
        """Prompt user or execute confirmation callback for unapproved mutating tool."""
        if self.confirmation_callback:
            res = self.confirmation_callback(confirmation)
            if inspect.isawaitable(res):
                return bool(await res)
            return bool(res)

        # Interactive terminal fallback
        try:
            from rich.console import Console

            console = Console()
            console.print("\n[bold yellow]⚠ Approval Required[/bold yellow]")
            console.print(f"  Tool: [bold]{confirmation.tool_name}[/bold]")
            desc = getattr(confirmation, "description", None)
            if desc:
                console.print(f"  {desc}")
            if hasattr(confirmation, "affected_paths") and confirmation.affected_paths:
                for p in confirmation.affected_paths:
                    console.print(f"  Path: {p}")
            diff_func = getattr(confirmation, "get_diff_text", None)
            if callable(diff_func):
                diff_text = diff_func()
                if diff_text:
                    console.print(diff_text)
            response = console.input("\n[bold]Approve? (y/n): [/bold]").strip().lower()
            return response in ("y", "yes")
        except Exception:
            return not getattr(confirmation, "is_dangerous", False)

    async def request_approval(self, context: ApprovalContext | ToolConfirmation) -> bool:
        """Backwards-compatible alias for request_confirmation."""
        return await self.request_confirmation(context)
