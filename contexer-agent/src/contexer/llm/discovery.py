"""Asking a provider what it offers: its models, whether a key works, whether a model answers.

``contexer setup`` and ``contexer models`` use these so a user picks a model
that exists, with a key that works, before any run depends on them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from contexer.llm.catalog import ProviderSpec

ANTHROPIC_VERSION = "2023-06-01"


class DiscoveryError(Exception):
    """The provider could not be reached, or refused the key."""


@dataclass
class ModelInfo:
    id: str
    context: Optional[int] = None
    free: Optional[bool] = None
    tools: Optional[bool] = None
    created: Optional[int] = None


def _headers(spec: ProviderSpec, api_key: Optional[str]) -> dict[str, str]:
    if not api_key:
        return {}
    if spec.protocol == "anthropic":
        return {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION}
    return {"Authorization": f"Bearer {api_key}"}


def _get(url: str, spec: ProviderSpec, api_key: Optional[str], transport: Optional[httpx.BaseTransport]) -> Any:
    try:
        with httpx.Client(timeout=30, transport=transport) as client:
            response = client.get(url, headers=_headers(spec, api_key))
    except httpx.HTTPError as exc:
        raise DiscoveryError(f"could not reach {spec.label} at {url}: {exc}") from exc
    if response.status_code in (401, 403):
        raise DiscoveryError(f"{spec.label} rejected the key (HTTP {response.status_code}). Check it at {spec.keys_url or url}.")
    if response.status_code >= 400:
        detail = response.text.strip().replace(api_key or "\0", "••••")[:200]
        raise DiscoveryError(f"{spec.label} answered HTTP {response.status_code} for {url}: {detail}")
    try:
        return response.json()
    except ValueError as exc:
        raise DiscoveryError(f"{spec.label} did not answer with JSON at {url}") from exc


def list_models(
    spec: ProviderSpec,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    transport: Optional[httpx.BaseTransport] = None,
) -> list[ModelInfo]:
    """The provider's models, newest first when it says when they were created."""
    root = (base_url or spec.base_url).rstrip("/")
    if not root:
        raise DiscoveryError(f"{spec.label} needs a base URL")
    payload = _get(f"{root}/models", spec, api_key, transport)
    rows = payload.get("data", payload.get("models", [])) if isinstance(payload, dict) else payload
    models = [_model_info(row) for row in rows or [] if isinstance(row, dict) and row.get("id")]
    return sorted(models, key=lambda m: -(m.created or 0))


def check_key(
    spec: ProviderSpec,
    api_key: Optional[str],
    base_url: Optional[str] = None,
    transport: Optional[httpx.BaseTransport] = None,
) -> None:
    """Raise :class:`DiscoveryError` unless the provider accepts ``api_key`` (local servers need none)."""
    if spec.id == "openrouter":
        # OpenRouter's model list is public, so it cannot tell a good key from a bad one.
        _get(f"{(base_url or spec.base_url).rstrip('/')}/key", spec, api_key, transport)
        return
    list_models(spec, api_key, base_url, transport)


# A small change took about 15 free-model requests in our live runs: drafting, the agent's steps, a repair.
LOW_FREE_REQUESTS = 25


@dataclass
class FreeQuota:
    """OpenRouter's daily allowance of requests to ``:free`` models."""

    used: int
    limit: int
    remaining: int


def is_free_model(model: str) -> bool:
    """An OpenRouter model that counts against the daily free-request limit."""
    return model.endswith(":free") or model == "openrouter/free"


def openrouter_free_quota(
    api_key: str,
    base_url: str = "https://openrouter.ai/api/v1",
    transport: Optional[httpx.BaseTransport] = None,
) -> Optional[FreeQuota]:
    """Free requests left today, or None when OpenRouter does not say or cannot be reached.

    Reading the key's status is not itself a model request.
    """
    try:
        with httpx.Client(timeout=8, transport=transport) as client:
            response = client.get(f"{base_url.rstrip('/')}/key", headers={"Authorization": f"Bearer {api_key}"})
        counts = (response.json().get("data") or {}).get("free_model_daily_requests")
        return FreeQuota(int(counts["used"]), int(counts["limit"]), int(counts["remaining"]))
    except (httpx.HTTPError, ValueError, AttributeError, KeyError, TypeError):
        return None


async def try_model(provider: Any) -> tuple[bool, str, float]:
    """One tiny real request: (worked, detail, seconds). Proves the model answers before a run needs it."""
    started = time.monotonic()
    try:
        response = await provider.generate("Reply with the single word: ok")
    except Exception as exc:
        return False, str(exc).splitlines()[0][:300], time.monotonic() - started
    answered_by = getattr(response, "model", "") or provider.model
    return True, f"answered by {answered_by}", time.monotonic() - started


def _model_info(row: dict) -> ModelInfo:
    pricing = row.get("pricing") or {}
    free: Optional[bool] = None
    if pricing:
        free = str(pricing.get("prompt")) in ("0", "0.0") and str(pricing.get("completion")) in ("0", "0.0")
    elif str(row.get("id", "")).endswith(":free"):
        free = True
    params = row.get("supported_parameters")
    created = row.get("created")
    return ModelInfo(
        id=str(row["id"]),
        context=row.get("context_length") or row.get("context_window") or row.get("max_context_length"),
        free=free,
        tools=("tools" in params) if isinstance(params, list) else None,
        created=created if isinstance(created, int) else None,
    )
