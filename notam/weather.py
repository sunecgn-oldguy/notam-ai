"""Fetch METAR/TAF and classify aerodrome weather into 4 colour categories.

Source: aviationweather.gov (US NWS) — free, no key, global METAR/TAF. Same
philosophy as the FAA NOTAM source. METAR/TAF are shown raw (pilots read them
natively); we only compute a colour category deterministically from visibility
and ceiling — no AI, no tokens, no hallucination.

Categories (the WORSE of visibility / ceiling decides), per the pilot's spec:
  CAVOK     green   — CAVOK, or vis >= 10 km AND ceiling >= 5000 ft
  GOOD      blue    — vis >= 5 km  AND ceiling >= 1500 ft
  MARGINAL  amber   — vis >= 1 km  AND ceiling >= 500 ft
  LOW VIS   red     — below that (vis < 1 km OR ceiling < 500 ft)
"""

from __future__ import annotations

import re
import urllib.request

_METAR_URL = "https://aviationweather.gov/api/data/metar?ids={}&format=raw"
_TAF_URL = "https://aviationweather.gov/api/data/taf?ids={}&format=raw"

_SM = re.compile(r"\b(?:(\d+)\s+)?(\d+/\d+|\d+)SM\b")
_METRIC_VIS = re.compile(r"(\d{4})(NDV)?")
_CEILING = re.compile(r"\b(?:BKN|OVC|VV)(\d{3})\b")


def fetch(icao: str) -> dict:
    """Return {'metar', 'taf', 'category'} for one ICAO. category may be None."""
    metar = _get(_METAR_URL.format(icao))
    taf = _get(_TAF_URL.format(icao))
    up = metar.upper()
    return {
        "metar": metar,
        "taf": taf,
        "category": _classify("CAVOK" in up, _visibility_m(up), _ceiling_ft(up)),
    }


def _classify(cavok: bool, vis_m: int | None, ceil_ft: int | None):
    if cavok:
        return "CAVOK"
    if vis_m is None and ceil_ft is None:
        return None                        # couldn't read it — show neutral
    v = vis_m if vis_m is not None else 99999
    c = ceil_ft if ceil_ft is not None else 99999
    if v < 1000 or c < 500:
        return "LOW VIS"
    if v < 5000 or c < 1500:
        return "MARGINAL"
    if v < 10000 or c < 5000:
        return "GOOD"
    return "CAVOK"


def _visibility_m(metar: str) -> int | None:
    if "CAVOK" in metar:
        return 10000
    m = _SM.search(metar)                  # US statute miles, incl. fractions
    if m:
        whole = int(m.group(1)) if m.group(1) else 0
        part = m.group(2)
        val = whole + (int(part.split("/")[0]) / int(part.split("/")[1])
                       if "/" in part else int(part))
        return int(val * 1609)
    for tok in metar.split():              # metric 4-digit metres
        mm = _METRIC_VIS.fullmatch(tok)
        if mm:
            v = int(mm.group(1))
            return 10000 if v >= 9999 else v
    return None


def _ceiling_ft(metar: str) -> int | None:
    if "CAVOK" in metar:
        return None
    heights = [int(h) * 100 for h in _CEILING.findall(metar)]   # lowest BKN/OVC/VV
    return min(heights) if heights else None


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "NOTAM-AI"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", "replace").strip()
    except Exception:
        return ""
