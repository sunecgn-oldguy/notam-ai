"""In-memory sliding-window rate limiter (review #4).

Guards the expensive /briefing endpoint. Each briefing fans out to many FAA
fetches and (with AI on) many Claude calls, so an unbounded public URL is a real
cost/DoS exposure. This caps calls per key (the client IP) inside a rolling
time window: at most `max_calls` in any `per_seconds` stretch.

Sliding window, not fixed buckets, so you can't burst 2x across a bucket edge.
In-memory and per-process: it resets on restart, and on a multi-instance deploy
each instance counts on its own. That is fine for the intended protection —
move the counter to a shared store (Redis) only if you ever run several server
instances behind a load balancer.

Wiring — Used by: server.py (wraps POST /briefing). Calls nothing internal.
"""

from __future__ import annotations

import threading
import time


class RateLimiter:
    """max_calls per rolling per_seconds window, keyed by an arbitrary string."""

    def __init__(self, max_calls: int, per_seconds: float):
        self._max = max_calls
        self._per = per_seconds
        self._hits: dict[str, list[float]] = {}   # key -> recent call timestamps
        self._lock = threading.Lock()
        self._last_sweep = 0.0

    def allow(self, key: str, now: float | None = None) -> bool:
        """Record a call for `key`; return True if it is within the limit.

        On a False result nothing is recorded, so a blocked caller does not push
        its own window further out (it can retry as soon as old hits age out).
        """
        now = time.time() if now is None else now
        cutoff = now - self._per
        with self._lock:
            self._sweep(now, cutoff)
            hits = [t for t in self._hits.get(key, ()) if t > cutoff]
            if len(hits) >= self._max:
                self._hits[key] = hits           # keep the pruned list; deny
                return False
            hits.append(now)
            self._hits[key] = hits
            return True

    def _sweep(self, now: float, cutoff: float) -> None:
        """Occasionally drop keys with no recent hits, so the dict stays bounded."""
        if now - self._last_sweep < self._per:
            return
        self._last_sweep = now
        self._hits = {k: recent for k, recent in
                      ((k, [t for t in ts if t > cutoff]) for k, ts in self._hits.items())
                      if recent}
