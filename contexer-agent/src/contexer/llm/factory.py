"""Instantiating LLM providers, and choosing the one that compiles goals into checks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from contexer.config.project import CompilerSettings
    from contexer.config.settings import ContexerConfig

from contexer.llm.base import LLMProvider
from contexer.llm.catalog import PROVIDERS, provider_ids, provider_spec
from contexer.llm.openrouter import OpenAICompatibleProvider, OpenAIProvider, OpenRouterProvider

SUPPORTED_PROVIDERS = tuple(provider_ids())

# When nothing is chosen explicitly, prefer the provider most likely to have a
# strong model behind it: draft quality is what decides how many bugs a
# contract catches (see bench/RESULTS.md). Other keys follow in catalogue order.
_AUTO_ORDER = ("anthropic", "openai", "openrouter")


def create_llm_provider(config: ContexerConfig, provider: Optional[str] = None, model: Optional[str] = None) -> LLMProvider:
    """Build ``provider`` (default: ``config.llm_provider``), optionally overriding its model.

    Model precedence: ``model`` (``[compiler] model``), then ``CONTEXER_LLM_MODEL``,
    then the provider's own variable (``OPENROUTER_MODEL``...), then its default.
    """
    name = (provider or config.llm_provider or "openrouter").lower()
    # CONTEXER_LLM_MODEL / _BASE_URL belong to the provider chosen with them (CONTEXER_LLM_PROVIDER);
    # a project that picks another provider must not inherit another provider's model id.
    paired = name == (config.compiler_provider or "").lower()
    model = model or (config.llm_model if paired else None)
    base_override = config.llm_base_url if paired else None
    if name == "openrouter":
        return OpenRouterProvider(
            api_key=config.openrouter_api_key,
            model=model or config.openrouter_model,
            site_url=config.openrouter_site_url,
            app_name=config.openrouter_app_name,
        )
    if name == "openai":
        return OpenAIProvider(
            api_key=config.openai_api_key,
            model=model or config.openai_model,
            base_url=base_override or config.openai_base_url,
        )
    if name == "anthropic":
        from contexer.llm.anthropic import AnthropicProvider

        return AnthropicProvider(api_key=config.anthropic_api_key, model=model or config.anthropic_model)
    spec = provider_spec(name)  # ValueError for an unknown provider
    base_url = base_override or spec.base_url
    if not base_url:
        raise ValueError(f"The '{name}' provider needs a base URL: set CONTEXER_LLM_BASE_URL or run `contexer setup`.")
    return OpenAICompatibleProvider.for_spec(spec, model=model or spec.default_model, base_url=base_url)


def available_providers(config: ContexerConfig) -> list[str]:
    keys = {
        "anthropic": config.anthropic_api_key,
        "openai": config.openai_api_key,
        "openrouter": config.openrouter_api_key,
    }
    ordered = [name for name in _AUTO_ORDER if keys[name]]
    # Other providers are used automatically only with a key and a known default model.
    ordered += [p.id for p in PROVIDERS if p.id not in keys and p.key() and p.default_model]
    return ordered


def compiler_provider(
    config: ContexerConfig, settings: Optional[CompilerSettings] = None
) -> Optional[LLMProvider]:
    """The provider used to compile goals, or None when no key is configured.

    Precedence: ``[compiler]`` in contexer.toml, then ``CONTEXER_LLM_PROVIDER``
    (which ``contexer setup`` sets for you), then the first available key in
    the order anthropic, openai, openrouter.
    """
    chosen = (settings.provider if settings else None) or config.compiler_provider
    model = settings.model if settings else None
    if chosen:
        provider = create_llm_provider(config, chosen, model)
        return provider if provider.validate_configuration()[0] else None
    for name in available_providers(config):
        provider = create_llm_provider(config, name, model)
        if provider.validate_configuration()[0]:
            return provider
    return None
