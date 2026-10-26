"""Model providers a user can bring their own key for (BYOK).

One place that knows, for every provider: where its OpenAI-compatible API is,
which environment variable holds its key, where to get one, a default model
when Contexer has measured one, and the provider id OpenCode uses (OpenCode
reads its catalogue from models.dev, as do the key variable names below).
Endpoints were checked to exist on 2026-10-26.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, Optional

from contexer.config.settings import DEFAULT_OPENROUTER_MODEL

Protocol = Literal["anthropic", "openai"]


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    key_env: str
    keys_url: str
    protocol: Protocol = "openai"
    base_url: str = ""
    # A model Contexer has measured or that is the provider's flagship; empty means "pick one".
    default_model: str = ""
    # Provider id in OpenCode (models.dev), so `--agent opencode` can use the same key.
    opencode_id: str = ""
    # Coding agent that speaks this provider natively, when there is one.
    native_agent: str = ""
    # Local servers need no key.
    local: bool = False
    note: str = ""

    def key(self) -> Optional[str]:
        value = os.environ.get(self.key_env, "").strip()
        return value or None

    def opencode_model(self, model: str) -> Optional[str]:
        """``provider/model`` for OpenCode, or None if OpenCode does not know this provider."""
        return f"{self.opencode_id}/{model}" if self.opencode_id and model else None


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        "openrouter",
        "OpenRouter",
        "OPENROUTER_API_KEY",
        "https://openrouter.ai/keys",
        base_url="https://openrouter.ai/api/v1",
        default_model=DEFAULT_OPENROUTER_MODEL,
        opencode_id="openrouter",
        note="one key for hundreds of models, including free ones",
    ),
    ProviderSpec(
        "anthropic",
        "Anthropic",
        "ANTHROPIC_API_KEY",
        "https://console.anthropic.com/settings/keys",
        protocol="anthropic",
        base_url="https://api.anthropic.com/v1",
        default_model="claude-opus-5-5",
        opencode_id="anthropic",
        native_agent="claude-code",
    ),
    ProviderSpec(
        "openai",
        "OpenAI",
        "OPENAI_API_KEY",
        "https://platform.openai.com/api-keys",
        base_url="https://api.openai.com/v1",
        default_model="gpt-5",
        opencode_id="openai",
        native_agent="codex",
    ),
    ProviderSpec(
        "google",
        "Google Gemini",
        "GEMINI_API_KEY",
        "https://aistudio.google.com/apikey",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        opencode_id="google",
    ),
    ProviderSpec("groq", "Groq", "GROQ_API_KEY", "https://console.groq.com/keys",
                 base_url="https://api.groq.com/openai/v1", opencode_id="groq"),
    ProviderSpec("deepseek", "DeepSeek", "DEEPSEEK_API_KEY", "https://platform.deepseek.com/api_keys",
                 base_url="https://api.deepseek.com", opencode_id="deepseek"),
    ProviderSpec("mistral", "Mistral", "MISTRAL_API_KEY", "https://console.mistral.ai/api-keys",
                 base_url="https://api.mistral.ai/v1", opencode_id="mistral"),
    ProviderSpec("togetherai", "Together AI", "TOGETHER_API_KEY", "https://api.together.ai/settings/api-keys",
                 base_url="https://api.together.xyz/v1", opencode_id="togetherai"),
    ProviderSpec("xai", "xAI", "XAI_API_KEY", "https://console.x.ai",
                 base_url="https://api.x.ai/v1", opencode_id="xai"),
    ProviderSpec("fireworks-ai", "Fireworks", "FIREWORKS_API_KEY", "https://fireworks.ai/account/api-keys",
                 base_url="https://api.fireworks.ai/inference/v1", opencode_id="fireworks-ai"),
    ProviderSpec("cerebras", "Cerebras", "CEREBRAS_API_KEY", "https://cloud.cerebras.ai",
                 base_url="https://api.cerebras.ai/v1", opencode_id="cerebras"),
    ProviderSpec("nvidia", "NVIDIA", "NVIDIA_API_KEY", "https://build.nvidia.com",
                 base_url="https://integrate.api.nvidia.com/v1", opencode_id="nvidia"),
    ProviderSpec("ollama", "Ollama (local)", "OLLAMA_API_KEY", "https://ollama.com",
                 base_url="http://localhost:11434/v1", local=True, note="models on your machine"),
    ProviderSpec(
        "custom",
        "Any OpenAI-compatible API",
        "CONTEXER_CUSTOM_API_KEY",
        "",
        note="your own gateway or provider; set its base URL",
    ),
)

_BY_ID = {p.id: p for p in PROVIDERS}


def provider_spec(provider_id: str) -> ProviderSpec:
    try:
        return _BY_ID[provider_id.lower()]
    except KeyError:
        raise ValueError(
            f"Unknown provider '{provider_id}'. Choose one of: {', '.join(p.id for p in PROVIDERS)}"
        ) from None


def provider_ids() -> list[str]:
    return [p.id for p in PROVIDERS]
