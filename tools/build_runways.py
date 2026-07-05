"""Build notam/runways.json from the public OurAirports runways dataset.

Same source as iata_icao.json (public domain). Keyed by ICAO ident, so it
lines up with the FAA feed and our IATA->ICAO table. We keep only what the
runway line needs: both end idents, their TRUE headings, and the length.

Headings are degrees TRUE — the same reference as METAR wind — so the
wind-favoured runway can be computed directly, no magnetic variation needed.

Run:  python3 tools/build_runways.py
"""

from __future__ import annotations

import csv
import io
import json
import os
import urllib.request

_URL = "https://davidmegginson.github.io/ourairports-data/runways.csv"
_OUT = os.path.join(os.path.dirname(__file__), "..", "notam", "runways.json")


def _heading(raw: str, ident: str) -> int | None:
    """TRUE heading from the dataset; fall back to the ident (06 -> 060)."""
    raw = (raw or "").strip()
    if raw:
        try:
            return round(float(raw)) % 360
        except ValueError:
            pass
    digits = "".join(c for c in ident if c.isdigit())
    return (int(digits) * 10) % 360 if digits else None


def build() -> dict:
    with urllib.request.urlopen(_URL, timeout=60) as r:
        text = r.read().decode("utf-8", "replace")

    out: dict[str, list] = {}
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("closed") == "1":
            continue
        icao = (row.get("airport_ident") or "").strip().upper()
        le, he = (row.get("le_ident") or "").strip(), (row.get("he_ident") or "").strip()
        if not icao or not le or not he:
            continue
        try:
            length = int(row.get("length_ft") or 0)
        except ValueError:
            length = 0
        out.setdefault(icao, []).append({
            "le": le, "he": he,
            "le_hdg": _heading(row.get("le_heading_degT"), le),
            "he_hdg": _heading(row.get("he_heading_degT"), he),
            "len": length,
        })

    # Longest runway first — the one a pilot reads first.
    for rwys in out.values():
        rwys.sort(key=lambda x: x["len"], reverse=True)
    return out


if __name__ == "__main__":
    data = build()
    with open(_OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), sort_keys=True)
    size = os.path.getsize(_OUT)
    print(f"wrote {len(data)} airports, "
          f"{sum(len(v) for v in data.values())} runways, "
          f"{size / 1e6:.1f} MB -> {os.path.relpath(_OUT)}")
