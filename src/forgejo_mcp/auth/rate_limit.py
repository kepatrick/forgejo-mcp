import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import HTTPException, status


class LoginRateLimiter:
    """Small in-memory limiter suitable for the supported single-replica deployment."""

    def __init__(self, attempts: int = 5, window_seconds: int = 300) -> None:
        self.attempts = attempts
        self.window_seconds = window_seconds
        self._events: defaultdict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        events = self._events[key]
        while events and events[0] <= now - self.window_seconds:
            events.popleft()
        if len(events) >= self.attempts:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many login attempts")

    def failure(self, key: str) -> None:
        self._events[key].append(time.monotonic())

    def success(self, key: str) -> None:
        self._events.pop(key, None)


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    scope: str | None = None
    retry_after_seconds: int = 0


class MultiScopeRateLimiter:
    """Fixed-window in-memory limits for the supported single-replica deployment."""

    def __init__(self, window_seconds: int) -> None:
        self.window_seconds = window_seconds
        self._events: defaultdict[str, deque[float]] = defaultdict(deque)

    def check(self, limits: list[tuple[str, str, int]]) -> RateLimitDecision:
        now = time.monotonic()
        prepared: list[tuple[str, str, int, deque[float]]] = []
        for scope, identifier, limit in limits:
            key = f"{scope}:{identifier}"
            events = self._events[key]
            while events and events[0] <= now - self.window_seconds:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, int(events[0] + self.window_seconds - now) + 1)
                return RateLimitDecision(
                    allowed=False,
                    scope=scope,
                    retry_after_seconds=retry_after,
                )
            prepared.append((scope, identifier, limit, events))
        for _scope, _identifier, _limit, events in prepared:
            events.append(now)
        return RateLimitDecision(allowed=True)
