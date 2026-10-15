"""Resolve and run the target application for the duration of a verification."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Literal, Optional

from contexer.appserver.detect import StartPlanError, plan_start
from contexer.appserver.devserver import DevServer, DevServerError
from contexer.config.project import AppSettings, ProjectConfigError, load_project_config
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
    server: Optional[DevServer] = None

    def ensure_running(self) -> str:
        """Bring a crashed dev server back; other kinds are left to their owner."""
        if self.server is not None:
            self.url = self.server.ensure_running()
        return self.url


@contextmanager
def open_app(
    project_dir: str | Path,
    url: Optional[str] = None,
    *,
    repo_context: Optional[RepositoryContext] = None,
    settings: Optional[AppSettings] = None,
    log_path: Optional[Path] = None,
    on_status: Optional[Callable[[str], None]] = None,
) -> Iterator[RunningApp]:
    """Yield a running app; anything Contexer started is stopped on exit.

    Resolution order: an explicit ``url`` (the caller runs the app), a static
    site (served by Contexer), then the project's dev server.
    """
    project = Path(project_dir).resolve()
    context = repo_context or RepositoryInspector().inspect(project)

    if url:
        yield RunningApp(url=url, kind="external", repo_context=context)
        return

    try:
        app_settings = settings or load_project_config(project).app
    except ProjectConfigError as exc:
        raise AppStartError(str(exc)) from exc

    if context.is_static_site and not app_settings.start:
        with StaticAppServer(project) as static:
            yield RunningApp(url=static.url, kind="static", repo_context=context, command="static file server")
        return

    try:
        plan = plan_start(project, app_settings)
    except StartPlanError as exc:
        raise AppStartError(str(exc)) from exc

    server = DevServer(plan, log_path=log_path, on_status=on_status)
    try:
        try:
            ready_url = server.start()
        except DevServerError as exc:
            raise AppStartError(str(exc), exc.log_tail) from exc
        yield RunningApp(
            url=ready_url,
            kind="dev",
            repo_context=context,
            log_tail=server.log_tail,
            command=plan.display,
            server=server,
        )
    finally:
        server.stop()
