"""Tests for the D)-schedule parser (notam/schedule.py).

Run:  python3 test_schedule.py
"""

from datetime import datetime, timezone

from notam.schedule import active_during


def w(y, mo, d, h1, mi1, h2, mi2):
    return (datetime(y, mo, d, h1, mi1, tzinfo=timezone.utc),
            datetime(y, mo, d, h2, mi2, tzinfo=timezone.utc))


CRANE = "JUN 26 0700-1630, JUN 29-JUL 04 0700-1630"   # the real Porto crane D)

CASES = [
    # name, D) text, window, expected
    ("crane: active day+time",   CRANE, w(2026, 6, 26, 9, 0, 10, 30), True),
    ("crane: after band",        CRANE, w(2026, 6, 26, 17, 0, 18, 0), False),
    ("crane: day not listed",    CRANE, w(2026, 6, 27, 9, 0, 10, 0), False),
    ("crane: inside range",      CRANE, w(2026, 6, 30, 9, 0, 10, 0), True),
    ("crane: after range",       CRANE, w(2026, 7, 5, 9, 0, 10, 0), False),

    ("daily band: in",           "0700-1630", w(2026, 7, 4, 8, 0, 9, 30), True),
    ("daily band: out",          "0700-1630", w(2026, 7, 4, 17, 0, 18, 0), False),

    ("weekday: Monday in",       "MON-FRI 0800-1700", w(2026, 7, 6, 9, 0, 10, 0), True),
    ("weekday: Monday late",     "MON-FRI 0800-1700", w(2026, 7, 6, 18, 0, 19, 0), False),
    ("weekday: Saturday out",    "MON-FRI 0800-1700", w(2026, 7, 11, 9, 0, 10, 0), False),

    ("same-month range: in",     "JUN 26-30 0700-1630", w(2026, 6, 28, 9, 0, 10, 0), True),
    ("same-month range: out",    "JUN 26-30 0700-1630", w(2026, 6, 25, 9, 0, 10, 0), False),

    ("multi-band: gap",          "0800-1200 1400-1800", w(2026, 7, 4, 12, 30, 13, 30), False),
    ("multi-band: hit",          "0800-1200 1400-1800", w(2026, 7, 4, 15, 0, 15, 30), True),

    ("dow list: Saturday in",    "SAT SUN 0900-1500", w(2026, 7, 11, 10, 0, 11, 0), True),
    ("dow list: Monday out",     "SAT SUN 0900-1500", w(2026, 7, 6, 10, 0, 11, 0), False),

    ("H24",                      "H24", w(2026, 7, 4, 3, 0, 4, 0), True),
    ("no D) field",              "", w(2026, 7, 4, 9, 0, 10, 0), None),
    ("unparseable SR-SS",        "SR-SS", w(2026, 7, 4, 9, 0, 10, 0), None),
]


def main():
    fails = 0
    for name, d, window, expected in CASES:
        got = active_during(d, *window)
        ok = got == expected and type(got) is type(expected)
        if not ok:
            fails += 1
        print(f"[{'ok' if ok else 'FAIL'}] {name}: got={got!r} expected={expected!r}")
    print()
    print("ALL PASSED" if fails == 0 else f"{fails} FAILED")
    return fails


if __name__ == "__main__":
    raise SystemExit(1 if main() else 0)
