"""Contexer tool execution framework and standard tool suite."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Optional

from contexer.tools.filesystem import (
    file_exists,
    list_directory,
    read_file,
    search_files,
    write_file,
)
from contexer.tools.git import git_branch, git_diff, git_log, git_status
from contexer.tools.registry import ToolRegistry
from contexer.tools.schemas import (
    ExecuteCommandArgs,
    FileExistsArgs,
    GitBranchArgs,
    GitDiffArgs,
    GitLogArgs,
    GitStatusArgs,
    ListDirectoryArgs,
    ReadFileArgs,
    SearchFilesArgs,
    Tool,
    ToolKind,
    ToolResult,
    WriteFileArgs,
)
from contexer.tools.terminal import execute_command


def create_default_registry(workspace_root: Optional[Path | str] = None) -> ToolRegistry:
    """Instantiate a ToolRegistry pre-populated with standard workspace tools."""
    root = Path(workspace_root) if workspace_root else Path.cwd()
    registry = ToolRegistry()

    # -- Filesystem tools -------------------------------------------------
    registry.register(
        Tool(
            name="list_directory",
            description="List files and directories in the workspace.",
            args_schema=ListDirectoryArgs,
            handler=partial(list_directory, root),
        )
    )
    registry.register(
        Tool(
            name="read_file",
            description="Read the text content of a file in the workspace.",
            args_schema=ReadFileArgs,
            handler=partial(read_file, root),
        )
    )
    registry.register(
        Tool(
            name="write_file",
            description="Write text content to a file in the workspace.",
            args_schema=WriteFileArgs,
            handler=partial(write_file, root),
            kind=ToolKind.WRITE,
        )
    )
    registry.register(
        Tool(
            name="search_files",
            description="Search for keywords or regex patterns in workspace files.",
            args_schema=SearchFilesArgs,
            handler=partial(search_files, root),
        )
    )
    registry.register(
        Tool(
            name="file_exists",
            description="Check whether a path exists in the workspace and identify its type.",
            args_schema=FileExistsArgs,
            handler=partial(file_exists, root),
        )
    )

    # -- Terminal tools ---------------------------------------------------
    registry.register(
        Tool(
            name="execute_command",
            description="Execute a shell command from the workspace root and return output.",
            args_schema=ExecuteCommandArgs,
            handler=partial(execute_command, root),
            kind=ToolKind.SHELL,
        )
    )

    # -- Git read-only tools ----------------------------------------------
    registry.register(
        Tool(
            name="git_status",
            description="Get the repository's git working tree and branch status.",
            args_schema=GitStatusArgs,
            handler=partial(git_status, root),
        )
    )
    registry.register(
        Tool(
            name="git_diff",
            description="Inspect git diff for unstaged or staged changes.",
            args_schema=GitDiffArgs,
            handler=partial(git_diff, root),
        )
    )
    registry.register(
        Tool(
            name="git_log",
            description="View recent git commit history.",
            args_schema=GitLogArgs,
            handler=partial(git_log, root),
        )
    )
    registry.register(
        Tool(
            name="git_branch",
            description="List local and remote git branches.",
            args_schema=GitBranchArgs,
            handler=partial(git_branch, root),
        )
    )

    return registry


__all__ = [
    "ToolRegistry",
    "Tool",
    "ToolKind",
    "ToolResult",
    "create_default_registry",
    "ListDirectoryArgs",
    "ReadFileArgs",
    "WriteFileArgs",
    "SearchFilesArgs",
    "FileExistsArgs",
    "ExecuteCommandArgs",
    "GitStatusArgs",
    "GitDiffArgs",
    "GitLogArgs",
    "GitBranchArgs",
]
