"""Flight-time relevance (step 6).

Deterministic date/time gate: a NOTAM is only surfaced if its active period
overlaps the planned flight window. Nothing is deleted — out-of-window NOTAMs
are just collapsed.

NOTAM start/end arrive from the FAA feed as strings:
  - "08/04/2025 1300"     -> MM/DD/YYYY HHMM (UTC)
  - "PERM"                -> permanent (open-ended)
  - "07/16/2026 2359EST"  -> 'EST' = estimated end; the marker is ignored

Note (known limitation): the optional daily time-band (the "D)" field, e.g.
0700-1500) is not yet applied, so a NOTAM active on the date but only during a
daily window still shows. That over-shows, which is the safe direction.
"""

from __future__ import annotations

from datetime import datetime, timezone

from notam import schedule


def parse_notam_dt(s: str) -> datetime | None:
    """Parse a NOTAM start/end string. None means permanent / open-ended."""
    s = (s or "").upper().replace("EST", "").strip()
    if not s or s.startswith("PERM"):
        return None
    try:
        return datetime.strptime(s, "%m/%d/%Y %H%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def is_active_during(notam: dict, start: datetime, end: datetime) -> bool:
    """True if the NOTAM is active during the flight window [start, end].

    Two gates: the B)/C) validity period must overlap the window, AND the D)
    daily schedule (if parseable) must not confidently rule it out. An
    unparseable or absent D) never hides the NOTAM (safe default).
    """
    if not _bc_overlap(notam, start, end):
        return False
    return schedule.active_during(notam.get("d", ""), start, end) is not False


def _bc_overlap(notam: dict, start: datetime, end: datetime) -> bool:
    """Does the NOTAM's B)/C) validity period overlap the flight window?"""
    n_start = parse_notam_dt(notam.get("start", ""))
    n_end = parse_notam_dt(notam.get("end", ""))
    # If a start won't parse, be safe and treat it as already active.
    starts_ok = (n_start is None) or (n_start <= end)
    ends_ok = (n_end is None) or (n_end >= start)
    return starts_ok and ends_ok
