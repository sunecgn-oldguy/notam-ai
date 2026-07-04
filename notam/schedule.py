"""Parse the NOTAM D) schedule field to decide activity during a flight window.

D) is the hardest NOTAM field — semi-free-text with many formats. We parse the
common, unambiguous ones and, crucially, fall back to "assume active" (never
hide) when we cannot parse it confidently. A NOTAM is moved out of the main list
only when we are SURE it is inactive.

    active_during(d, start, end) -> True | False | None
      True  : active at some moment in [start, end]
      False : confidently inactive during the window
      None  : no D) field, or a format we don't parse -> caller keeps it visible

Handled: H24; daily band(s) "0700-1630"; month+day(s)+band "JUN 26 0700-1630"
and cross-month range "JUN 29-JUL 04 0700-1630"; weekday+band "MON-FRI 0800-1700".
Not handled (-> None): sunrise/sunset (SR/SS) and anything unusual.
All times are UTC (as NOTAM times and the flight window are).
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta

_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT",
     "NOV", "DEC"], 1)}
_DOW = {d: i for i, d in enumerate(
    ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"])}

_BAND = re.compile(r"\b(\d{4})-(\d{4})\b")


def active_during(d: str, start: datetime, end: datetime):
    """True / False / None — see module docstring."""
    d = " ".join((d or "").upper().split())
    if not d:
        return None                          # no D) — caller uses B/C only
    if re.fullmatch(r"H24\.?", d):
        return True

    rules = []
    for seg in d.split(","):
        rule = _parse_segment(seg)
        if rule is None:
            return None                      # a format we don't understand
        rules.append(rule)

    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= end:
        w1, w2 = _window_minutes_on(day.date(), start, end)
        if w1 is not None:
            for rule in rules:
                if rule["applies"](day.date()):
                    for b1, b2 in rule["bands"]:
                        if _overlaps(w1, w2, b1, b2):
                            return True
        day += timedelta(days=1)
    return False


def _parse_segment(seg: str):
    bands = [(_mins(a), _mins(b)) for a, b in _BAND.findall(seg)]
    if not bands:
        return None
    applies = _parse_dates(_BAND.sub("", seg).strip())
    if applies is None:
        return None
    return {"applies": applies, "bands": bands}


def _parse_dates(prefix: str):
    """Return a predicate applies(date)->bool for a date/weekday constraint, or None."""
    prefix = prefix.strip()
    if not prefix or prefix == "DAILY":
        return lambda date: True

    # Cross-month day range: "JUN 29-JUL 04"
    m = re.fullmatch(r"([A-Z]{3})\s+(\d{1,2})\s*-\s*([A-Z]{3})\s+(\d{1,2})", prefix)
    if m and m.group(1) in _MONTHS and m.group(3) in _MONTHS:
        a = (_MONTHS[m.group(1)], int(m.group(2)))
        b = (_MONTHS[m.group(3)], int(m.group(4)))
        return lambda date, a=a, b=b: a <= (date.month, date.day) <= b

    # Same-month day range: "JUN 26-30"
    m = re.fullmatch(r"([A-Z]{3})\s+(\d{1,2})\s*-\s*(\d{1,2})", prefix)
    if m and m.group(1) in _MONTHS:
        mo, d1, d2 = _MONTHS[m.group(1)], int(m.group(2)), int(m.group(3))
        return lambda date, mo=mo, d1=d1, d2=d2: date.month == mo and d1 <= date.day <= d2

    # Month + explicit day list: "JUN 26" / "JUN 26 28 30"
    m = re.fullmatch(r"([A-Z]{3})\s+((?:\d{1,2}\s*)+)", prefix)
    if m and m.group(1) in _MONTHS:
        mo = _MONTHS[m.group(1)]
        days = {int(x) for x in m.group(2).split()}
        return lambda date, mo=mo, days=days: date.month == mo and date.day in days

    # Weekday range: "MON-FRI"
    m = re.fullmatch(r"([A-Z]{3})\s*-\s*([A-Z]{3})", prefix)
    if m and m.group(1) in _DOW and m.group(2) in _DOW:
        a, b = _DOW[m.group(1)], _DOW[m.group(2)]
        return lambda date, a=a, b=b: (a <= date.weekday() <= b) if a <= b \
            else (date.weekday() >= a or date.weekday() <= b)

    # Weekday list: "MON WED FRI" / "SAT SUN"
    toks = prefix.split()
    if toks and all(t in _DOW for t in toks):
        s = {_DOW[t] for t in toks}
        return lambda date, s=s: date.weekday() in s

    return None


def _mins(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[2:])


def _overlaps(w1: float, w2: float, b1: int, b2: int) -> bool:
    if b2 > b1:                              # normal band within a day
        return w1 < b2 and w2 > b1
    # wrapping band across midnight: active [b1,1440) and [0,b2)
    return (w2 > b1) or (w1 < b2)


def _window_minutes_on(date, start: datetime, end: datetime):
    """The window's minute range [w1, w2] on `date`, or (None, None) if untouched."""
    day_start = datetime.combine(date, time.min, tzinfo=start.tzinfo)
    day_end = day_start + timedelta(days=1)
    s, e = max(start, day_start), min(end, day_end)
    if s >= e:
        return None, None
    return (s - day_start).total_seconds() / 60, (e - day_start).total_seconds() / 60
