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
  /stats    -> stats.snapshot()   (notam/stats.py — how many pilots, how many briefings)
  input codes -> airports.to_icao() (notam/airports.py)
The engine in notam/ is pure stdlib; Flask lives only here. See ARCHITECTURE.md.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from flask import Flask, abort, jsonify, request, send_from_directory

from notam import briefing, feedback, ratelimit, stats, usage
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


# --- Usage stats (private). Both routes need ?key=<STATS_KEY>; with no STATS_KEY
#     set in the environment they 404, so a fresh deploy leaks nothing by default.
#     /stats.json is what the keep-alive job polls; /stats is the page you read. ---

def _stats_authorised() -> bool:
    key = os.environ.get("STATS_KEY", "")
    return bool(key) and hmac.compare_digest(request.args.get("key", ""), key)


@app.get("/stats.json")
def stats_json():
    """Since-boot counts + the device roster, for .github/scripts/log_usage.py."""
    if not _stats_authorised():
        abort(404)
    return jsonify(stats.snapshot(with_devices=True))


@app.get("/stats")
def stats_page():
    """Human-readable numbers: lifetime (from the Gist) and since this deploy."""
    if not _stats_authorised():
        abort(404)
    now, life = stats.snapshot(), _lifetime()
    tok = usage.snapshot()

    def row(label, value, sub=""):
        return (f'<tr><th>{label}</th><td>{value}</td>'
                f'<td class="sub">{sub}</td></tr>')

    if life:
        head = (row("Pilots (unique devices)", life.get("users", "—")) +
                row("Briefings built", life.get("briefings", "—")) +
                row("AI calls", life.get("calls", "—")) +
                row("Tokens", f'{life.get("total", 0):,}'.replace(",", " "),
                    _cost_dkk(life)))
        stamp = f'Lifetime · last updated {life.get("updated_at", "—")}'
    else:
        head = row("Lifetime", "not available",
                   "set GIST_ID on the server to read the stored totals")
        stamp = "Lifetime"
    body = (row("Pilots (unique devices)", now["devices"]) +
            row("Briefings built", now["briefings"]) +
            row("AI calls", tok["calls"]) +
            row("Tokens", f'{tok["total_tokens"]:,}'.replace(",", " ")))
    return f"""<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>NOTAM AI — usage</title>
<style>
 body{{font:15px/1.5 -apple-system,system-ui,sans-serif;margin:0;padding:22px 16px;
   background:#0f1115;color:#e8eaed}}
 h1{{font-size:17px;margin:0 0 18px}} h2{{font-size:12px;letter-spacing:.1em;
   text-transform:uppercase;color:#8b93a1;margin:22px 0 8px;font-weight:700}}
 table{{width:100%;max-width:520px;border-collapse:collapse}}
 th{{text-align:left;font-weight:400;color:#b6bcc7;padding:7px 0}}
 td{{text-align:right;font-variant-numeric:tabular-nums;font-size:19px;padding:7px 0}}
 td.sub{{text-align:right;font-size:12px;color:#8b93a1;padding-left:10px;width:1%;
   white-space:nowrap}}
 tr+tr th,tr+tr td{{border-top:1px solid #232733}}
</style>
<h1>NOTAM &amp; WX AI — usage</h1>
<h2>{stamp}</h2><table>{head}</table>
<h2>Since this deploy</h2><table>{body}</table>"""


def _cost_dkk(life: dict) -> str:
    """Rough spend so far, at Claude Haiku 4.5 rates ($1/M in, $5/M out)."""
    usd = life.get("input", 0) / 1e6 + life.get("output", 0) / 1e6 * 5
    return f"≈ ${usd:.2f}"


_LIFETIME_CACHE: dict = {"at": 0.0, "data": None}


def _lifetime() -> dict | None:
    """Lifetime totals from the secret Gist the keep-alive job writes.

    Read-only and unauthenticated: a secret Gist is readable by anyone holding
    its ID, so the server needs GIST_ID but not the token that writes it. Cached
    for 5 minutes — GitHub allows 60 unauthenticated calls an hour, and this page
    is refreshed by hand. Any failure returns None and the page says so.
    """
    gid = os.environ.get("GIST_ID", "")
    if not gid:
        return None
    if _LIFETIME_CACHE["data"] and time.time() - _LIFETIME_CACHE["at"] < 300:
        return _LIFETIME_CACHE["data"]
    try:
        req = urllib.request.Request(
            f"https://api.github.com/gists/{gid}",
            headers={"User-Agent": "notam-ai-stats",
                     "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            gist = json.load(r)
        state = json.loads(gist["files"]["notam-ai-usage.json"]["content"])
        out = dict(state.get("lifetime") or {})
        out["users"] = len(state.get("users") or [])
        out["briefings"] = (state.get("lifetime") or {}).get("briefings", "—")
        out["updated_at"] = state.get("updated_at", "—")
    except Exception:
        app.logger.exception("could not read lifetime stats from Gist %s", gid)
        return None
    _LIFETIME_CACHE.update(at=time.time(), data=out)
    return out


@app.post("/briefing")
def make_briefing():
    if not _BRIEFING_LIMIT.allow(_client_key()):
        return jsonify({
            "error": "rate_limited",
            "message": "Too many briefings this hour. Please wait a bit and try again.",
        }), 429
    data = request.get_json(force=True, silent=True) or {}
    stats.record(data.get("client", ""))   # anonymous usage count; see notam/stats.py
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
