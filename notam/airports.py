"""Resolve airport codes to ICAO (the FAA feed is keyed by ICAO).

Accepts IATA (3-letter) or ICAO (4-char) and returns the ICAO code. The
IATA->ICAO table is built from the public OurAirports dataset
(iata_icao.json, ~8500 codes). A 4-char code is assumed to be ICAO already; an
unknown 3-letter code is returned unchanged (it will simply yield no NOTAMs).
"""

from __future__ import annotations

import json
import os

_FILE = os.path.join(os.path.dirname(__file__), "iata_icao.json")
_table: dict | None = None


def _lookup() -> dict:
    global _table
    if _table is None:
        with open(_FILE, encoding="utf-8") as f:
            _table = json.load(f)
    return _table


def to_icao(code: str) -> str:
    """IATA or ICAO in -> ICAO out."""
    code = code.strip().upper()
    if len(code) == 3:
        return _lookup().get(code, code)
    return code
