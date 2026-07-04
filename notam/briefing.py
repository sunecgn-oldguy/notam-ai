"""Assemble a structured route briefing (shared by the CLI and the server).

Pure stdlib — the web framework lives only in server.py. Returns plain dicts so
it serialises straight to JSON. This is the one place the whole pipeline is wired
together: fetch -> enrich -> classify -> time-gate -> AI summary (cached).

The two I/O-bound steps run concurrently: the FAA fetches (one per airport) and
the AI summaries (one per relevant NOTAM). The cache is thread-safe (see
cache.py), so parallel summaries never clobber each other.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from notam.enrich import enrich
from notam.faa import fetch_notams
from notam.llm import summarise
from notam.relevance import classify
from notam.timing import is_active_during

_FETCH_WORKERS = 6
_AI_WORKERS = 8


def build(airports: list[tuple[str, str]],
          window: tuple[datetime, datetime]) -> dict:
    """airports: list of (icao, role). window: (start, end). Returns a briefing dict."""
    # 1. Fetch + classify every airport concurrently.
    with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
        groups = list(pool.map(lambda ar: _process_airport(ar, window), airports))

    # 2. Translate all relevant NOTAMs (across all airports) concurrently — cached.
    _summarise_parallel([n for g in groups for n in g["high"]])

    # 3. Assemble the response.
    return {"airports": [_airport_view(g) for g in groups]}


def _process_airport(airport: tuple[str, str],
                     window: tuple[datetime, datetime]) -> dict:
    icao, role = airport
    notams = [enrich(n) for n in fetch_notams(icao)]
    for n in notams:
        n["relevance"] = classify(n)
        n["active"] = is_active_during(n, *window)

    # Military first (all disregarded); then split the civil NOTAMs by activity.
    military = [n for n in notams if n["relevance"]["tier"] == "low"]
    civil = [n for n in notams if n["relevance"]["tier"] != "low"]
    return {
        "icao": icao, "role": role,
        "name": notams[0]["airport_name"] if notams else "",
        "notams": notams, "military": military,
        "high": [n for n in civil if n["active"]],
        "inactive": [n for n in civil if not n["active"]],
    }


def _summarise_parallel(notams: list[dict]) -> None:
    """Fill n['_summary'] for each NOTAM, running the AI calls concurrently."""
    if not notams:
        return

    def work(n):
        try:
            n["_summary"] = summarise(n)
        except Exception:                     # one failed call never kills the briefing
            n["_summary"] = n.get("body", "")

    with ThreadPoolExecutor(max_workers=_AI_WORKERS) as pool:
        list(pool.map(work, notams))


def _airport_view(g: dict) -> dict:
    return {
        "icao": g["icao"],
        "role": g["role"],
        "name": g["name"],
        "counts": {"raw": len(g["notams"]), "relevant": len(g["high"]),
                   "military": len(g["military"]), "inactive": len(g["inactive"])},
        "relevant": [_view(n) for n in g["high"]],
        "military": [_raw_view(n) for n in g["military"]],
        "inactive": [_raw_view(n) for n in g["inactive"]],
    }


def _view(n: dict) -> dict:
    q = n["qline"]
    return {
        "id": n["id"],
        "category": n["relevance"]["category"],
        "summary": n.get("_summary") or summarise(n),   # precomputed in step 2
        "raw": n["raw"],                  # original NOTAM, always available
        "start": n["start"],
        "end": n["end"],
        "area": None if not q else {
            "lat": q["lat"], "lon": q["lon"], "radius_nm": q["radius_nm"],
            "fl_lower": q["fl_lower"], "fl_upper": q["fl_upper"],
        },
    }


def _raw_view(n: dict) -> dict:
    """id + full original text only — no AI spent on disregarded / out-of-window NOTAMs."""
    return {"id": n["id"], "raw": n["raw"]}
