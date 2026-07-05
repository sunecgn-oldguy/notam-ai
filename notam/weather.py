"""Fetch METAR/TAF and classify aerodrome weather into 4 colour categories.

Source: aviationweather.gov (US NWS) — free, no key, global METAR/TAF. Same
philosophy as the FAA NOTAM source. METAR/TAF are shown raw (pilots read them
natively); we only compute a colour category deterministically — no AI.

The badge colour reflects the FORECAST during the flight window (the worst
category a TAF period predicts while you're there); it falls back to the current
METAR when there is no usable TAF.

Categories (the WORSE of visibility / ceiling decides). CAVOK is shown ONLY when
the report literally says CAVOK; good-but-not-CAVOK conditions read GOOD.
  CAVOK     green   — the report literally says CAVOK
  GOOD      green   — vis >= 10 km  AND ceiling >= 5000 ft (but not a reported CAVOK)
  OK        blue    — vis >= 5 km   AND ceiling >= 1500 ft
  MARGINAL  amber   — vis > 550 m   AND ceiling > 200 ft
  LOW VIS   red     — at/below Cat I minima (vis <= 550 m OR ceiling <= 200 ft)
"""

from __future__ import annotations

import re
import urllib.request
from datetime import datetime, timedelta

_METAR_URL = "https://aviationweather.gov/api/data/metar?ids={}&format=raw"
_TAF_URL = "https://aviationweather.gov/api/data/taf?ids={}&format=raw"

_SM = re.compile(r"\bM?(?:(\d+)\s+)?(\d+/\d+|\d+)SM\b")
_METRIC_VIS = re.compile(r"(\d{4})(NDV)?")
_CEILING = re.compile(r"\b(?:BKN|OVC|VV)(\d{3})\b")
_PERIOD = re.compile(r"\b(\d{2})(\d{2})/(\d{2})(\d{2})\b")
_MARKER = re.compile(r"\b(FM\d{6}|BECMG|TEMPO|PROB\d{2})\b")
_HAS_VIS = re.compile(r"\b(\d{4}(?:NDV)?|\d+/\d+SM|\d+SM|CAVOK)\b")
_HAS_CLOUD = re.compile(r"\b(?:FEW|SCT|BKN|OVC|VV|SKC|NSC|NCD|CLR)\d*\b")
_WIND = re.compile(r"\b(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?(KT|MPS)\b")
_SEVERITY = {"CAVOK": 0, "GOOD": 1, "OK": 2, "MARGINAL": 3, "LOW VIS": 4}
_WINDY_KT = 20                               # steady or gust above this flags "Windy"


def fetch(icao: str, window: tuple | None = None) -> dict:
    """Return METAR/TAF and colour categories. 'category' is the badge colour:
    the TAF forecast during the flight window, or the current METAR as fallback."""
    metar = _get(_METAR_URL.format(icao))
    taf = _get(_TAF_URL.format(icao))
    up = metar.upper()
    metar_cat = _classify("CAVOK" in up, _visibility_m(up), _ceiling_ft(up))
    taf_cat = taf_category(taf, window[0], window[1]) if window else None
    wind = _wind(up)
    windy = max(wind["speed"], wind["gust"] or 0) > _WINDY_KT      # METAR now
    if window and taf_windy(taf, window[0], window[1]):            # or TAF in the window
        windy = True
    return {
        "metar": metar, "taf": taf,
        "metar_category": metar_cat, "taf_category": taf_cat,
        "category": taf_cat or metar_cat,
        "wind": wind, "windy": windy,
    }


def _wind(metar: str) -> dict:
    """Surface wind from a METAR: {'dir': deg true|None (VRB), 'speed': kt,
    'gust': kt|None}. dir is None for variable/calm; speeds are knots."""
    m = _WIND.search(metar.upper())
    if not m:
        return {"dir": None, "speed": 0, "gust": None}
    to_kt = 1.94384 if m.group(4) == "MPS" else 1
    spd = round(int(m.group(2)) * to_kt)
    gust = round(int(m.group(3)) * to_kt) if m.group(3) else None
    calm = spd == 0 or m.group(1) == "VRB"      # no usable direction
    return {
        "dir": None if calm else int(m.group(1)),   # 360 = north (000 = calm)
        "speed": spd, "gust": gust,
    }


def _wind_kt(text: str):
    """Max wind (steady or gust) in kt from a wind group in text, or None if the
    text has no wind group at all (so callers can carry the previous wind forward)."""
    if not _WIND.search(text):
        return None
    w = _wind(text)
    return max(w["speed"], w["gust"] or 0)


def taf_category(taf: str, ws: datetime, we: datetime):
    """Worst forecast category during [ws, we], or None if unparseable."""
    cats = [c for c in (_classify(cav, vis, ceil)
                        for cav, vis, ceil, _ in _taf_conditions(taf, ws, we)) if c]
    return max(cats, key=lambda c: _SEVERITY[c]) if cats else None


def taf_windy(taf: str, ws: datetime, we: datetime) -> bool:
    """True if any in-window TAF period forecasts wind (steady or gust) > 20 kt."""
    return any(w is not None and w > _WINDY_KT
               for _, _, _, w in _taf_conditions(taf, ws, we))


def _taf_conditions(taf: str, ws: datetime, we: datetime):
    """Per-period (cavok, vis_m, ceil_ft, wind_kt) for every TAF period that
    overlaps [ws, we]. vis/ceiling/wind carry forward through changes that don't
    restate them; wind_kt = max(steady, gust). [] if the TAF can't be parsed."""
    if not taf:
        return []
    up = " ".join(taf.upper().split())
    v = _PERIOD.search(up)
    if not v:
        return []
    valid_start = _ddhh(v.group(1), v.group(2), ws)
    valid_end = _ddhh(v.group(3), v.group(4), ws)
    if valid_start is None or valid_end is None:
        return []

    body = up[v.end():]
    marks = list(_MARKER.finditer(body))
    perms, temps = [], []                    # perms: (start, text); temps: (start, end, text)

    base = body[:marks[0].start()] if marks else body
    perms.append((valid_start, base))

    for i, mk in enumerate(marks):
        text = body[mk.end():marks[i + 1].start() if i + 1 < len(marks) else len(body)]
        kw = mk.group(1)
        if kw.startswith("FM"):
            start = _ddhh(kw[2:4], kw[4:6], ws)
            if start:
                perms.append((start + timedelta(minutes=int(kw[6:8])), text))
        else:
            pm = _PERIOD.search(text)
            if not pm:
                continue
            ps, pe = _ddhh(pm.group(1), pm.group(2), ws), _ddhh(pm.group(3), pm.group(4), ws)
            cond = text[pm.end():]
            if kw == "BECMG" and ps:
                perms.append((ps, cond))
            elif ps and pe:                  # TEMPO / PROB
                temps.append((ps, pe, cond))

    out = []
    # permanent timeline, carrying vis/ceiling/wind forward through partial changes
    perms = sorted((p for p in perms if p[0] is not None), key=lambda p: p[0])
    cav, vis, ceil, wind = False, None, None, None
    for j, (start, text) in enumerate(perms):
        if "CAVOK" in text:
            cav, vis, ceil = True, 10000, None
        else:
            if _HAS_VIS.search(text):
                cav, vis = False, _visibility_m(text)
            if _HAS_CLOUD.search(text):
                cav, ceil = False, _ceiling_ft(text)
        wk = _wind_kt(text)
        if wk is not None:
            wind = wk
        end = perms[j + 1][0] if j + 1 < len(perms) else valid_end
        if start < we and end > ws:          # overlaps the flight window
            out.append((cav, vis, ceil, wind))

    for ps, pe, text in temps:               # temporary deviations in the window
        if ps < we and pe > ws:
            out.append(("CAVOK" in text, _visibility_m(text),
                        _ceiling_ft(text), _wind_kt(text)))
    return out


def _ddhh(dd: str, hh: str, ref: datetime):
    """A TAF day-hour (DDHH) resolved to a datetime, anchored on the flight date."""
    day, hour = int(dd), int(hh)
    extra, hour = divmod(hour, 24)           # HH may be 24 (= next day 00)
    year, month = ref.year, ref.month
    if day < ref.day - 20:                   # TAF crosses into next month
        month += 1
        if month > 12:
            month, year = 1, year + 1
    try:
        return datetime(year, month, day, hour, tzinfo=ref.tzinfo) + timedelta(days=extra)
    except ValueError:
        return None


def _classify(cavok: bool, vis_m: int | None, ceil_ft: int | None):
    if cavok:
        return "CAVOK"                # ONLY when the report literally says CAVOK
    if vis_m is None and ceil_ft is None:
        return None
    v = vis_m if vis_m is not None else 99999
    c = ceil_ft if ceil_ft is not None else 99999
    if v <= 550 or c <= 200:          # at/below Cat I minima (550 m RVR / 200 ft)
        return "LOW VIS"
    if v < 5000 or c < 1500:
        return "MARGINAL"
    if v < 10000 or c < 5000:
        return "OK"
    return "GOOD"                     # good VMC by the numbers — but not a reported CAVOK


def _visibility_m(metar: str) -> int | None:
    if "CAVOK" in metar:
        return 10000
    m = _SM.search(metar)
    if m:
        whole = int(m.group(1)) if m.group(1) else 0
        part = m.group(2)
        val = whole + (int(part.split("/")[0]) / int(part.split("/")[1])
                       if "/" in part else int(part))
        return int(val * 1609)
    for tok in metar.split():
        mm = _METRIC_VIS.fullmatch(tok)
        if mm:
            n = int(mm.group(1))
            return 10000 if n >= 9999 else n
    return None


def _ceiling_ft(metar: str) -> int | None:
    if "CAVOK" in metar:
        return None
    heights = [int(h) * 100 for h in _CEILING.findall(metar)]
    return min(heights) if heights else None


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "NOTAM-AI"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", "replace").strip()
    except Exception:
        return ""
