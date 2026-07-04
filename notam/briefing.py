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

        # Military first (all military is disregarded, active or not). Then, among
        # the civil NOTAMs, split by whether they're active in the flight window.
        military = [n for n in notams if n["relevance"]["tier"] == "low"]
        civil = [n for n in notams if n["relevance"]["tier"] != "low"]
        high = [n for n in civil if n["active"]]
        inactive = [n for n in civil if not n["active"]]

        out.append({
            "icao": icao,
            "role": role,
            "name": notams[0]["airport_name"] if notams else "",
            "counts": {"raw": len(notams), "relevant": len(high),
                       "military": len(military), "inactive": len(inactive)},
            "relevant": [_view(n) for n in high],
            "military": [_raw_view(n) for n in military],
            "inactive": [_raw_view(n) for n in inactive],
        })
    return {"airports": out}


def _raw_view(n: dict) -> dict:
    """id + full original text only — no AI spent on disregarded / out-of-window NOTAMs."""
    return {"id": n["id"], "raw": n["raw"]}


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
