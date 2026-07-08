"""In-memory, single-flight, short-TTL cache for upstream fetches — the scaling lever.

A NOTAM list for an airport is identical for every pilot, so with thousands of
pilots we must NOT hit the FAA once per pilot per airport. This caches each fetch
by key for a short TTL and — crucially — coalesces concurrent misses for the SAME
key into a SINGLE upstream call ("single-flight"): a morning rush of 500 pilots
all briefing EDDK triggers one FAA fetch, not 500.

Two mechanisms:
  1. TTL cache  — a hit within `ttl` seconds skips the upstream call entirely.
  2. Single-flight — while one thread is fetching a key, other threads asking for
     the same key wait for it instead of firing their own fetch (no stampede).

In-memory + per-process: on one server instance it is shared across all pilots
hitting that instance. For a multi-instance deploy, back get_or_fetch() with a
shared store (Redis) so the coalescing spans instances too.

Wiring — Used by: faa.py (wraps fetch_notams). Calls nothing internal.
"""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()                 # guards _store and _keylocks
_store: dict = {}                        # key -> (expires_at, value)
_keylocks: dict = {}                     # key -> Lock (one in-flight fetch per key)


def _keylock(key: str) -> threading.Lock:
    with _lock:
        lk = _keylocks.get(key)
        if lk is None:
            lk = threading.Lock()
            _keylocks[key] = lk
        return lk


def _read(key: str, now: float):
    """Return the cached value (which may legitimately be an empty list), or None
    on a miss/expiry. None uniquely means 'not cached' — fetchers return lists."""
    with _lock:
        entry = _store.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    return value if expires_at >= now else None


def get_or_fetch(key: str, fetcher, ttl: float, now: float | None = None):
    """Return key's value from cache, or call fetcher() once and cache it for ttl
    seconds. Concurrent callers for the same key share a single fetcher() call."""
    t = time.time() if now is None else now
    hit = _read(key, t)
    if hit is not None:
        return hit                       # fast path — no lock, no upstream call

    with _keylock(key):                  # single-flight: one fetch per key at a time
        t = time.time() if now is None else now
        hit = _read(key, t)              # someone may have filled it while we waited
        if hit is not None:
            return hit
        value = fetcher()                # the one real upstream call
        with _lock:
            _store[key] = (t + ttl, value)
        return value


def clear() -> None:
    """Drop everything (used in tests)."""
    with _lock:
        _store.clear()
        _keylocks.clear()


def stats() -> dict:
    with _lock:
        return {"entries": len(_store)}
