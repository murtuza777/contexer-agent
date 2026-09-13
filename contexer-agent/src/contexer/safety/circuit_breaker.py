"""Circuit breaker registry tracking model/API failures and managing failovers.

Adapted from AgentForge (MIT License, Copyright (c) 2026 Mohit Goyal).
Prevents cascading failures and endless retries against degraded upstream endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import time
from typing import Optional


class CircuitState(str, Enum):
    """The operational state of a circuit breaker."""

    CLOSED = "closed"          # Healthy: requests pass through
    OPEN = "open"              # Failing: requests fail fast or trigger fallbacks
    HALF_OPEN = "half_open"    # Probing: testing recovery after reset timeout


@dataclass
class _BreakerState:
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0


class CircuitBreakerRegistry:
    """Registry maintaining circuit breaker states per model or provider endpoint."""

    def __init__(self, failure_threshold: int = 3, reset_timeout: float = 60.0) -> None:
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self._breakers: dict[str, _BreakerState] = {}

    def _get_or_create(self, model_name: str) -> _BreakerState:
        if model_name not in self._breakers:
            self._breakers[model_name] = _BreakerState()
        return self._breakers[model_name]

    def record_failure(self, model_name: str) -> None:
        """Record a failure for the specified model and trip to OPEN if threshold reached."""
        state = self._get_or_create(model_name)
        state.failure_count += 1
        state.last_failure_time = time.time()
        if state.failure_count >= self.failure_threshold:
            state.state = CircuitState.OPEN

    def record_success(self, model_name: str) -> None:
        """Record a success, resetting failure counter and closing the circuit."""
        state = self._get_or_create(model_name)
        state.failure_count = 0
        state.state = CircuitState.CLOSED

    def can_try(self, model_name: str) -> bool:
        """Check if requests are permitted to this model."""
        state = self._get_or_create(model_name)
        if state.state == CircuitState.CLOSED:
            return True
        if state.state == CircuitState.OPEN:
            elapsed = time.time() - state.last_failure_time
            if elapsed >= self.reset_timeout:
                state.state = CircuitState.HALF_OPEN
                return True
            return False
        # HALF_OPEN allows a trial request
        return True

    def get_state(self, model_name: str) -> CircuitState:
        """Get the current state for a model, accounting for timeout transitions."""
        state = self._get_or_create(model_name)
        if state.state == CircuitState.OPEN:
            elapsed = time.time() - state.last_failure_time
            if elapsed >= self.reset_timeout:
                state.state = CircuitState.HALF_OPEN
        return state.state

    def is_open(self, model_name: str) -> bool:
        """Return True if circuit is currently open and requests should fail-fast."""
        state = self._get_or_create(model_name)
        if state.state != CircuitState.OPEN:
            return False
        elapsed = time.time() - state.last_failure_time
        if elapsed >= self.reset_timeout:
            state.state = CircuitState.HALF_OPEN
            return False
        return True

    def reset(self, model_name: Optional[str] = None) -> None:
        """Reset breaker state for a specific model or all models."""
        if model_name:
            self._breakers.pop(model_name, None)
        else:
            self._breakers.clear()
