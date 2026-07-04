"""Tests for the weather classifier (notam/weather.py).

Run:  python3 test_weather.py
"""

from notam.weather import _classify, _ceiling_ft, _visibility_m


def cat(metar: str):
    up = metar.upper()
    return _classify("CAVOK" in up, _visibility_m(up), _ceiling_ft(up))


CASES = [
    # metar (visibility + cloud groups shown), expected category
    ("EDDK 041250Z 24012KT CAVOK 18/12 Q1015", "CAVOK"),
    ("EDDK 041250Z 24012KT 9999 FEW020 SCT040 18/12 Q1015", "CAVOK"),   # vis 10km, no ceiling
    ("EDDK 041250Z 24012KT 8000 BKN018 15/12 Q1012", "GOOD"),          # vis 8km
    ("EDDK 041250Z 24012KT 9999 BKN012 15/12 Q1012", "MARGINAL"),      # ceiling 1200 ft
    ("EDDK 041250Z 24012KT 4000 BKN008 12/11 Q1010", "MARGINAL"),      # vis 4km, ceil 800
    ("EDDK 041250Z 24012KT 0600 OVC003 09/09 Q1008", "LOW VIS"),       # vis 600 m
    ("EDDK 041250Z 24012KT 9999 OVC004 09/08 Q1008", "LOW VIS"),       # ceiling 400 ft
    ("KJFK 041251Z 24012KT 10SM FEW250 20/10 A3006", "CAVOK"),         # US 10SM, no ceiling
    ("KJFK 041251Z 24012KT 3SM BR BKN009 12/11 A2998", "MARGINAL"),    # US 3SM, ceil 900
    ("KJFK 041251Z 00000KT 1/2SM FG OVC002 09/09 A2995", "LOW VIS"),   # US 1/2SM
]

fails = 0
for metar, expected in CASES:
    got = cat(metar)
    ok = got == expected
    if not ok:
        fails += 1
    print(f"[{'ok' if ok else 'FAIL'}] {expected:9} <- got {got!r:11}  ({metar[:44]}…)")

print()
print("ALL PASSED" if fails == 0 else f"{fails} FAILED")
raise SystemExit(1 if fails else 0)
