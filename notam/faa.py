"""Fetch raw NOTAMs — two interchangeable sources behind one function.

  NOTAM_SOURCE=web  (default) — the free public FAA NOTAM Search web endpoint
                    (undocumented; fine for the prototype). Returns JSON with the
                    raw ICAO message per NOTAM.
  NOTAM_SOURCE=nms  — the OFFICIAL FAA NMS-API (OAuth2, request/response REST).
                    Confirmed to carry European NOTAMs and to return the full raw
                    ICAO text (notamTranslation[ICAO].formattedText), so it maps
                    onto the exact same dict shape — see _normalise_nms.

Both return the same list of small dicts (id/airport/start/end/raw/…), so nothing
downstream (enrich, relevance, timing, llm) changes when you switch sources.

NMS-API config (server env vars — the KEY/SECRET come from FAA's onboarding Excel;
NEVER hardcode them):
  FAA_NMS_KEY / FAA_NMS_SECRET   OAuth2 client_id / client_secret
  FAA_NMS_HOST                   default https://api-staging.cgifederal-aim.com
                                 (prod: https://api-nms.aim.faa.gov)
  FAA_NMS_MIN_INTERVAL           seconds between NMS calls (staging spike-arrest is
                                 1/sec; default 1.1). Set lower once prod limits allow.

Only the Python standard library is used, so there is nothing to install.
"""

# Wiring — Used by: briefing.py (_process_airport) and main.py (_report_airport).
#          Calls nothing internal; talks straight to the FAA over HTTP.
#          See ARCHITECTURE.md for the full pipeline map.
#
# ROBUSTHED: fetch_notams() kaster ved FAA-fejl (timeout / 500 / ikke-JSON / 429).
# Det er MED VILJE — kaldere bestemmer selv hvordan de reagerer. Produktionsvejen
# (briefing.py:_process_airport) fanger det per plads og markerer pladsen med et
# error-flag, så én plads' fejl aldrig vælter hele ruten.

from __future__ import annotations

import base64
import html
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime


def fetch_notams(icao: str) -> list[dict]:
    """Return the active NOTAMs for one ICAO airport code (e.g. "EDDK").

    Each NOTAM is a small dict with clear field names. The full raw ICAO text
    (including the Q-line) is kept under "raw" so later steps can parse the
    affected area and altitude from it.
    """
    if os.environ.get("NOTAM_SOURCE", "web").lower() == "nms":
        return _fetch_nms(icao)
    return _fetch_web(icao)


# ---------------- source: web (default, undocumented FAA NOTAM Search) ----------

_ENDPOINT = "https://notams.aim.faa.gov/notamSearch/search"


def _fetch_web(icao: str) -> list[dict]:
    body = urllib.parse.urlencode(
        {"searchType": "0", "designatorsForLocation": icao}
    ).encode()
    req = urllib.request.Request(
        _ENDPOINT,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    return [_normalise_web(n) for n in data.get("notamList", [])]


def _normalise_web(n: dict) -> dict:
    """Keep only the fields we use, with clear names."""
    return {
        "id": n.get("notamNumber", ""),
        "airport": n.get("facilityDesignator", ""),
        "airport_name": n.get("airportName", ""),
        "keyword": n.get("keyword", ""),
        "issued": n.get("issueDate", ""),
        "start": n.get("startDate", ""),
        "end": n.get("endDate", ""),
        # Decode HTML entities (&apos; &amp;) the feed leaves in the text, so the
        # original NOTAM we display reads cleanly — the true character, not an edit.
        "raw": html.unescape((n.get("icaoMessage") or "").strip()),
    }


# ---------------- source: nms (official FAA NMS-API) ----------------------------

_NMS_DEFAULT_HOST = "https://api-staging.cgifederal-aim.com"
_nms_lock = threading.Lock()
_nms_token = {"value": None, "expires": 0.0}   # cached bearer token (~30 min TTL)
_nms_gate = threading.Lock()
_nms_last = 0.0                                # time of last NMS request (throttle)


def _nms_host() -> str:
    return os.environ.get("FAA_NMS_HOST", _NMS_DEFAULT_HOST).rstrip("/")


def _nms_bearer() -> str:
    """A valid OAuth2 bearer token, fetched once and reused until ~1 min before it
    expires. Thread-safe so 16 parallel fetches share a single token."""
    now = time.time()
    with _nms_lock:
        if _nms_token["value"] and now < _nms_token["expires"] - 60:
            return _nms_token["value"]
        key = os.environ["FAA_NMS_KEY"]
        secret = os.environ["FAA_NMS_SECRET"]
        auth = base64.b64encode(f"{key}:{secret}".encode()).decode()
        req = urllib.request.Request(
            _nms_host() + "/v1/auth/token",
            data=b"grant_type=client_credentials",
            headers={"Authorization": "Basic " + auth,
                     "Content-Type": "application/x-www-form-urlencoded"},
            method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            d = json.load(resp)
        _nms_token["value"] = d["access_token"]
        _nms_token["expires"] = now + int(d.get("expires_in", 1799))
        return _nms_token["value"]


def _nms_throttle() -> None:
    """Serialise NMS calls to at most 1 per FAA_NMS_MIN_INTERVAL seconds — the
    staging spike-arrest is 1/sec and the app fetches airports concurrently."""
    global _nms_last
    interval = float(os.environ.get("FAA_NMS_MIN_INTERVAL", "1.1"))
    with _nms_gate:
        wait = _nms_last + interval - time.time()
        if wait > 0:
            time.sleep(wait)
        _nms_last = time.time()


def _fetch_nms(icao: str) -> list[dict]:
    token = _nms_bearer()
    _nms_throttle()
    url = _nms_host() + "/nmsapi/v1/notams?location=" + urllib.parse.quote(icao)
    req = urllib.request.Request(
        url, headers={"Authorization": "Bearer " + token,
                      "nmsResponseFormat": "GEOJSON"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    feats = ((data.get("data") or {}).get("geojson")) or []
    return [_normalise_nms(f) for f in feats]


def _normalise_nms(feat: dict) -> dict:
    """Map one NMS GeoJSON feature to the same dict shape as the web source. The
    full ICAO text (with Q-line) comes from notamTranslation[type=ICAO]."""
    core = (feat.get("properties") or {}).get("coreNOTAMData") or {}
    n = core.get("notam") or {}
    raw = ""
    for t in core.get("notamTranslation") or []:
        if t.get("type") == "ICAO" and t.get("formattedText"):
            raw = t["formattedText"]
            break
    return {
        "id": n.get("number", ""),
        "airport": n.get("icaoLocation") or n.get("location", ""),
        "airport_name": "",                  # NMS gives no friendly name
        "keyword": "",                       # no FAA 'keyword'; military still caught via body text
        "issued": _nms_dt(n.get("issued", "")),
        "start": _nms_dt(n.get("effectiveStart", "")),
        "end": _nms_dt(n.get("effectiveEnd", "")),
        "raw": html.unescape((raw or "").strip()),
    }


def _nms_dt(s: str) -> str:
    """NMS ISO time (2025-08-04T13:00:00Z) -> the "MM/DD/YYYY HHMM" string that
    timing.parse_notam_dt already understands. 'PERM'/empty pass straight through."""
    s = (s or "").strip()
    if not s or s.upper().startswith("PERM"):
        return s
    try:
        return datetime.strptime(s[:16], "%Y-%m-%dT%H:%M").strftime("%m/%d/%Y %H%M")
    except ValueError:
        return ""
