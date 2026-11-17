"""Browser tools: how an agent uses the app like a person does.

One Chromium page, opened on the running app with the project's signed-in
state. The tools are the verbs of the check language (``verification/checks.py``)
and act through the same code that replays checks (:class:`CheckRunner`), so
what the agent did while exploring is exactly what a replay will do.

Rules the tools keep:

* a target is validated by the ``Locator`` model: the model cannot invent a
  selector form the runner does not support;
* a tool never raises. A target that matches nothing, an invalid argument or a
  closed browser comes back as text starting with ``Error:``, with the page's
  current snapshot where that helps;
* the browser stays on the app under test. A ``goto`` to another origin is
  refused, an action that leaves the origin is undone and not recorded, and
  pop-ups are closed: a steered model cannot operate another site;
* only actions that happened are recorded. When an action fails after it may
  have changed the page (a slow machine can time out an action that landed),
  the recording is marked unreliable until the next ``reset``, and no finding
  can be built on it;
* what is typed into a password field is masked in everything the model reads.

Page content is data. Nothing a page says is an instruction to Contexer.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal, Mapping, Optional, cast

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from contexer.browser.recorder import Recorder
from contexer.observer.playwright import capture_ui_snapshot, record_console_error
from contexer.verification.checks import (
    MASK,
    Check,
    Expectation,
    ExpectationOutcome,
    Locator,
    MissingSecretError,
    Step,
    StepAction,
    expand_secrets,
    redact,
)
from contexer.verification.runner import CheckRunner, _any_visible, _describe_failed_action, _locate, _short

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright

SCREENS_DIR = "screens"
CLOSE_TIMEOUT_SECONDS = 5.0
# After Ctrl+C the close cannot finish (see BrowserSession.close), so it is not waited for long.
INTERRUPTED_CLOSE_TIMEOUT_SECONDS = 1.0
_MAX_ERRORS_SHOWN = 15
_IGNORED_REQUESTS = ("/favicon.ico",)

ResetCommand = Callable[[], Awaitable[Optional[str]]]


class Target(BaseModel):
    """How to find an element. Use exactly one of role, text, label, placeholder, test_id, css."""

    model_config = ConfigDict(extra="allow")

    role: Optional[str] = Field(None, description='ARIA role from the snapshot, e.g. "button". Add `name`.')
    name: Optional[str] = Field(None, description="Accessible name; only together with `role`.")
    text: Optional[str] = Field(None, description="Visible text of the element.")
    label: Optional[str] = Field(None, description="Label of a form field.")
    placeholder: Optional[str] = Field(None, description="Placeholder of a form field.")
    test_id: Optional[str] = Field(None, description="The element's data-testid.")
    css: Optional[str] = Field(None, description="A CSS selector. Last resort.")


# A model that sends a target as text gets an error it can act on, not a schema dump.
TargetArg = Target | str


class _OnTarget(BaseModel):
    target: TargetArg


class _WithValue(BaseModel):
    target: TargetArg
    value: str = Field(description="The text to type, or the option to choose.")


class _Press(BaseModel):
    key: str = Field(description='A key, e.g. "Enter", "Escape", "Tab".')
    target: Optional[TargetArg] = Field(None, description="The element to press it on; leave out for the page.")


class _Goto(BaseModel):
    path: str = Field(description='A path in the app, e.g. "/settings".')


class _Expect(BaseModel):
    kind: Literal[
        "visible", "hidden", "checked", "unchecked", "count", "text", "value", "attribute", "css", "url", "title", "no_errors"
    ] = Field(description="What to check.")  # fmt: skip
    target: Optional[TargetArg] = Field(None, description="The element; not needed for url, title, no_errors.")
    equals: Optional[str] = Field(None, description="Exact value, after whitespace is normalised.")
    contains: Optional[str] = Field(None, description="Substring, case-insensitive.")
    matches: Optional[str] = Field(None, description="Regular expression.")
    changed: Optional[bool] = None
    attribute: Optional[str] = Field(None, description="Attribute name, for kind=attribute.")
    property: Optional[str] = Field(None, description="CSS property, for kind=css.")
    min: Optional[int] = Field(None, description="For kind=count.")
    max: Optional[int] = Field(None, description="For kind=count.")


class _Reset(BaseModel):
    signed_out: bool = Field(False, description="True to continue as a visitor who is not signed in.")


class _NoArgs(BaseModel):
    pass


class BrowserSession:
    """One page on the running app, operated through tools and recorded as it goes."""

    def __init__(
        self,
        url: str,
        *,
        run_dir: Optional[Path] = None,
        storage_state: Optional[dict[str, Any]] = None,
        reset: Optional[ResetCommand] = None,
        headless: bool = True,
        timeout_scale: float = 1.0,
    ) -> None:
        self.url = url
        self._origin = _origin(url)
        # The last address inside the app, to return to when an action leaves it.
        self._home = url
        self.run_dir = Path(run_dir) if run_dir is not None else None
        self.storage_state = storage_state
        self.reset_command = reset
        self.recorder = Recorder()
        # Values typed into password fields. The caller masks them wherever text is kept.
        self.secrets: list[str] = []
        self.closed = False
        self._runner = CheckRunner(headless=headless)
        self._runner.navigation_timeout *= timeout_scale
        self._runner.action_timeout *= timeout_scale
        self._runner.expect_timeout *= timeout_scale
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._page_errors: list[str] = []
        self._console_errors: list[str] = []
        self._failed_requests: list[str] = []
        self._screens = 0

    # -- lifecycle ------------------------------------------------------------

    async def __aenter__(self) -> BrowserSession:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.launch(headless=self._runner.headless)
            await self._open_page(signed_in=self.storage_state is not None)
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        """Close the page, the browser and Playwright. Safe to call twice, and it never hangs.

        On Ctrl+C asyncio cancels Playwright's own tasks together with ours, and a
        close then waits for an answer that will not come. The wait is bounded and
        the close is left behind; when the event loop ends, Playwright's driver
        exits and takes Chromium with it.
        """
        self.closed = True
        closers = [c for c in (self._context, self._browser) if c is not None]
        playwright = self._playwright
        self._page = self._context = self._browser = self._playwright = None

        async def close_all() -> None:
            for closer in closers:
                try:
                    await closer.close()
                except Exception:
                    pass
            if playwright is not None:
                try:
                    await playwright.stop()
                except Exception:
                    pass

        # Not wait_for: it cancels on timeout, and Playwright answers a cancel by waiting again.
        closing = asyncio.ensure_future(close_all())
        closing.add_done_callback(lambda task: task.cancelled() or task.exception())
        task = asyncio.current_task()
        interrupted = task is not None and task.cancelling() > 0
        await asyncio.wait({closing}, timeout=INTERRUPTED_CLOSE_TIMEOUT_SECONDS if interrupted else CLOSE_TIMEOUT_SECONDS)

    async def _open_page(self, signed_in: bool) -> None:
        assert self._browser is not None
        if self._context is not None:
            await self._context.close()
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=True,
            storage_state=cast(Any, self.storage_state) if signed_in else None,
        )
        self._page_errors, self._console_errors, self._failed_requests = [], [], []
        page = await self._context.new_page()
        page.on("pageerror", lambda exc: self._page_errors.append(str(exc)))
        page.on("console", lambda msg: record_console_error(msg, self._console_errors))
        page.on("requestfailed", lambda request: self._note_request(request.url, request.failure or "failed"))
        page.on("response", lambda response: self._note_request(response.url, response.status))
        # A pop-up is a page the agent cannot see or steer; one to another origin is somewhere it must not act.
        self._context.on("page", lambda popup: asyncio.ensure_future(self._close_popup(popup)))
        self._page = page
        await page.goto(self.url, wait_until="load", timeout=self._runner.navigation_timeout * 1000)

    def _note_request(self, url: str, problem: Any) -> None:
        if isinstance(problem, int) and problem < 400:
            return
        if url.endswith(_IGNORED_REQUESTS):
            return
        self._failed_requests.append(f"{problem} {url}")

    # -- the tools ------------------------------------------------------------

    async def snapshot(self) -> str:
        """The page as roles, names, test ids and placeholders."""
        page = self._page
        if page is None:
            return _closed()
        if not self._on_app(page.url) and page.url != "about:blank":  # a late redirect took it elsewhere
            return await self._brought_back(page)
        return self._mask(f"Page: {page.url}\n{await capture_ui_snapshot(page)}")

    async def act(self, action: StepAction, target: Any = None, value: Optional[str] = None) -> str:
        """Perform one step of the check language, and record it if it happened."""
        page = self._page
        if page is None:
            return _closed()
        if isinstance(target, str):
            return _TARGET_HELP
        try:
            step = Step.model_validate({"action": action, "target": _plain(target), "value": value})
        except ValidationError as exc:
            return f"Error: {_problem(exc)}. {_TARGET_EXAMPLES}"
        if action == "goto" and not self._on_app(urljoin(self.url, step.value or "")):
            return (
                f"Error: '{step.value}' is outside the app under test ({self._origin_text()}). "
                "Only the app's own paths can be opened. Nothing was done."
            )
        try:
            await self._runner._perform(page, step, self.url)
        except Exception as exc:
            return await self._brought_back(page) or await self._action_failed(page, step, exc)
        left = await self._brought_back(page)
        if left:
            return left
        if action == "fill" and step.target is not None and value and await self._is_password(page, step.target):
            self.secrets.append(value)
        self.recorder.add_step(step)
        return self._mask(f"ok: {step.describe()}")

    async def expect(self, **fields: Any) -> str:
        """Evaluate one expectation now, and record what was observed."""
        page = self._page
        if page is None:
            return _closed()
        if not self._on_app(page.url) and page.url != "about:blank":
            return await self._brought_back(page)
        if fields.get("changed") is not None:
            return "Error: `changed` compares with a value from before the steps, which a live check does not have. Use equals, contains or matches."
        if isinstance(fields.get("target"), str):
            return _TARGET_HELP
        if isinstance(fields.get("target"), (dict, BaseModel)):
            fields["target"] = _plain(fields["target"])
        if fields.get("kind") == "count" and fields.get("equals") is not None and fields.get("min") is None and fields.get("max") is None:
            # "count equals 2" is what models write; the check language says min and max.
            try:
                fields["min"] = fields["max"] = int(str(fields.pop("equals")).strip())
            except ValueError:
                return "Error: a count needs a whole number: use min and max, or equals with a number."
        try:
            expectation = Expectation.model_validate({k: v for k, v in fields.items() if v is not None})
        except ValidationError as exc:
            return f"Error: {_problem(exc)}"
        if expectation.kind == "no_errors":
            errors = self._page_errors + self._console_errors
            outcome = ExpectationOutcome(
                description=expectation.describe(),
                passed=not errors,
                actual="; ".join(errors[:3]) if errors else "no errors",
            )
        else:
            outcome = await self._runner._evaluate(page, expectation, None)
        crashed = expectation.kind == "no_errors" and not outcome.passed and bool(self._page_errors)
        observation = self.recorder.add_observation(expectation, outcome.passed, outcome.actual, crashed)
        if outcome.passed:
            return self._mask(f"{observation.id} PASS: {outcome.description} (saw {outcome.actual})")
        return self._mask(f"{observation.id} FAIL: expected {outcome.description}, but saw {outcome.actual}")

    async def read_errors(self) -> str:
        """Uncaught exceptions, console errors and failed network requests since the page was fresh."""
        if self._page is None:
            return _closed()
        lines = [f"uncaught exception: {e}" for e in self._page_errors]
        lines += [f"console {e}" for e in self._console_errors]
        lines += [f"request failed: {r}" for r in self._failed_requests]
        if not lines:
            return "No errors: no uncaught exception, console error or failed request."
        more = f"\n... and {len(lines) - _MAX_ERRORS_SHOWN} more" if len(lines) > _MAX_ERRORS_SHOWN else ""
        return self._mask("\n".join(lines[:_MAX_ERRORS_SHOWN]) + more)

    async def screenshot(self) -> str:
        """Save a JPEG of the page in the run folder."""
        page = self._page
        if page is None:
            return _closed()
        if self.run_dir is None:
            return "Error: there is no run folder to save a screenshot in."
        self._screens += 1
        path = self.run_dir / SCREENS_DIR / f"{self._screens:02d}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            await page.screenshot(path=str(path), type="jpeg", quality=70, timeout=5000)
        except Exception as exc:
            return f"Error: the screenshot failed: {_short(exc)}"
        return f"ok: saved {SCREENS_DIR}/{path.name} for the report. You cannot see it; use snapshot to read the page."

    async def reset(self, signed_out: bool = False) -> str:
        """A fresh page (and the project's reset command, if it has one). Starts a new recording."""
        if self._browser is None:
            return _closed()
        if self.reset_command is not None:
            problem = await self.reset_command()
            if problem:
                return f"Error: the app's reset command failed: {problem}. The page was left as it is."
        try:
            await self._open_page(signed_in=self.storage_state is not None and not signed_out)
        except Exception as exc:
            return f"Error: the app did not load again: {_short(exc)}"
        self.recorder.start_over(login=False if signed_out else None)
        who = "signed out" if signed_out else ("signed in" if self.storage_state is not None else "a new visitor")
        # The page comes with the answer: a model that has to ask for it spends a step on every reset.
        return f"ok: a fresh page at the start of the app, {who}. Earlier steps no longer apply.\n{await self.snapshot()}"

    def tools(self) -> list[BaseTool]:
        """The tools, in the order a model is shown them."""

        def on_target(action: StepAction, does: str) -> BaseTool:
            async def run(target: Target) -> str:
                return await self.act(action, target)

            return StructuredTool.from_function(coroutine=run, name=action, description=does, args_schema=_OnTarget)

        def with_value(action: StepAction, does: str) -> BaseTool:
            async def run(target: Target, value: str) -> str:
                return await self.act(action, target, value)

            return StructuredTool.from_function(coroutine=run, name=action, description=does, args_schema=_WithValue)

        async def snapshot() -> str:
            return await self.snapshot()

        async def press(key: str, target: Optional[Target] = None) -> str:
            return await self.act("press", target, key)

        async def goto(path: str) -> str:
            return await self.act("goto", None, path)

        async def read_errors() -> str:
            return await self.read_errors()

        async def screenshot() -> str:
            return await self.screenshot()

        async def expect(**fields: Any) -> str:
            return await self.expect(**fields)

        async def reset(signed_out: bool = False) -> str:
            return await self.reset(signed_out)

        def make(run: Any, name: str, does: str, schema: type[BaseModel]) -> BaseTool:
            return StructuredTool.from_function(coroutine=run, name=name, description=does, args_schema=schema)

        return [
            make(snapshot, "snapshot", "Read the current page: every element with its role, name, test id and placeholder. Call it before acting and after anything that changes the page.", _NoArgs),
            on_target("click", "Click an element."),
            with_value("fill", "Type into a text field, replacing what is there."),
            make(press, "press", "Press a key, on an element or on the page.", _Press),
            with_value("select", "Choose an option in a select box."),
            on_target("check", "Tick a checkbox or radio button."),
            on_target("uncheck", "Untick a checkbox."),
            on_target("hover", "Move the mouse over an element."),
            make(goto, "goto", "Open a path of the app. Reloading the current path is how you test that data survives a reload.", _Goto),
            make(read_errors, "read_errors", "List uncaught exceptions, console errors and failed network requests since the page was fresh.", _NoArgs),
            make(screenshot, "screenshot", "Save a picture of the page for the report.", _NoArgs),
            make(expect, "expect", "Check one thing about the page right now and get PASS or FAIL with what was actually there. The result has an id (e1, e2, ...) that a finding refers to.", _Expect),
            make(reset, "reset", "Start again from a fresh page with the app's data reset. Do this before testing a new behaviour, so its steps start from a known state. It returns the fresh page, so no snapshot is needed after it.", _Reset),
        ]  # fmt: skip

    # -- helpers --------------------------------------------------------------

    async def _action_failed(self, page: Page, step: Step, exc: Exception) -> str:
        if step.target is None:
            return self._mask(f"Error: could not {step.describe()}: {_short(exc)}")
        try:
            target = _locate(page, step.target)
            if not await _any_visible(target, await target.count()):
                ui = await capture_ui_snapshot(page)
                return self._mask(
                    f"Error: {step.target.describe()} matches nothing visible on the page. "
                    f"Nothing was done. The page has:\n{ui}"
                )
            if await self._fill_landed(target, step):
                # The text is in the field: the action happened and only its confirmation was late.
                if step.value and await self._is_password(page, step.target):
                    self.secrets.append(step.value)
                self.recorder.add_step(step)
                return self._mask(f"ok: {step.describe()}")
            actual = await _describe_failed_action(target, step, exc)
        except Exception as inner:
            actual = _short(inner)
        # The target was there, so the action may have changed the page before it failed.
        self.recorder.tainted = True
        return self._mask(
            f"Error: could not {step.describe()}: {actual}. It was not recorded, and the page may have changed "
            "anyway. Call reset and repeat the steps before you rely on what you see."
        )

    async def _fill_landed(self, target: Any, step: Step) -> bool:
        if step.action != "fill" or step.value is None:
            return False
        try:
            return await target.first.input_value(timeout=1000) == step.value
        except Exception:
            return False

    def _on_app(self, url: str) -> bool:
        return urlparse(url).scheme in ("http", "https") and _origin(url) == self._origin

    def _origin_text(self) -> str:
        scheme, host, port = self._origin
        return f"{scheme}://{host}:{port}"

    async def _brought_back(self, page: Page) -> str:
        """If the page has left the app, return it and say so; '' while it is still on the app.

        A link, a redirect or a script can navigate anywhere. Whatever is there is not the app under
        test, so the agent gets no chance to read or operate it.
        """
        try:
            await page.wait_for_timeout(120)  # a navigation started by a script shows up a moment later
            await page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass
        here = page.url
        if self._on_app(here) or here == "about:blank":
            if self._on_app(here):
                self._home = here
            return ""
        try:
            await page.goto(self._home, wait_until="load", timeout=self._runner.navigation_timeout * 1000)
        except Exception:
            try:
                await page.goto(self.url, wait_until="load", timeout=self._runner.navigation_timeout * 1000)
            except Exception:
                pass
        self.recorder.tainted = True
        return self._mask(
            f"Error: that action left the app under test (it went to {here}). The page was brought back and the "
            "step was not recorded. Only the app itself can be tested; call reset before you rely on what you see."
        )

    async def _close_popup(self, popup: Any) -> None:
        if popup is self._page:
            return
        try:
            await popup.close()
        except Exception:
            pass

    async def _is_password(self, page: Page, locator: Locator) -> bool:
        try:
            kind = await _locate(page, locator).first.get_attribute("type", timeout=500)
        except Exception:
            return False
        return (kind or "").lower() == "password"

    def _mask(self, text: str) -> str:
        return redact(text, self.secrets) if self.secrets else text


_SECRET_FIELD = re.compile(r"pass|secret|token|otp|pin\b|one.?time|code\b|pwd", re.IGNORECASE)
_SECRET_NAME = re.compile(r"PASS|SECRET|TOKEN|KEY|PWD|OTP")
_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def credential_secrets(flow: Check, env: Optional[Mapping[str, str]] = None) -> list[str]:
    """The values of a sign-in flow that must be masked from an agent: passwords and codes, not identities.

    A report or a repair prompt masks everything a sign-in types. An agent that tests the app must not
    lose the email or the user name that way: a page that greets the member by email instead of by
    name is a bug it has to be able to see. So a value is a secret here only when its field looks like
    one (password, token, one-time code) or it comes from a ``${NAME}`` whose name does.
    """
    values: list[str] = []
    for step in flow.steps:
        if step.action != "fill" or not step.value:
            continue
        field = " ".join(str(v) for v in step.target.model_dump(exclude_none=True).values()) if step.target else ""
        names = _REFERENCE.findall(step.value)
        if not (_SECRET_FIELD.search(field) or any(_SECRET_NAME.search(name) for name in names)):
            continue
        try:
            values.append(expand_secrets(step.value, dict(os.environ if env is None else env)))
        except MissingSecretError:
            continue  # never typed, so it cannot appear anywhere
    return values


def _origin(url: str) -> tuple[str, str, int]:
    """Scheme, host and port: what makes two addresses the same site."""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    try:
        port = parsed.port
    except ValueError:
        port = None
    return scheme, (parsed.hostname or "").lower(), port or (443 if scheme == "https" else 80)


def _plain(target: Any) -> Any:
    """A target as a plain dict, whether it came as a model or as a model's raw arguments."""
    if isinstance(target, BaseModel):
        return target.model_dump(exclude_none=True)
    return target


def _problem(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors()[:4]:
        where = ".".join(str(p) for p in error["loc"])
        message = error["msg"].removeprefix("Value error, ")
        parts.append(f"{where}: {message}" if where else message)
    return "; ".join(parts)


_TARGET_EXAMPLES = (
    'A target is an object with one way to find the element, for example '
    '{"role": "button", "name": "Add"}, {"placeholder": "Email"}, {"text": "Sign out"} '
    'or {"test_id": "total"}.'
)
_TARGET_HELP = f"Error: the target was sent as text. {_TARGET_EXAMPLES}"


def _closed() -> str:
    return "Error: the browser is closed."


__all__ = ["MASK", "BrowserSession", "Target", "credential_secrets"]
