"""Factory function for instantiating configured LLM providers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from contexer.config.settings import ContexerConfig

from contexer.llm.base import LLMProvider
from contexer.llm.openrouter import OpenRouterProvider


def create_llm_provider(config: ContexerConfig) -> LLMProvider:
    """Instantiate the appropriate LLMProvider based on ContexerConfig.

    Currently supports 'openrouter' as the default provider, structured to allow
    plugging in future providers.
    """
    provider_name = (config.llm_provider or "openrouter").lower()

    if provider_name == "openrouter":
        return OpenRouterProvider(
            api_key=config.openrouter_api_key,
            model=config.openrouter_model,
            site_url=config.openrouter_site_url,
            app_name=config.openrouter_app_name,
        )

    raise ValueError(
        f"Unsupported LLM provider '{provider_name}'. "
        "Supported providers in this release: ['openrouter']"
    )
