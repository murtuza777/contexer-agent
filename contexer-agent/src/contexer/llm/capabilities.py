"""What one model can do, and how Contexer knows each thing.

The catalog (``catalog.py``) knows providers. This is the record per model: the context window,
whether it calls tools natively, makes several calls in one reply, follows a strict schema and
reads images, and what it costs. Every fact says where it came from:

* ``catalogue``: the provider's own model list says so. OpenRouter publishes all of it; most other
  providers publish an id and nothing else;
* ``measured``: Contexer saw it. Either the model is in the table of models its agents have been
  run on (``catalog.MEASURED_MODELS``), or ``contexer setup`` made one real tool call on this
  machine (``chat.check_tool_calling``) and saved what happened;
* ``assumed``: nobody said. The value is what the agents expect of a model (it calls tools, it can
  make several calls in one reply), or None for a number nobody can guess (the window, a price).

A model Contexer knows nothing about still works: its record is all assumptions, and says so.
Nothing here makes a model request; looking a model up is one read of the provider's model list.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar

from contexer.llm import discovery
from contexer.llm.catalog import MEASURED_MODELS, provider_spec

if TYPE_CHECKING:
    import httpx

Source = Literal["catalogue", "measured", "assumed"]
T = TypeVar("T")
MEASUREMENTS_FILE = "models.json"


@dataclass(frozen=True)
class Fact(Generic[T]):
    """One thing known about a model, and where it came from."""

    value: T
    source: Source = "assumed"
    # Which catalogue, or which measurement.
    detail: str = ""

    def origin(self) -> str:
        return f"{self.source}: {self.detail}" if self.detail else self.source


@dataclass(frozen=True)
class ModelCapabilities:
    provider: str
    model: str
    # Tokens; None when nobody says.
    context_window: Fact[int | None] = Fact(None)
    native_tools: Fact[bool] = Fact(True)
    parallel_tool_calls: Fact[bool] = Fact(True)
    strict_schemas: Fact[bool] = Fact(False)
    vision: Fact[bool] = Fact(False)
    # US dollars per million tokens; None when nobody says.
    input_usd_per_mtok: Fact[float | None] = Fact(None)
    output_usd_per_mtok: Fact[float | None] = Fact(None)
    cached_input_usd_per_mtok: Fact[float | None] = Fact(None)

    def rows(self) -> list[tuple[str, str, str]]:
        """Each capability as (name, value, where it came from), for ``contexer doctor`` and ``contexer setup``."""
        window = self.context_window.value
        return [
            ("Tool calling", _yes_no(self.native_tools.value), self.native_tools.origin()),
            ("Parallel calls", _yes_no(self.parallel_tool_calls.value), self.parallel_tool_calls.origin()),
            ("Strict schemas", _yes_no(self.strict_schemas.value), self.strict_schemas.origin()),
            ("Vision", _yes_no(self.vision.value), self.vision.origin()),
            ("Context window", f"{window:,} tokens" if window else "not known", self.context_window.origin()),
            ("Input price", _price(self.input_usd_per_mtok.value), self.input_usd_per_mtok.origin()),
            ("Output price", _price(self.output_usd_per_mtok.value), self.output_usd_per_mtok.origin()),
            ("Cached input", _price(self.cached_input_usd_per_mtok.value), self.cached_input_usd_per_mtok.origin()),
        ]


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _price(value: float | None) -> str:
    return "not known" if value is None else f"${value:.2f} per million tokens"


def model_capabilities(
    provider: str,
    model: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    transport: httpx.BaseTransport | None = None,
    models: list[discovery.ModelInfo] | None = None,
) -> ModelCapabilities:
    """The record for ``model`` at ``provider``. The strongest source wins: catalogue, then measured, then assumed.

    ``models`` is the provider's model list when the caller already has it; otherwise it is read here.
    A provider that cannot be reached, or does not list the model, adds nothing.
    """
    spec = provider_spec(provider)  # ValueError for an unknown provider
    endpoint = (base_url or spec.endpoint()).rstrip("/")
    record = ModelCapabilities(provider=spec.id, model=model)
    record = _with_measured(record, endpoint)
    if spec.protocol == "anthropic":
        return replace(record, native_tools=Fact(True, "catalogue", "every Claude model on Anthropic's API accepts tools"))
    info = next((m for m in models if m.id == model), None) if models is not None else None
    if models is None:
        info = _catalogue_row(spec.id, model, api_key or spec.key(), endpoint, transport)
    return _with_catalogue(record, info, f"{spec.label}'s model list") if info is not None else record


def _catalogue_row(
    provider: str, model: str, api_key: str | None, base_url: str, transport: httpx.BaseTransport | None = None
) -> discovery.ModelInfo | None:
    """The provider's own row for ``model``, or None. The one place a record reads from the network."""
    try:
        listed = discovery.list_models(provider_spec(provider), api_key, base_url or None, transport)
    except discovery.DiscoveryError:
        return None
    return next((m for m in listed if m.id == model), None)


def _with_catalogue(record: ModelCapabilities, info: discovery.ModelInfo, where: str) -> ModelCapabilities:
    """``record`` with every fact the provider's row states. A field the row leaves out stays as it was."""

    def said(value: Any) -> Fact[Any]:
        return Fact(value, "catalogue", where)

    row = info.raw
    changes: dict[str, Fact[Any]] = {}
    if info.context:
        changes["context_window"] = said(int(info.context))
    if info.tools is not None:
        changes["native_tools"] = said(info.tools)
    parameters = row.get("supported_parameters")
    if isinstance(parameters, list):
        # Listing a parameter says the model takes it. Not listing `parallel_tool_calls` only says the switch
        # is missing, not that the model answers with one call at a time, so that one is never set to "no".
        changes["strict_schemas"] = said("structured_outputs" in parameters)
        if "parallel_tool_calls" in parameters:
            changes["parallel_tool_calls"] = said(True)
    architecture = row.get("architecture")
    kinds = architecture.get("input_modalities") if isinstance(architecture, dict) else None
    if isinstance(kinds, list):
        changes["vision"] = said("image" in kinds)
    pricing = row.get("pricing")
    if isinstance(pricing, dict):
        for name, field_name in (
            ("prompt", "input_usd_per_mtok"),
            ("completion", "output_usd_per_mtok"),
            ("input_cache_read", "cached_input_usd_per_mtok"),
        ):
            price = _per_million(pricing.get(name))
            if price is not None:
                changes[field_name] = said(price)
    return replace(record, **changes)


def _per_million(per_token: Any) -> float | None:
    """A catalogue price (US dollars per token, as text) per million tokens. A router's "-1" is no price."""
    try:
        price = float(per_token)
    except (TypeError, ValueError):
        return None
    return round(price * 1_000_000, 6) if price >= 0 else None


# -- measured ----------------------------------------------------------------------------------------


def _with_measured(record: ModelCapabilities, endpoint: str) -> ModelCapabilities:
    """``record`` with what Contexer saw: the shipped table first, then a measurement saved on this machine."""
    shipped = MEASURED_MODELS.get(record.model.lower())
    if shipped is not None:
        if shipped.native_tools is not None:
            record = replace(record, native_tools=Fact(shipped.native_tools, "measured", shipped.where))
        if shipped.parallel_tool_calls is not None:
            record = replace(record, parallel_tool_calls=Fact(shipped.parallel_tool_calls, "measured", shipped.where))
    saved = _load_measurements().get(_measurement_key(record.provider, endpoint, record.model))
    if isinstance(saved, dict) and isinstance(saved.get("native_tools"), bool):
        where = f"one tool call by `contexer setup` on {saved.get('on') or 'this machine'}"
        record = replace(record, native_tools=Fact(saved["native_tools"], "measured", where))
    return record


def save_measurement(provider: str, base_url: str, model: str, *, native_tools: bool) -> None:
    """Keep what one real tool call showed, beside the settings ``contexer setup`` saves (never in a project)."""
    from contexer.config.user import home_dir

    measurements = _load_measurements()
    measurements[_measurement_key(provider, base_url.rstrip("/"), model)] = {
        "native_tools": native_tools,
        "on": date.today().isoformat(),
    }
    # `contexer setup` saves this before it saves a key, so this call is often the one that creates the folder.
    (home_dir() / MEASUREMENTS_FILE).write_text(json.dumps(measurements, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_measurements() -> dict[str, Any]:
    from contexer.config.user import contexer_home

    try:
        data = json.loads((contexer_home() / MEASUREMENTS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _measurement_key(provider: str, endpoint: str, model: str) -> str:
    return f"{provider}|{endpoint}|{model}"


# -- the record of a chat model that was built ---------------------------------------------------------

# Records by (model id, endpoint), kept when `contexer.cli.test_cli.build_model` builds a chat model.
_BUILT: dict[tuple[str, str], ModelCapabilities] = {}


def remember(record: ModelCapabilities, base_url: str) -> None:
    _BUILT[(record.model, base_url.rstrip("/"))] = record


def capabilities_of(model: Any) -> ModelCapabilities:
    """The record of a chat model an agent is about to run on (``crew/base.py`` can ask this of its model).

    A model that was not built through ``build_model`` (a test's scripted model, say) gets the record
    of a model nothing is known about.
    """
    inner = getattr(model, "bound", model)
    name = getattr(inner, "model_name", None) or getattr(inner, "model", None)
    name = name if isinstance(name, str) else type(inner).__name__
    endpoint = str(getattr(inner, "openai_api_base", "") or "").rstrip("/")
    exact = _BUILT.get((name, endpoint))
    if exact is not None:
        return exact
    same_name = [record for (known, _endpoint), record in _BUILT.items() if known == name]
    return same_name[0] if len(same_name) == 1 else ModelCapabilities(provider="", model=name)
