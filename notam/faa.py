"""Fetch raw NOTAMs from the FAA NOTAM Search service.

This is the free, public-domain FAA feed. For a personal prototype we use the
simple web search endpoint. When the app is published we switch to the official
FAA SWIM feed (same data, supported interface) — see memory/notam-data-source.md.

Only the Python standard library is used, so there is nothing to install.
"""

from __future__ import annotations

import html
import json
import urllib.parse
import urllib.request

_ENDPOINT = "https://notams.aim.faa.gov/notamSearch/search"


def fetch_notams(icao: str) -> list[dict]:
    """Return the active NOTAMs for one ICAO airport code (e.g. "EDDK").

    Each NOTAM is a small dict with clear field names. The full raw ICAO text
    (including the Q-line) is kept under "raw" so later steps can parse the
    affected area and altitude from it.
    """
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

    return [_normalise(n) for n in data.get("notamList", [])]


def _normalise(n: dict) -> dict:
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
        # original NOTAM we display reads cleanly — this is the true character,
        # not an edit. (The FAA's own data may still contain garbled repetition;
        # we show that faithfully rather than "fix" a malformed source.)
        "raw": html.unescape((n.get("icaoMessage") or "").strip()),
    }
