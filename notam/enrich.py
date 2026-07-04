"""Enrich a raw NOTAM with cleaned text and parsed Q-line data.

This ties step 2 (clean) and step 3 (qline) together. It takes a raw NOTAM dict
from faa.fetch_notams and returns a copy with two extra fields:
  - "body"  : the cleaned, abbreviation-expanded E) text (human readable)
  - "qline" : the parsed Q-line dict (area, altitude, subject) or None
"""

from __future__ import annotations

from notam.clean import clean
from notam.qline import parse_qline


def body_text(raw: str) -> str:
    """Extract the E) message body from a raw ICAO NOTAM, as one clean line."""
    idx = raw.find("E)")
    if idx == -1:
        return ""
    text = raw[idx + 2:]
    # The body ends where the optional F)/G) lower/upper limits begin.
    for marker in ("\nF)", "\nG)"):
        cut = text.find(marker)
        if cut != -1:
            text = text[:cut]
    return " ".join(text.split())


def enrich(notam: dict) -> dict:
    """Return a copy of the NOTAM with cleaned body text and parsed Q-line."""
    return {
        **notam,
        "body": clean(body_text(notam["raw"])),
        "qline": parse_qline(notam["raw"]),
    }
