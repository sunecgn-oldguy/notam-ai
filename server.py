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

Wiring — this is the HTTP entry point (Render runs `gunicorn server:app`). It is
a thin adapter: parse the request, then hand off to the engine.
  /briefing -> briefing.build()   (notam/briefing.py — the whole pipeline)
  /feedback -> feedback.submit()  (notam/feedback.py)
  /usage    -> usage.snapshot()   (notam/usage.py)
  input codes -> airports.to_icao() (notam/airports.py)
The engine in notam/ is pure stdlib; Flask lives only here. See ARCHITECTURE.md.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, request, send_from_directory

from notam import briefing, feedback, usage
from notam.airports import to_icao

app = Flask(__name__)

_WEB = os.path.join(os.path.dirname(__file__), "web")


@app.get("/")
def index():
    """A simple browser UI for trying the engine (served from the same origin)."""
    return send_from_directory(_WEB, "index.html")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/usage")
def usage_report():
    """AI token usage since this server last started (provider-agnostic)."""
    return jsonify(usage.snapshot())


@app.post("/briefing")
def make_briefing():
    data = request.get_json(force=True, silent=True) or {}
    return jsonify(briefing.build(_airports(data), _window(data)))


@app.post("/feedback")
def make_feedback():
    """Pilot feedback: saved to a file (backup) and emailed to the owner."""
    data = request.get_json(force=True, silent=True) or {}
    return jsonify(feedback.submit(
        data.get("message", ""), data.get("email", ""), data.get("context") or {}))


def _codes(raw: str) -> list[str]:
    return [to_icao(c) for c in re.split(r"[\s,.]+", str(raw)) if c][:20]


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
    """Flight window from day (today/tomorrow) + ETD + EET, all UTC."""
    base = datetime.now(timezone.utc)
    if str(data.get("day", "")).lower().startswith("tom"):
        base += timedelta(days=1)
    eh, em = _hhmm(data.get("etd", "0000"))
    dh, dm = _hhmm(data.get("eet", "0000"))
    start = base.replace(hour=eh, minute=em, second=0, microsecond=0)
    return (start, start + timedelta(hours=dh, minutes=dm))


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
