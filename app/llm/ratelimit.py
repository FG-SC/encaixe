"""Client-side rate limiting for the free plan: token buckets per minute (requests, tokens) + daily caps."""

from __future__ import annotations

import threading
import time

from app.config import RULES


class RateLimited(Exception):
    def __init__(self, wait_s: float, reason: str) -> None:
        super().__init__(reason)
        self.wait_s = wait_s
        self.reason = reason


class TokenBucket:
    def __init__(self, capacity: float, per_minute: float, clock=time.monotonic) -> None:  # type: ignore[no-untyped-def]
        self.capacity = capacity
        self.rate = per_minute / 60.0
        self.level = capacity
        self._clock = clock
        self._t = clock()

    def _refill(self) -> None:
        now = self._clock()
        self.level = min(self.capacity, self.level + (now - self._t) * self.rate)
        self._t = now

    def wait_time(self, amount: float) -> float:
        self._refill()
        if amount > self.capacity:
            amount = self.capacity
        return 0.0 if self.level >= amount else (amount - self.level) / self.rate

    def take(self, amount: float) -> None:
        self._refill()
        self.level -= min(amount, self.capacity)


class Limiter:
    """acquire() waits up to ``max_wait`` seconds, then raises RateLimited (onboarding never waits long)."""

    def __init__(self, clock=time.monotonic, sleep=time.sleep) -> None:  # type: ignore[no-untyped-def]
        self.requests = TokenBucket(RULES.llm.rpm, RULES.llm.rpm, clock)
        self.tokens = TokenBucket(RULES.llm.tpm, RULES.llm.tpm, clock)
        self._lock = threading.Lock()
        self._sleep = sleep
        self.cooldown_until = 0.0
        self._clock = clock

    def acquire(self, est_tokens: int, max_wait: float, requests_today: int = 0, tokens_today: int = 0) -> None:
        if requests_today >= RULES.llm.rpd:
            raise RateLimited(3600, "limite diário de requisições atingido")
        if RULES.llm.tpd and tokens_today + est_tokens > RULES.llm.tpd:
            raise RateLimited(3600, "limite diário de tokens atingido")
        with self._lock:
            wait = max(
                self.requests.wait_time(1), self.tokens.wait_time(est_tokens), self.cooldown_until - self._clock()
            )
            if wait > max_wait:
                raise RateLimited(wait, f"limite por minuto: espera de {wait:.0f} s")
            if wait > 0:
                self._sleep(wait)
            self.requests.take(1)
            self.tokens.take(est_tokens)

    def cool_down(self, seconds: float) -> None:
        """After a 429: honour retry-after for every following call."""
        self.cooldown_until = max(self.cooldown_until, self._clock() + seconds)


_limiter: Limiter | None = None


def limiter() -> Limiter:
    global _limiter
    if _limiter is None:
        _limiter = Limiter()
    return _limiter
