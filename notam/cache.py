"""Content-addressed cache for AI-processed NOTAMs (the big token saver).

A NOTAM is identical for every pilot, so turning one raw NOTAM into readable
text only needs to happen once in the world. We key on a hash of the raw NOTAM
text: identical text -> identical result, reused for free by everyone. Only
NOTAMs whose exact text we have never seen cost tokens.

Because the key *is* the text, a NOTAM that FAA changes gets a new hash and is
re-processed automatically — we can never show a stale translation of changed
text.

This holds public NOTAM translations only, never user routes, so there is no
privacy concern in sharing it across users. Prototype storage is one JSON file;
in the real server swap it for Redis/SQLite behind the same three functions.
"""

from __future__ import annotations

import hashlib
import json
import os
import time

_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_FILE = os.path.join(_DIR, "notam_cache.json")


def key(raw: str) -> str:
    """Stable content hash of a raw NOTAM (whitespace-normalised)."""
    norm = " ".join(raw.split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def _load() -> dict:
    if not os.path.exists(_FILE):
        return {}
    with open(_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save(store: dict) -> None:
    os.makedirs(_DIR, exist_ok=True)
    with open(_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def get(raw: str, now: float | None = None) -> str | None:
    """Return the cached processed text for this raw NOTAM, or None on a miss."""
    now = time.time() if now is None else now
    entry = _load().get(key(raw))
    if entry is None:
        return None
    if entry.get("expires") is not None and entry["expires"] < now:
        return None                       # expired — treat as a miss
    return entry["text"]


def put(raw: str, text: str, expires: float | None = None, model: str = "") -> None:
    """Store the processed text for this raw NOTAM."""
    store = _load()
    store[key(raw)] = {
        "text": text, "expires": expires, "model": model, "stored": time.time(),
    }
    _save(store)


def cleanup(now: float | None = None) -> int:
    """Drop entries whose NOTAM has expired. Returns how many were removed."""
    now = time.time() if now is None else now
    store = _load()
    live = {k: v for k, v in store.items()
            if v.get("expires") is None or v["expires"] >= now}
    removed = len(store) - len(live)
    if removed:
        _save(live)
    return removed
