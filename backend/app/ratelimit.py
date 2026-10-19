"""
Tiny in-memory per-IP rate limiter.

The deployed API uses YOUR Groq key, and the URL is public -- without a limit,
anyone could burn your free-tier quota in a loop. In-memory is fine for a
single Render instance (it resets on restart, which is acceptable here).
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException


class RateLimiter:
    def __init__(self, per_minute: int, per_day: int):
        self.per_minute, self.per_day = per_minute, per_day
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        q = self.hits[key]
        while q and now - q[0] > 86_400:
            q.popleft()
        last_min = sum(1 for t in q if now - t < 60)
        if last_min >= self.per_minute:
            raise HTTPException(429, "Too many requests — wait a minute and try again.")
        if len(q) >= self.per_day:
            raise HTTPException(429, "Daily limit reached for this demo. Try again tomorrow.")
        q.append(now)
        if len(self.hits) > 10_000:          # don't grow forever on a public URL
            self.hits.clear()
