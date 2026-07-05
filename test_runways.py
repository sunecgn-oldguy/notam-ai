"""Tests for runway lookup, wind parsing and the wind-favoured end.

Run:  python3 test_runways.py
"""

from notam.runways import _angle, view
from notam.weather import _wind

fails = 0


def check(name, got, exp):
    global fails
    ok = got == exp
    if not ok:
        fails += 1
    print(f"[{'ok' if ok else 'FAIL'}] {name:36} got {got!r:24} exp {exp!r}")


# --- METAR wind parsing ---
check("36007KT", _wind("EDDK 121250Z 36007KT CAVOK"), {"dir": 360, "speed": 7, "gust": None})
check("28015G25KT", _wind("X 28015G25KT"), {"dir": 280, "speed": 15, "gust": 25})
check("VRB03KT dir", _wind("X VRB03KT")["dir"], None)
check("VRB03KT speed", _wind("X VRB03KT")["speed"], 3)
check("00000KT calm", _wind("X 00000KT"), {"dir": None, "speed": 0, "gust": None})
check("27010MPS -> kt", _wind("X 27010MPS")["speed"], 19)      # 10 m/s ~= 19 kt
check("no wind token", _wind("EDDK CAVOK"), {"dir": None, "speed": 0, "gust": None})

# --- angle helper ---
check("angle 010/350 = 20", _angle(10, 350), 20)
check("angle 090/270 = 180", _angle(90, 270), 180)


# --- favoured end (EDDK: 06/24=064/244, 13L/31R & 13R/31L=138/318) ---
def favs(icao, wind):
    return {r["le"] + "/" + r["he"]: r["fav"] for r in view(icao, wind)}

w = favs("EDDK", {"dir": 280, "speed": 12})           # W wind -> land 24 / 31
check("280/12 -> 06/24 = 24", w["06/24"], "he")
check("280/12 -> 13L/31R = 31R", w["13L/31R"], "he")

w = favs("EDDK", {"dir": 100, "speed": 10})           # E wind -> land 06 / 13
check("100/10 -> 06/24 = 06", w["06/24"], "le")
check("100/10 -> 13L/31R = 13L", w["13L/31R"], "le")

check("calm -> no favour", set(favs("EDDK", {"dir": None, "speed": 0}).values()), {None})
check("2 kt -> no favour", set(favs("EDDK", {"dir": 280, "speed": 2}).values()), {None})
check("unknown airport -> []", view("ZZZZ", {"dir": 280, "speed": 12}), [])

print()
print("ALL PASSED" if fails == 0 else f"{fails} FAILED")
raise SystemExit(1 if fails else 0)
