"""Content-addressed cache for AI-processed NOTAMs (the big token saver).

A NOTAM is identical for every pilot, so turning one raw NOTAM into readable
text only needs to happen once in the world. We key on a hash of the raw NOTAM
text: identical text -> identical result, reused for free by everyone. Only
NOTAMs whose exact text we have never seen cost tokens.

Because the key *is* the text, a NOTAM that FAA changes gets a new hash and is
re-processed automatically — we can never show a stale translation of changed
text.

Thread-safe: the summaries run in parallel (see briefing.py), so the store is an
in-memory dict guarded by a lock, written through to disk atomically. This holds
public NOTAM translations only, never user routes. Prototype storage is one JSON
file; in the real server swap it for Redis/SQLite behind the same functions.
"""

# Wiring — Used by: llm.py (get before an AI call, put after). Calls nothing
#          internal. See ARCHITECTURE.md.
#
# ⚠️ EFFEKTIVITET: put() skriver HELE JSON-filen om under låsen ved hvert kald.
# Med 16 parallelle AI-tråde der bliver færdige næsten samtidig, betyder det N
# fulde fil-omskrivninger pr. briefing, alle serialiseret på låsen. Fint i en
# prototype; batch skrivningerne (eller skift til SQLite) før skala. Bemærk også
# at cleanup() aldrig kaldes nogen steder — cachen vokser ubegrænset (på Renders
# free-disk nulstilles den dog ved redeploy). Se review-noten.

from __future__ import annotations

import hashlib
import json
import os
import threading
import time

_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_FILE = os.path.join(_DIR, "notam_cache.json")

_lock = threading.Lock()
_store: dict | None = None          # in-memory cache, loaded once, guarded by _lock


def key(raw: str) -> str:
    """Stable content hash of a raw NOTAM (whitespace-normalised)."""
    norm = " ".join(raw.split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def get(raw: str, now: float | None = None) -> str | None:
    """Return the cached processed text for this raw NOTAM, or None on a miss."""
    now = time.time() if now is None else now
    with _lock:
        _ensure_loaded()
        entry = _store.get(key(raw))
    if entry is None:
        return None
    if entry.get("expires") is not None and entry["expires"] < now:
        return None                        # expired — treat as a miss
    return entry["text"]


def put(raw: str, text: str, expires: float | None = None, model: str = "") -> None:
    """Store the processed text for this raw NOTAM (thread-safe, write-through)."""
    with _lock:
        _ensure_loaded()
        _store[key(raw)] = {
            "text": text, "expires": expires, "model": model, "stored": time.time(),
        }
        _write_file(_store)


def cleanup(now: float | None = None) -> int:
    """Drop entries whose NOTAM has expired. Returns how many were removed."""
    global _store
    now = time.time() if now is None else now
    with _lock:
        _ensure_loaded()
        live = {k: v for k, v in _store.items()
                if v.get("expires") is None or v["expires"] >= now}
        removed = len(_store) - len(live)
        if removed:
            _store = live
            _write_file(_store)
    return removed


# --- internals (all called under _lock) ---

def _ensure_loaded() -> None:
    global _store
    if _store is None:
        _store = _read_file()


def _read_file() -> dict:
    if not os.path.exists(_FILE):
        return {}
    try:
        with open(_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _write_file(store: dict) -> None:
    os.makedirs(_DIR, exist_ok=True)
    tmp = _FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _FILE)                  # atomic — a concurrent read never sees half a file
