"""Resolve and run the target application for the duration of a verification."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Literal, Optional

from contexer.workflow.app_server import StaticAppServer
from contexer.workflow.inspector import RepositoryContext, RepositoryInspector

AppKind = Literal["external", "static", "dev"]


class AppStartError(Exception):
    """The application could not be started or reached."""

    def __init__(self, message: str, log_tail: str = "") -> None:
        super().__init__(message)
        self.log_tail = log_tail


@dataclass
class RunningApp:
    url: str
    kind: AppKind
    repo_context: Optional[RepositoryContext] = None
    log_tail: Callable[[], str] = field(default=lambda: "")
    command: str = ""


@contextmanager
def open_app(
    project_dir: str | Path,
    url: Optional[str] = None,
    *,
    repo_context: Optional[RepositoryContext] = None,
) -> Iterator[RunningApp]:
    """Yield a running app; anything Contexer started is stopped on exit."""
    project = Path(project_dir).resolve()
    context = repo_context or RepositoryInspector().inspect(project)

    if url:
        yield RunningApp(url=url, kind="external", repo_context=context)
        return

    if context.is_static_site:
        with StaticAppServer(project) as server:
            yield RunningApp(url=server.url, kind="static", repo_context=context, command="static file server")
        return

    raise AppStartError(
        f"'{project.name}' ({context.framework}) needs a dev server. Start it yourself and pass --url, "
        "or let Contexer start it (dev-server support)."
    )
