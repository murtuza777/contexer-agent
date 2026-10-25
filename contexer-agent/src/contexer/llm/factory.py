"""Instantiating LLM providers, and choosing the one that compiles goals into checks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from contexer.config.project import CompilerSettings
    from contexer.config.settings import ContexerConfig

from contexer.llm.base import LLMProvider
from contexer.llm.openrouter import OpenAIProvider, OpenRouterProvider

SUPPORTED_PROVIDERS = ("anthropic", "openai", "openrouter")

# When nothing is chosen explicitly, prefer the provider most likely to have a
# strong model behind it: draft quality is what decides how many bugs a
# contract catches (see bench/RESULTS.md).
_AUTO_ORDER = ("anthropic", "openai", "openrouter")


def create_llm_provider(config: ContexerConfig, provider: Optional[str] = None, model: Optional[str] = None) -> LLMProvider:
    """Build ``provider`` (default: ``config.llm_provider``), optionally overriding its model."""
    name = (provider or config.llm_provider or "openrouter").lower()
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
            base_url=config.openai_base_url,
        )
    if name == "anthropic":
        from contexer.llm.anthropic import AnthropicProvider

        return AnthropicProvider(api_key=config.anthropic_api_key, model=model or config.anthropic_model)
    raise ValueError(
        f"Unsupported LLM provider '{name}'. Supported providers in this release: {list(SUPPORTED_PROVIDERS)}"
    )


def available_providers(config: ContexerConfig) -> list[str]:
    keys = {
        "anthropic": config.anthropic_api_key,
        "openai": config.openai_api_key,
        "openrouter": config.openrouter_api_key,
    }
    return [name for name in _AUTO_ORDER if keys[name]]


def compiler_provider(
    config: ContexerConfig, settings: Optional[CompilerSettings] = None
) -> Optional[LLMProvider]:
    """The provider used to compile goals, or None when no key is configured.

    Precedence: ``[compiler]`` in contexer.toml, then ``CONTEXER_LLM_PROVIDER``,
    then the first available key in the order anthropic, openai, openrouter.
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
