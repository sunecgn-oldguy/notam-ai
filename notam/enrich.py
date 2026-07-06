"""Enrich a raw NOTAM with cleaned text and parsed Q-line data.

This ties step 2 (clean) and step 3 (qline) together. It takes a raw NOTAM dict
from faa.fetch_notams and returns a copy with two extra fields:
  - "body"  : the cleaned, abbreviation-expanded E) text (human readable)
  - "qline" : the parsed Q-line dict (area, altitude, subject) or None
"""

# Wiring — Used by: briefing.py (_process_airport) and main.py (_report_airport).
#          Calls: clean.py (clean) + qline.py (parse_qline). See ARCHITECTURE.md.

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


def d_field(raw: str) -> str:
    """Extract the D) schedule field (text after 'D)', before 'E)'), if present."""
    e = raw.find("E)")
    region = raw[:e] if e != -1 else raw
    idx = region.find("D)")
    if idx == -1:
        return ""
    return " ".join(region[idx + 2:].split())


def enrich(notam: dict) -> dict:
    """Return a copy of the NOTAM with cleaned body text, Q-line and D) schedule."""
    return {
        **notam,
        "body": clean(body_text(notam["raw"])),
        "qline": parse_qline(notam["raw"]),
        "d": d_field(notam["raw"]),
    }
