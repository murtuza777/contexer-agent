"""Base abstractions and error hierarchy for Contexer LLM providers."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


def _mask_api_key_match(match: re.Match[str]) -> str:
    val = match.group(0)
    if val.startswith("sk-or-v1-"):
        return "sk-or-v1-...[MASKED]"
    if val.startswith("AIza"):
        return "AIza...[MASKED]"
    if val.startswith("sk-"):
        return "sk-...[MASKED]"
    return "...[MASKED]"


# Patterns to mask OpenRouter, OpenAI, and Google API keys. A key starts a word: "sk-" in the middle of
# one ("task-remaining-count-label", a test id or a class name) is not a key, and masking it would change
# the names in a diff or a page snapshot that an agent is asked to work with. In JSON text a key on a
# new line follows the two characters "\n", so a letter that is the end of such an escape does not count.
_KEY_START = r"(?:(?<![0-9A-Za-z])|(?<=\\[nrt]))"
_API_KEY_PATTERNS = [
    re.compile(_KEY_START + r"sk-or-v1-[0-9a-zA-Z\-_]{20,}"),
    re.compile(_KEY_START + r"sk-[0-9a-zA-Z\-_]{20,}"),
    re.compile(_KEY_START + r"AIza[0-9A-Za-z\-_]{35}"),
]


def sanitize_sensitive_text(text: str, sensitive_values: list[str] | None = None) -> str:
    """Mask known API key patterns and explicit secret values from text."""
    if not text:
        return text

    sanitized = text
    for pattern in _API_KEY_PATTERNS:
        sanitized = pattern.sub(_mask_api_key_match, sanitized)

    if sensitive_values:
        for secret in sensitive_values:
            if secret and len(secret) >= 4:
                if secret.startswith("sk-or-v1-"):
                    mask = "sk-or-v1-...[MASKED]"
                elif secret.startswith("AIza"):
                    mask = "AIza...[MASKED]"
                elif secret.startswith("sk-"):
                    mask = "sk-...[MASKED]"
                else:
                    mask = f"{secret[:3]}...[MASKED]"
                sanitized = sanitized.replace(secret, mask)

    return sanitized


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LLMError(Exception):
    """Base exception for all LLM provider errors."""

    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        clean_msg = sanitize_sensitive_text(message)
        super().__init__(clean_msg)
        self.original_error = original_error


class LLMAuthenticationError(LLMError):
    """Raised when the API key is missing or invalid."""


class LLMRateLimitError(LLMError):
    """Raised when rate limits or quotas are exceeded."""


class LLMNetworkError(LLMError):
    """Raised when connection or network timeouts occur."""


class LLMModelUnavailableError(LLMError):
    """Raised when the requested model is unknown, deprecated, or unavailable."""


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


@dataclass
class LLMResponse:
    """Complete response returned from an LLM call."""

    text: str = ""
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Abstract Provider Interface
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Abstract provider interface for language model backends.

    Any provider (OpenRouter, OpenAI, Anthropic, local models) must implement
    this interface, ensuring the Contexer agent remains decoupled from
    specific LLM vendors.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the provider (e.g., 'openrouter', 'anthropic')."""

    @property
    @abstractmethod
    def model(self) -> str:
        """Active model identifier."""

    @abstractmethod
    async def generate(
        self,
        prompt: str | list[Any],
        system_instruction: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a complete response for a prompt."""

    @abstractmethod
    def validate_configuration(self) -> tuple[bool, str | None]:
        """Validate if required credentials and options are present.

        Returns:
            A tuple of (is_valid, error_message). Does not make network requests.
        """
