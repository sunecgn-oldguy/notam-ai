"""Tests for the weather classifier (notam/weather.py).

Run:  python3 test_weather.py
"""

from datetime import datetime, timezone

from notam.weather import _classify, _ceiling_ft, _visibility_m, taf_category


def cat(metar: str):
    up = metar.upper()
    return _classify("CAVOK" in up, _visibility_m(up), _ceiling_ft(up))


CASES = [
    # metar (visibility + cloud groups shown), expected category
    ("EDDK 041250Z 24012KT CAVOK 18/12 Q1015", "CAVOK"),               # literal CAVOK -> CAVOK
    ("EDDK 041250Z 24012KT 9999 FEW020 SCT040 18/12 Q1015", "GOOD"),   # vis 10km, no ceiling — good, not reported CAVOK
    ("EDDK 041250Z 24012KT 8000 BKN018 15/12 Q1012", "OK"),            # vis 8km
    ("EDDK 041250Z 24012KT 9999 BKN012 15/12 Q1012", "MARGINAL"),      # ceiling 1200 ft
    ("EDDK 041250Z 24012KT 4000 BKN008 12/11 Q1010", "MARGINAL"),      # vis 4km, ceil 800
    ("EDDK 041250Z 24012KT 0600 OVC003 09/09 Q1008", "MARGINAL"),      # vis 600 m, ceil 300 — above Cat I minima
    ("EDDK 041250Z 24012KT 9999 OVC004 09/08 Q1008", "MARGINAL"),      # ceiling 400 ft — above 200 ft minima
    ("EDDK 041250Z 24012KT 0500 FG OVC002 08/08 Q1009", "LOW VIS"),    # vis 500 m — at/below minima
    ("EDDK 041250Z 24012KT 9999 OVC002 08/08 Q1009", "LOW VIS"),       # ceiling 200 ft — at minima
    ("KJFK 041251Z 24012KT 10SM FEW250 20/10 A3006", "GOOD"),          # US 10SM, no ceiling — good, not reported CAVOK
    ("KJFK 041251Z 24012KT 3SM BR BKN009 12/11 A2998", "MARGINAL"),    # US 3SM, ceil 900
    ("KJFK 041251Z 00000KT 1/2SM FG OVC002 09/09 A2995", "LOW VIS"),   # US 1/2SM, ceil 200 ft
]

fails = 0
for metar, expected in CASES:
    got = cat(metar)
    ok = got == expected
    if not ok:
        fails += 1
    print(f"[{'ok' if ok else 'FAIL'}] METAR {expected:9} <- got {got!r:11}  ({metar[:40]}…)")


def win(day, h1, mi1, h2, mi2):
    return (datetime(2026, 7, day, h1, mi1, tzinfo=timezone.utc),
            datetime(2026, 7, day, h2, mi2, tzinfo=timezone.utc))


TAF_CAVOK = "TAF EDDK 041700Z 0418/0524 30015G25KT CAVOK BECMG 0418/0421 29008KT TEMPO 0422/0505 23004KT"
TAF_TEMPO = "TAF LFML 050500Z 0506/0612 27010KT 9999 SCT035 TEMPO 0510/0514 3000 BKN008"
TAF_FM = "TAF EGLL 050000Z 0500/0606 25008KT CAVOK FM051000 20008KT 0400 FG OVC002"
TAF_BECMG = "TAF LSZH 050000Z 0500/0606 24006KT CAVOK BECMG 0512/0514 6000 BKN020"

TAF_CASES = [
    ("all-CAVOK, wind-only changes",  TAF_CAVOK, win(5, 8, 0, 9, 30), "CAVOK"),
    ("TEMPO deterioration hits",      TAF_TEMPO, win(5, 12, 0, 13, 0), "MARGINAL"),
    ("before the TEMPO",              TAF_TEMPO, win(5, 7, 0, 8, 0), "GOOD"),
    ("after an FM (permanent bad)",   TAF_FM, win(5, 11, 0, 12, 0), "LOW VIS"),
    ("before the FM",                 TAF_FM, win(5, 8, 0, 9, 0), "CAVOK"),
    ("after a BECMG",                 TAF_BECMG, win(5, 15, 0, 16, 0), "OK"),
    ("before the BECMG",              TAF_BECMG, win(5, 5, 0, 5, 30), "CAVOK"),
]

for name, taf, window, expected in TAF_CASES:
    got = taf_category(taf, *window)
    ok = got == expected
    if not ok:
        fails += 1
    print(f"[{'ok' if ok else 'FAIL'}] TAF   {expected:9} <- got {got!r:11}  ({name})")

print()
print("ALL PASSED" if fails == 0 else f"{fails} FAILED")
raise SystemExit(1 if fails else 0)
