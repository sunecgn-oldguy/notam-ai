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

from flask import Flask, abort, jsonify, request, send_from_directory

from notam import briefing, feedback, ratelimit, usage
from notam.airports import to_icao

app = Flask(__name__)

_WEB = os.path.join(os.path.dirname(__file__), "web")

# Rate-limit the expensive /briefing endpoint (review #4): 20 briefings per hour
# per client IP. The keep-alive pinger hits /health, not /briefing, so it is
# unaffected. Tune here — override via env if you ever want it configurable.
_BRIEFING_LIMIT = ratelimit.RateLimiter(max_calls=20, per_seconds=3600)


def _client_key() -> str:
    """Best-effort client identity for rate limiting. Render sits behind a proxy
    that sets X-Forwarded-For, so trust its first hop; fall back to remote_addr."""
    fwd = request.headers.get("X-Forwarded-For", "")
    return fwd.split(",")[0].strip() if fwd else (request.remote_addr or "unknown")


@app.get("/")
def index():
    """A simple browser UI for trying the engine (served from the same origin)."""
    return send_from_directory(_WEB, "index.html")


# --- PWA static assets (served from the site root so the service worker's scope
#     is the whole origin). These make the app installable + offline-capable;
#     saved briefings live in the browser's IndexedDB (see web/index.html). ---

@app.get("/sw.js")
def service_worker():
    return send_from_directory(_WEB, "sw.js", mimetype="application/javascript")


@app.get("/manifest.json")
def manifest():
    return send_from_directory(_WEB, "manifest.json",
                               mimetype="application/manifest+json")


@app.get("/icon-<int:size>.png")
def icon(size: int):
    if size not in (192, 512):
        abort(404)
    return send_from_directory(_WEB, f"icon-{size}.png")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/usage")
def usage_report():
    """AI token usage since this server last started (provider-agnostic)."""
    return jsonify(usage.snapshot())


@app.post("/briefing")
def make_briefing():
    if not _BRIEFING_LIMIT.allow(_client_key()):
        return jsonify({
            "error": "rate_limited",
            "message": "Too many briefings this hour. Please wait a bit and try again.",
        }), 429
    data = request.get_json(force=True, silent=True) or {}
    # Last line of defence: whatever breaks downstream, the pilot gets a readable
    # reason instead of Flask's bare HTML 500 page. The traceback goes to the
    # Render log so the cause is findable after the fact.
    try:
        return jsonify(briefing.build(_airports(data), _window(data)))
    except Exception:
        app.logger.exception("briefing failed for %s", data)
        return jsonify({
            "error": "briefing_failed",
            "message": "Could not build the briefing. Please try again.",
        }), 500


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
    """'08:00', '0800', '08.00', '08 00' -> (8, 0). Anything unparseable -> (0, 0).

    The separator is whatever the phone's keyboard produced: iOS shows a time as
    '08.00' in Danish locale, and a numeric keypad has no ':' at all. So we ignore
    separators entirely and read the digits. Out-of-range values are clamped, not
    raised — hour=25 used to reach datetime.replace() and 500 the whole request.
    """
    digits = re.sub(r"\D", "", str(s))
    if len(digits) < 3:                       # '', '8', '08' -> no usable time
        return (0, 0)
    h, m = int(digits[:-2]), int(digits[-2:])
    return (min(h, 23), min(m, 59))


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
