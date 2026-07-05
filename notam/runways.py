"""Runways per airport + the wind-favoured landing direction.

Data: notam/runways.json (built from OurAirports — see tools/build_runways.py),
keyed by ICAO. Headings are degrees TRUE, the same reference as METAR wind, so
the favoured end is a direct comparison — no magnetic variation involved.

'Favoured' means only 'more into the wind of the two ends'. It is NOT a
runway-in-use call: noise abatement, preferential runways, ILS availability and
ATC all override wind. The UI says so; the pilot decides.
"""

from __future__ import annotations

import json
import os

_FILE = os.path.join(os.path.dirname(__file__), "runways.json")
_data: dict | None = None

_CALM_KT = 3            # below this (or variable) we don't guess a direction


def _load() -> dict:
    global _data
    if _data is None:
        with open(_FILE, encoding="utf-8") as f:
            _data = json.load(f)
    return _data


def _angle(a: int, b: int) -> int:
    """Smallest angle (0..180) between two bearings."""
    return abs((a - b + 180) % 360 - 180)


def view(icao: str, wind: dict | None = None) -> list[dict]:
    """Runways for an airport, longest first, each tagged with the wind-favoured
    end. wind: {"dir": int|None, "speed": int}. 'fav' is 'le' | 'he' | None."""
    rwys = _load().get((icao or "").upper(), [])
    wdir = (wind or {}).get("dir")
    wspd = (wind or {}).get("speed") or 0
    active = wdir is not None and wspd >= _CALM_KT      # calm/variable -> no pick

    out = []
    for r in rwys:
        fav = None
        if active and r["le_hdg"] is not None and r["he_hdg"] is not None:
            fav = "le" if _angle(wdir, r["le_hdg"]) < _angle(wdir, r["he_hdg"]) else "he"
        out.append({**r, "fav": fav})
    return out
