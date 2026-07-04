"""Tiny HTTP server exposing the NOTAM engine — deploy target: Render.

The server holds the ANTHROPIC_API_KEY as an environment variable (set it in
Render's dashboard), so the key is never in the app. Turn the AI on by setting
NOTAM_LLM=claude on the server; the default 'none' runs the deterministic
pipeline with no tokens spent.

Run locally:    python3 server.py
Render start:   gunicorn server:app --bind 0.0.0.0:$PORT

Request:  POST /briefing
  { "dep": "EDDK", "arr": "LFML", "alt": "LFMN", "enr": "LSGG LFLL",
    "etd": "0800", "eet": "0130" }
Codes are ICAO for now, separated by space / comma / dot.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, request

from notam import briefing

app = Flask(__name__)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/briefing")
def make_briefing():
    data = request.get_json(force=True, silent=True) or {}
    return jsonify(briefing.build(_airports(data), _window(data)))


def _codes(raw: str) -> list[str]:
    return [c.upper() for c in re.split(r"[\s,.]+", str(raw)) if c][:20]


def _airports(data: dict) -> list[tuple[str, str]]:
    out = []
    for keyname, role in (("dep", "DEP"), ("arr", "ARR"),
                          ("alt", "ALT"), ("enr", "ENR")):
        for code in _codes(data.get(keyname, "")):
            out.append((code, role))
    return out


def _hhmm(s: str) -> tuple[int, int]:
    m = re.match(r"(\d{1,2}):?(\d{2})", str(s))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def _window(data: dict) -> tuple[datetime, datetime]:
    """Derive the flight window from ETD + EET (date defaults to today, UTC)."""
    now = datetime.now(timezone.utc)
    eh, em = _hhmm(data.get("etd", "0000"))
    dh, dm = _hhmm(data.get("eet", "0000"))
    start = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    return (start, start + timedelta(hours=dh, minutes=dm))


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
