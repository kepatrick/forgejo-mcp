import time
from collections import deque
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException, status


class LoginRateLimiter:
    """Small in-memory limiter suitable for the supported single-replica deployment."""

    def __init__(
        self,
        attempts: int = 5,
        window_seconds: int = 300,
        max_keys: int = 10_000,
    ) -> None:
        self.attempts = attempts
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._events: dict[str, deque[float]] = {}
        self._lock = Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            events = self._events.get(key)
            if events is None:
                return
            _prune(events, now, self.window_seconds)
            if not events:
                self._events.pop(key, None)
                return
            if len(events) >= self.attempts:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many login attempts")

    def failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            events = self._events.get(key)
            if events is not None:
                _prune(events, now, self.window_seconds)
                if not events:
                    self._events.pop(key, None)
                    events = None
            if events is None:
                if len(self._events) >= self.max_keys:
                    _prune_mapping(self._events, now, self.window_seconds)
                if len(self._events) >= self.max_keys:
                    raise HTTPException(
                        status.HTTP_429_TOO_MANY_REQUESTS,
                        "login rate limiter capacity exceeded",
                    )
                events = deque()
                self._events[key] = events
            events.append(now)

    def success(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    scope: str | None = None
    retry_after_seconds: int = 0


class MultiScopeRateLimiter:
    """Fixed-window in-memory limits for the supported single-replica deployment."""

    def __init__(self, window_seconds: int, max_keys: int = 20_000) -> None:
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._events: dict[str, deque[float]] = {}
        self._lock = Lock()

    def check(self, limits: list[tuple[str, str, int]]) -> RateLimitDecision:
        now = time.monotonic()
        keyed_limits = [
            (scope, f"{scope}:{identifier}", limit) for scope, identifier, limit in limits
        ]
        with self._lock:
            for scope, key, limit in keyed_limits:
                events = self._events.get(key)
                if events is None:
                    continue
                _prune(events, now, self.window_seconds)
                if not events:
                    self._events.pop(key, None)
                    continue
                if len(events) >= limit:
                    retry_after = max(1, int(events[0] + self.window_seconds - now) + 1)
                    return RateLimitDecision(
                        allowed=False,
                        scope=scope,
                        retry_after_seconds=retry_after,
                    )

            new_keys = {key for _scope, key, _limit in keyed_limits if key not in self._events}
            if len(self._events) + len(new_keys) > self.max_keys:
                _prune_mapping(self._events, now, self.window_seconds)
            if len(self._events) + len(new_keys) > self.max_keys:
                return RateLimitDecision(
                    allowed=False,
                    scope="capacity",
                    retry_after_seconds=self.window_seconds,
                )

            for _scope, key, _limit in keyed_limits:
                self._events.setdefault(key, deque()).append(now)
            return RateLimitDecision(allowed=True)


def _prune(events: deque[float], now: float, window_seconds: int) -> None:
    while events and events[0] <= now - window_seconds:
        events.popleft()


def _prune_mapping(
    entries: dict[str, deque[float]],
    now: float,
    window_seconds: int,
) -> None:
    for key, events in list(entries.items()):
        _prune(events, now, window_seconds)
        if not events:
            entries.pop(key, None)
