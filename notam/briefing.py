"""Assemble a structured route briefing (shared by the CLI and the server).

Pure stdlib — the web framework lives only in server.py. Returns plain dicts so
it serialises straight to JSON. This is the one place the whole pipeline is wired
together: fetch -> enrich -> classify -> time-gate -> AI summary (cached).
"""

from __future__ import annotations

from datetime import datetime

from notam.enrich import enrich
from notam.faa import fetch_notams
from notam.llm import summarise
from notam.relevance import classify
from notam.timing import is_active_during


def build(airports: list[tuple[str, str]],
          window: tuple[datetime, datetime]) -> dict:
    """airports: list of (icao, role). window: (start, end). Returns a briefing dict."""
    out = []
    for icao, role in airports:
        notams = [enrich(n) for n in fetch_notams(icao)]
        for n in notams:
            n["relevance"] = classify(n)
            n["active"] = is_active_during(n, *window)

        active = [n for n in notams if n["active"]]
        high = [n for n in active if n["relevance"]["tier"] == "high"]
        low = [n for n in active if n["relevance"]["tier"] == "low"]
        inactive = [n for n in notams if not n["active"]]

        out.append({
            "icao": icao,
            "role": role,
            "name": notams[0]["airport_name"] if notams else "",
            "counts": {"raw": len(notams), "relevant": len(high),
                       "military": len(low), "inactive": len(inactive)},
            "relevant": [_view(n) for n in high],
            "military_ids": [n["id"] for n in low],
            "inactive_ids": [n["id"] for n in inactive],
        })
    return {"airports": out}


def _view(n: dict) -> dict:
    q = n["qline"]
    return {
        "id": n["id"],
        "category": n["relevance"]["category"],
        "summary": summarise(n),          # AI (or deterministic) — cached
        "raw": n["raw"],                  # original NOTAM, always available
        "start": n["start"],
        "end": n["end"],
        "area": None if not q else {
            "lat": q["lat"], "lon": q["lon"], "radius_nm": q["radius_nm"],
            "fl_lower": q["fl_lower"], "fl_upper": q["fl_upper"],
        },
    }
