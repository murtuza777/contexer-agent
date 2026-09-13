"""Contexer LLM Layer — provider-agnostic language model interface."""

from contexer.llm.base import (
    LLMAuthenticationError,
    LLMChunk,
    LLMError,
    LLMModelUnavailableError,
    LLMNetworkError,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
    ToolCallRequest,
)
from contexer.llm.factory import create_llm_provider
from contexer.llm.openrouter import OpenRouterProvider
from contexer.llm.prompts import build_system_prompt

__all__ = [
    "LLMAuthenticationError",
    "LLMChunk",
    "LLMError",
    "LLMModelUnavailableError",
    "LLMNetworkError",
    "LLMProvider",
    "LLMRateLimitError",
    "LLMResponse",
    "ToolCallRequest",
    "create_llm_provider",
    "OpenRouterProvider",
    "build_system_prompt",
]
