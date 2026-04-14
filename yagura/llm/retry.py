"""LLM retry helpers.

Implements the spec requirement:
  "LLM rate limit / timeout → Auto-retry (max 3, exponential backoff).
   After 3 failures: notify user."

Retries are applied inside each LLMProvider subclass by wrapping the
network call with `with_retry(...)`. Only `LLMRateLimitError` and
`LLMTimeoutError` are retried; `LLMInvalidResponseError` and other
LLMErrors propagate immediately (no point retrying a malformed prompt).
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from yagura.errors import LLMRateLimitError, LLMTimeoutError

T = TypeVar("T")

_logger = logging.getLogger(__name__)


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 1.0  # seconds
    max_delay: float = 30.0  # cap the exponential backoff
    jitter: float = 0.1  # ±10% random jitter, avoids thundering herd

    def delay_for(self, attempt: int) -> float:
        """Compute sleep time before retry attempt N (1-indexed)."""
        exp = self.base_delay * (2 ** (attempt - 1))
        capped = min(exp, self.max_delay)
        if self.jitter:
            jitter = capped * self.jitter * (2 * random.random() - 1)
            capped = max(0.0, capped + jitter)
        return capped


DEFAULT_POLICY = RetryPolicy()


async def with_retry[T](
    fn: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy = DEFAULT_POLICY,
    provider_name: str = "LLM",
) -> T:
    """Run `fn` with exponential-backoff retry on rate-limit / timeout errors.

    - Only LLMRateLimitError and LLMTimeoutError trigger a retry.
    - Other exceptions propagate unchanged.
    - After `max_attempts` failures, the last exception is re-raised.
    """
    last_exc: Exception | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return await fn()
        except (LLMRateLimitError, LLMTimeoutError) as exc:
            last_exc = exc
            if attempt >= policy.max_attempts:
                _logger.warning("%s call failed after %d attempts: %s", provider_name, attempt, exc)
                break
            delay = policy.delay_for(attempt)
            _logger.info(
                "%s call failed (attempt %d/%d): %s — retrying in %.2fs",
                provider_name,
                attempt,
                policy.max_attempts,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc
