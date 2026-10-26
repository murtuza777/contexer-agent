"""``contexer setup`` and ``contexer models``: bring your own key, pick models, prove they answer."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from contexer.config.user import (
    UserSettings,
    contexer_home,
    load_credentials,
    load_user_settings,
    mask,
    save_credential,
    save_user_settings,
)
from contexer.llm.base import LLMProvider
from contexer.llm.catalog import PROVIDERS, ProviderSpec, provider_spec
from contexer.llm.discovery import DiscoveryError, ModelInfo, check_key, list_models, try_model

AGENT_BINARIES = {"claude-code": "claude", "codex": "codex", "opencode": "opencode"}
_SUGGESTIONS = 12


def setup(
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="Provider id (`contexer models --providers`)."),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model that drafts checks from goals."),
    key: Optional[str] = typer.Option(None, "--key", help="API key; leave out to be asked without echo."),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Endpoint for the 'custom' provider, or to override one."),
    agent: Optional[str] = typer.Option(None, "--agent", help="Coding agent for `contexer run`: claude-code, codex or opencode."),
    agent_model: Optional[str] = typer.Option(None, "--agent-model", help="Model for the coding agent (OpenCode: provider/model)."),
    test: bool = typer.Option(True, "--test/--no-test", help="Send one tiny request to prove the model answers."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Take the defaults instead of asking."),
    show: bool = typer.Option(False, "--show", help="Print the saved settings and exit."),
) -> None:
    """Bring your own key: choose a provider and models, test them live, and save them for every project."""
    console = Console()
    if show:
        _show(console)
        return
    try:
        spec = _choose_provider(console, provider, yes)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    url = base_url or spec.base_url
    if not url:
        if yes:
            raise typer.BadParameter(f"the {spec.id} provider needs --base-url")
        url = typer.prompt("Base URL of the OpenAI-compatible API (for example https://gateway.example.com/v1)").strip()

    api_key, pasted = _choose_key(console, spec, key, yes)
    if api_key or not spec.local:
        with console.status(f"[dim]Checking the key with {spec.label}...[/]"):
            try:
                check_key(spec, api_key, url)
            except DiscoveryError as exc:
                console.print(f"[red]✗[/] {escape(str(exc))}")
                raise typer.Exit(code=1) from exc
        console.print(f"[green]✓[/] {escape(spec.label)} accepted the key")

    try:
        available = list_models(spec, api_key, url)
    except DiscoveryError as exc:
        console.print(f"[yellow]![/] Could not list models: {escape(str(exc))}")
        available = []
    chosen = _choose_model(console, spec, model, available, yes)

    if test:
        llm = build_provider(spec, chosen, api_key, url)
        with console.status(f"[dim]Asking {escape(chosen)} for a one-word answer...[/]"):
            ok, detail, seconds = asyncio.run(try_model(llm))
        if not ok:
            console.print(f"[red]✗[/] {escape(chosen)} did not answer: {escape(detail)}")
            console.print("[dim]Nothing was saved. Pick another model, or retry if the provider is rate-limiting.[/]")
            raise typer.Exit(code=1)
        console.print(f"[green]✓[/] {escape(chosen)} answered in {seconds:.1f}s [dim]({escape(detail)})[/]")

    agent_name, agent_choice = _choose_agent(console, spec, chosen, agent, agent_model, yes)
    if pasted and api_key:
        save_credential(spec.key_env, api_key)
        if agent_name == "codex" and spec.id == "openai":
            save_credential("CODEX_API_KEY", api_key)  # `codex exec` reads its API key from here
    saved = UserSettings(
        provider=spec.id,
        model=chosen,
        base_url=url if url != spec.base_url else None,
        agent=agent_name,
        agent_model=agent_choice,
    )
    path = save_user_settings(saved)

    console.print()
    console.print(f"[bold]Saved[/] [dim]{escape(str(path))}[/]")
    console.print(f"  drafting  {escape(spec.label)} · {escape(chosen)}")
    if agent_name:
        console.print(f"  building  {escape(agent_name)}{f' · {escape(agent_choice)}' if agent_choice else ''}")
    else:
        console.print("  building  [yellow]no coding agent installed[/] [dim](npm i -g opencode-ai, then run setup again)[/]")
    if pasted and api_key:
        console.print(f"  key       {escape(spec.key_env)} {escape(mask(api_key))} [dim]in {escape(str(contexer_home()))}, never in a project[/]")
    ensure_browser(console, ask=not yes)
    console.print()
    console.print('[dim]Next:[/] contexer doctor · contexer run "<what must be true>" [dim](in your app\'s folder)[/]')


def ensure_browser(console: Console, ask: bool) -> bool:
    """Every check runs in Chromium; offer to install it now rather than fail at the first check."""
    from contexer.observer.browser import chromium_status

    ok, detail = asyncio.run(chromium_status())
    if ok:
        console.print(f"  browser   {escape(detail)}")
        return True
    console.print(f"  browser   [yellow]{escape(detail)}[/]")
    command = [sys.executable, "-m", "playwright", "install", "chromium"]
    if not ask or not typer.confirm("Install Chromium for Contexer now (about 150 MB)?", default=True):
        console.print("  [dim]Install it later with:[/] python -m playwright install chromium")
        return False
    if subprocess.call(command) != 0:
        console.print("[yellow]Chromium did not install.[/] On Linux it may also need: python -m playwright install-deps chromium")
        return False
    ok, detail = asyncio.run(chromium_status())
    console.print(f"  browser   {'' if ok else '[yellow]'}{escape(detail)}{'' if ok else '[/]'}")
    return ok


def models(
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="Provider id (default: the one you set up)."),
    free: bool = typer.Option(False, "--free", help="Only free models (OpenRouter)."),
    search: Optional[str] = typer.Option(None, "--search", "-s", help="Only models whose id contains this."),
    limit: int = typer.Option(30, "--limit", min=1, help="How many to show."),
    providers: bool = typer.Option(False, "--providers", help="List the providers you can bring a key for."),
) -> None:
    """List a provider's models (or, with --providers, every provider Contexer supports)."""
    console = Console()
    if providers:
        _show_providers(console)
        return
    configured = os.environ.get("CONTEXER_LLM_PROVIDER")
    try:
        spec = provider_spec(provider or configured or "openrouter")
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    paired = spec.id == configured
    url = (os.environ.get("CONTEXER_LLM_BASE_URL") if paired else None) or spec.base_url
    try:
        found = list_models(spec, spec.key(), url)
    except DiscoveryError as exc:
        console.print(f"[red]✗[/] {escape(str(exc))}")
        raise typer.Exit(code=1) from exc
    if free:
        found = [m for m in found if m.free]
    if search:
        found = [m for m in found if search.lower() in m.id.lower()]
    current = os.environ.get("CONTEXER_LLM_MODEL") if paired else None
    _model_table(console, f"{spec.label} models", found[:limit], spec.default_model, current)
    if len(found) > limit:
        console.print(f"[dim]{len(found) - limit} more; narrow with --search or raise --limit.[/]")
    console.print(f"[dim]Use one: contexer setup --provider {spec.id} --model <id>[/]")


# -- choices --------------------------------------------------------------------


def _choose_provider(console: Console, provider: Optional[str], yes: bool) -> ProviderSpec:
    if provider:
        return provider_spec(provider)
    default = next((p for p in PROVIDERS if p.key() and not p.local), provider_spec("openrouter"))
    if yes:
        return default
    _show_providers(console)
    answer = typer.prompt("Provider (number or id)", default=default.id).strip()
    if answer.isdigit() and 1 <= int(answer) <= len(PROVIDERS):
        return PROVIDERS[int(answer) - 1]
    return provider_spec(answer)


def _choose_key(console: Console, spec: ProviderSpec, key: Optional[str], yes: bool) -> tuple[Optional[str], bool]:
    """The key to use, and whether it is new (to be saved)."""
    if key:
        return key.strip(), True
    existing = spec.key()
    if existing:
        if yes or typer.confirm(f"Use the {spec.key_env} already set ({mask(existing)})?", default=True):
            return existing, False
    if spec.local:
        return None, False
    if yes:
        raise typer.BadParameter(f"no {spec.key_env} is set; pass --key or export it")
    where = f" (get one at {spec.keys_url})" if spec.keys_url else ""
    pasted = typer.prompt(f"Paste your {spec.label} API key{where}", hide_input=True).strip()
    return pasted, True


def _choose_model(console: Console, spec: ProviderSpec, model: Optional[str], available: list[ModelInfo], yes: bool) -> str:
    known = {m.id for m in available}
    if model:
        if available and model not in known:
            console.print(f"[yellow]![/] {escape(model)} is not in {escape(spec.label)}'s model list; using it anyway.")
        return model
    suggestions = _suggest(spec, available)
    default = spec.default_model if (not available or spec.default_model in known) else ""
    default = default or (suggestions[0].id if suggestions else "")
    if yes:
        if not default:
            raise typer.BadParameter(f"pass --model; `contexer models --provider {spec.id}` lists them")
        return default
    if suggestions:
        _model_table(console, f"Some {spec.label} models", suggestions, spec.default_model, None)
        console.print(f"[dim]Any id from `contexer models --provider {spec.id}` works.[/]")
    return typer.prompt("Model for drafting checks", default=default or None).strip()


def _choose_agent(
    console: Console,
    spec: ProviderSpec,
    model: str,
    agent: Optional[str],
    agent_model: Optional[str],
    yes: bool,
) -> tuple[Optional[str], Optional[str]]:
    installed = [name for name, binary in AGENT_BINARIES.items() if shutil.which(binary)]
    if agent:
        name: Optional[str] = agent
    else:
        if spec.native_agent in installed:
            recommended: Optional[str] = spec.native_agent
        elif "opencode" in installed and spec.opencode_id:
            recommended = "opencode"
        else:
            recommended = installed[0] if installed else None
        name = recommended
        if installed and not yes:
            answer = typer.prompt(f"Coding agent for `contexer run` ({', '.join(installed)})", default=recommended or installed[0])
            name = answer.strip()
    if name and name not in AGENT_BINARIES:
        raise typer.BadParameter(f"unknown agent '{name}' (choose {', '.join(AGENT_BINARIES)})")
    if name == "opencode" and not agent_model:
        agent_model = spec.opencode_model(model)
        if agent_model is None:
            console.print(f"[yellow]![/] OpenCode has no {escape(spec.label)} provider; pass --agent-model provider/model.")
    return name, agent_model


def _suggest(spec: ProviderSpec, available: list[ModelInfo]) -> list[ModelInfo]:
    if spec.id == "openrouter":
        # Free models that can call tools first (a coding agent needs tools), biggest context first.
        picks = sorted((m for m in available if m.free and m.tools), key=lambda m: -(m.context or 0))
    else:
        picks = list(available)
    default = next((m for m in available if m.id == spec.default_model), None)
    if default is not None:
        picks = [default, *(m for m in picks if m.id != default.id)]
    return picks[:_SUGGESTIONS]


# -- output ---------------------------------------------------------------------


def _show_providers(console: Console) -> None:
    table = Table(show_header=True, header_style="dim", box=None, pad_edge=False)
    for column in ("#", "provider", "id", "key", "notes"):
        table.add_column(column)
    for n, spec in enumerate(PROVIDERS, 1):
        if spec.local:
            status = "[dim]none needed[/]"
        elif spec.key():
            status = f"[green]✓[/] {spec.key_env}"
        else:
            status = f"[dim]{spec.key_env}[/]"
        notes = [spec.note] if spec.note else []
        if spec.native_agent:
            notes.append(f"builds with {spec.native_agent}")
        elif spec.opencode_id:
            notes.append("builds with opencode")
        table.add_row(str(n), spec.label, spec.id, status, escape("; ".join(notes)))
    console.print(table)


def _model_table(console: Console, title: str, rows: list[ModelInfo], default: str, current: Optional[str]) -> None:
    table = Table(title=title, show_header=True, header_style="dim", box=None, pad_edge=False, title_justify="left")
    for column in ("model", "context", "free", "tools", ""):
        table.add_column(column)
    for m in rows:
        marks = []
        if m.id == current:
            marks.append("[green]current[/]")
        if m.id == default:
            marks.append("[cyan]recommended[/]")
        table.add_row(
            escape(m.id),
            f"{m.context:,}" if m.context else "",
            {True: "yes", False: "", None: ""}[m.free],
            {True: "yes", False: "no", None: ""}[m.tools],
            " ".join(marks),
        )
    console.print(table)


def _show(console: Console) -> None:
    settings = load_user_settings()
    home = contexer_home()
    console.print(f"[bold]Contexer settings[/] [dim]{escape(str(home))}[/]")
    if not settings.provider:
        console.print("  Not set up yet: run `contexer setup`.")
    else:
        console.print(f"  drafting  {escape(settings.provider)} · {escape(settings.model or 'default model')}")
        if settings.base_url:
            console.print(f"  endpoint  {escape(settings.base_url)}")
        console.print(f"  building  {escape(settings.agent or 'not chosen')}{f' · {escape(settings.agent_model)}' if settings.agent_model else ''}")
    for name, value in load_credentials().items():
        console.print(f"  key       {escape(name)} {escape(mask(value))}")
    overrides = [n for n in ("CONTEXER_LLM_PROVIDER", "CONTEXER_LLM_MODEL", "CONTEXER_AGENT") if os.environ.get(n)]
    if overrides:
        console.print("[dim]Exported variables and a project's contexer.toml take precedence over these.[/]")


def build_provider(spec: ProviderSpec, model: str, api_key: Optional[str], base_url: str) -> LLMProvider:
    """A provider for ``spec`` using exactly this key, model and endpoint (not whatever the environment says)."""
    from contexer.llm.openrouter import OpenAICompatibleProvider, OpenAIProvider, OpenRouterProvider

    if spec.id == "openrouter":
        return OpenRouterProvider(api_key=api_key, model=model, base_url=base_url)
    if spec.id == "anthropic":
        from contexer.llm.anthropic import AnthropicProvider

        return AnthropicProvider(api_key=api_key, model=model)
    if spec.id == "openai":
        return OpenAIProvider(api_key=api_key, model=model, base_url=base_url)
    return OpenAICompatibleProvider.for_spec(spec, model=model, base_url=base_url, api_key=api_key)
