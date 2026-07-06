"""Assemble a structured route briefing (shared by the CLI and the server).

Pure stdlib — the web framework lives only in server.py. Returns plain dicts so
it serialises straight to JSON. This is the one place the whole pipeline is wired
together: fetch -> enrich -> classify -> time-gate -> AI summary (cached).

The two I/O-bound steps run concurrently: the FAA fetches (one per airport) and
the AI summaries (one per relevant NOTAM). The cache is thread-safe (see
cache.py), so parallel summaries never clobber each other.

This is the PRODUCTION path (what the app hits). The CLI in main.py wires a
similar-but-simpler pipeline for developer testing — see ARCHITECTURE.md for how
the two relate. Called by: server.py (POST /briefing).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from notam import cache, runways, weather
from notam.enrich import enrich
from notam.faa import fetch_notams
from notam.llm import summarise
from notam.relevance import classify, priority
from notam.timing import is_active_during, parse_notam_dt

# Both pools are I/O-bound (waiting on FAA / aviationweather / the Claude API),
# so extra threads are cheap and cut wall-clock on multi-airport routes — a whole
# route fans out at once instead of in waves. Kept moderate to be gentle on the
# upstream sources (avoid rate-limiting).
_FETCH_WORKERS = 16
_AI_WORKERS = 16


def build(airports: list[tuple[str, str]],
          window: tuple[datetime, datetime]) -> dict:
    """airports: list of (icao, role). window: (start, end). Returns a briefing dict."""
    # 1. Fetch + classify every airport concurrently.
    with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
        groups = list(pool.map(lambda ar: _process_airport(ar, window), airports))

    # 2. Translate all relevant NOTAMs (across all airports) concurrently — cached.
    _summarise_parallel([n for g in groups for n in g["high"]])
    cache.flush()          # persist the summaries written during this briefing (review #2)

    # 3. Assemble the response.
    return {"airports": [_airport_view(g) for g in groups]}


def _process_airport(airport: tuple[str, str],
                     window: tuple[datetime, datetime]) -> dict:
    icao, role = airport
    # Weather fetches independently (and already fails safe on its own), so the
    # pilot still gets METAR/TAF even if the FAA NOTAM feed is down for this one.
    weather_data = weather.fetch(icao, window)

    # ROBUSTHED (review #1): faa.fetch_notams kan kaste (FAA-timeout / 500 /
    # ikke-JSON). Fordi build() kører os i en trådpulje-map, ville en ufanget
    # exception her vælte HELE briefingen — også de pladser der hentede fint. Så
    # vi fanger per plads og returnerer en gyldig, TOM gruppe med et error-flag.
    # Vigtigt: vi viser IKKE bare en tom liste (det ville se ud som "ingen
    # NOTAMs" = usikkert) — error-flaget lader UI'en advare pilotens.
    try:
        notams = [enrich(n) for n in fetch_notams(icao)]
    except Exception:
        return {
            "icao": icao, "role": role, "name": "",
            "notams": [], "military": [], "high": [], "inactive": [],
            "weather": weather_data, "error": "notam_fetch_failed",
        }

    for n in notams:
        n["relevance"] = classify(n)
        n["active"] = is_active_during(n, *window)

    # Military first (all disregarded); then split the civil NOTAMs by activity.
    military = [n for n in notams if n["relevance"]["tier"] == "low"]
    civil = [n for n in notams if n["relevance"]["tier"] != "low"]
    # Relevant list sorted by category priority (ILS, Approach, Runway, …);
    # stable, so fetch order is kept within a category.
    high = sorted((n for n in civil if n["active"]),
                  key=lambda n: priority(n["relevance"]["category"]))
    return {
        "icao": icao, "role": role,
        "name": notams[0]["airport_name"] if notams else "",
        "notams": notams, "military": military, "high": high,
        "inactive": [n for n in civil if not n["active"]],
        "weather": weather_data, "error": None,
    }


def _summarise_parallel(notams: list[dict]) -> None:
    """Fill n['_summary'] for each NOTAM, running the AI calls concurrently."""
    if not notams:
        return

    def work(n):
        try:
            n["_summary"] = summarise(n)
        except Exception:                     # one failed call never kills the briefing
            n["_summary"] = n.get("body", "")

    with ThreadPoolExecutor(max_workers=_AI_WORKERS) as pool:
        list(pool.map(work, notams))


def _airport_view(g: dict) -> dict:
    return {
        "icao": g["icao"],
        "role": g["role"],
        "name": g["name"],
        "counts": {"raw": len(g["notams"]), "relevant": len(g["high"]),
                   "military": len(g["military"]), "inactive": len(g["inactive"])},
        "error": g.get("error"),          # "notam_fetch_failed" -> UI warns the pilot
        "weather": g["weather"],
        "runways": runways.view(g["icao"], g["weather"].get("wind")),
        "relevant": [_view(n) for n in g["high"]],
        "military": [_raw_view(n) for n in g["military"]],
        "inactive": [_raw_view(n) for n in g["inactive"]],
    }


def _age(n: dict) -> str:
    """How long ago the NOTAM was issued, compact — e.g. '3d', '2w', '5mo', '1y'."""
    dt = parse_notam_dt(n.get("issued") or n.get("start", ""))
    if dt is None:
        return ""
    days = (datetime.now(timezone.utc) - dt).days
    if days < 0:
        return "new"
    if days == 0:
        return "today"
    if days < 14:
        return f"{days}d"
    if days < 60:
        return f"{days // 7}w"
    if days < 365:
        return f"{days // 30}mo"
    return f"{days // 365}y"


def _view(n: dict) -> dict:
    q = n["qline"]
    return {
        "id": n["id"],
        "age": _age(n),
        "category": n["relevance"]["category"],
        "summary": n.get("_summary") or summarise(n),   # precomputed in step 2
        "raw": n["raw"],                  # original NOTAM, always available
        "start": n["start"],
        "end": n["end"],
        "area": None if not q else {
            "lat": q["lat"], "lon": q["lon"], "radius_nm": q["radius_nm"],
            "fl_lower": q["fl_lower"], "fl_upper": q["fl_upper"],
        },
    }


def _raw_view(n: dict) -> dict:
    """id + full original text only — no AI spent on disregarded / out-of-window NOTAMs."""
    return {"id": n["id"], "raw": n["raw"]}
