"""Parse the ICAO NOTAM Q-line (step 3).

The Q-line packs the structured metadata that lets us filter with plain math
instead of guessing. Example:

    Q) EDGG/QNMXX/IV/BO /AE/000/999/5047N00736E025
       |    |     |  |   |  |   |   |
       FIR  Qcode |  |   |  |   |   coordinates + radius
                  |  purpose scope
                  traffic     lower FL / upper FL

  - Qcode: 5 chars. chars 2-3 = subject, chars 4-5 = condition/status.
  - lower/upper are flight levels in hundreds of feet (000 = surface,
    999 = unlimited).
  - coordinates: DDMM[N/S]DDDMM[E/W] then a 3-digit radius in nautical miles.

Returns a dict of parsed values, or None if the raw text has no usable Q-line.
"""

from __future__ import annotations

import re

# Matches the coordinate + radius block, e.g. "5047N00736E025".
_COORD = re.compile(r"(\d{2})(\d{2})([NS])(\d{3})(\d{2})([EW])(\d{3})")


def _dm_to_degrees(deg: str, minutes: str, hemi: str) -> float:
    """Degrees+minutes with a hemisphere letter -> signed decimal degrees."""
    value = int(deg) + int(minutes) / 60
    return -value if hemi in ("S", "W") else value


def parse_qline(raw: str) -> dict | None:
    """Extract the structured Q-line values from a raw ICAO NOTAM."""
    line = _find_qline(raw)
    if line is None:
        return None

    # Everything after "Q)", split on "/". Purpose/scope carry trailing spaces.
    parts = [p.strip() for p in line.split("/")]
    if len(parts) < 8:
        return None

    fir, qcode, traffic, purpose, scope, lower, upper, coord = parts[:8]

    m = _COORD.match(coord)
    if not m:
        return None
    lat = _dm_to_degrees(m.group(1), m.group(2), m.group(3))
    lon = _dm_to_degrees(m.group(4), m.group(5), m.group(6))
    radius_nm = int(m.group(7))

    return {
        "fir": fir,
        "qcode": qcode,
        "q_subject": qcode[1:3] if len(qcode) >= 3 else "",
        "q_condition": qcode[3:5] if len(qcode) >= 5 else "",
        "traffic": traffic,
        "purpose": purpose,
        "scope": scope,
        "fl_lower": int(lower) if lower.isdigit() else None,
        "fl_upper": int(upper) if upper.isdigit() else None,
        "lat": round(lat, 5),
        "lon": round(lon, 5),
        "radius_nm": radius_nm,
    }


def _find_qline(raw: str) -> str | None:
    """Return the text of the Q-line (after the 'Q)' marker), if present."""
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("Q)"):
            return line[2:].strip()
    return None
