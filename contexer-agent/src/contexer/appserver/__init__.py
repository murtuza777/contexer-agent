"""Getting the target application running so it can be verified.

``open_app`` resolves, in order: an explicit URL (the caller runs the app),
a static site (served by Contexer), or a dev server Contexer starts itself.
"""

from contexer.appserver.app import AppStartError, RunningApp, open_app

__all__ = ["AppStartError", "RunningApp", "open_app"]
