"""The pilot's personal airport database and saved presets.

Airports are pilot-curated (see the design note in memory) — the pilot keeps a
small list of the fields he uses and picks from it per flight, optionally saving
a selection as a named preset for reuse.

Storage is two plain, human-readable JSON files under data/:
  - airports.json : [{"icao": "EDDK", "note": "home base"}, ...]
  - presets.json  : {"CGN-MRS": ["EDDK", "LFML"], ...}

In the real app this becomes local storage / SQLite; the interface here stays
the same so the rest of the code never has to care where it is stored.
"""

# Wiring — Used by: main.py (the CLI) ONLY. The deployed web app keeps routes in
#          the browser's localStorage (see web/index.html), so profile.py is not
#          in the app's request path. See ARCHITECTURE.md.

from __future__ import annotations

import json
import os

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_AIRPORTS = os.path.join(_DATA_DIR, "airports.json")
_PRESETS = os.path.join(_DATA_DIR, "presets.json")


def _load(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(path: str, data) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# --- airport database ---

def list_airports() -> list[dict]:
    return _load(_AIRPORTS, [])


def add_airport(icao: str, note: str = "") -> list[dict]:
    icao = icao.upper()
    airports = list_airports()
    for a in airports:
        if a["icao"] == icao:          # already known: update the note only
            if note:
                a["note"] = note
            _save(_AIRPORTS, airports)
            return airports
    airports.append({"icao": icao, "note": note})
    _save(_AIRPORTS, airports)
    return airports


def remove_airport(icao: str) -> list[dict]:
    airports = [a for a in list_airports() if a["icao"] != icao.upper()]
    _save(_AIRPORTS, airports)
    return airports


# --- saved presets (named airport selections) ---

def list_presets() -> dict:
    return _load(_PRESETS, {})


def save_preset(name: str, icaos: list[str]) -> None:
    presets = list_presets()
    presets[name] = [c.upper() for c in icaos]
    _save(_PRESETS, presets)


def load_preset(name: str) -> list[str]:
    return list_presets().get(name, [])
