"""NOTAM AI — route briefing engine (steps 1-4 + 6, no AI layer yet).

The pilot keeps a personal airport database and, per flight, briefs a selection
from it (or a saved preset) for a given date/time window. For each airport the
engine fetches raw NOTAMs, cleans them, parses the Q-line, classifies relevance
and gates on the flight window — all in plain code, before any AI.

Commands (the CLI is just for testing; the app reuses notam/profile.py):

    # manage the personal airport database
    python3 main.py add EDDK --note "home base"
    python3 main.py remove EDDK
    python3 main.py airports
    python3 main.py presets

    # brief a flight from an explicit list, and optionally save it as a preset
    python3 main.py brief --airports EDDK LFML \\
        --dep-time "2026-07-06 0800" --arr-time "2026-07-06 0930" \\
        --save-preset "CGN-MRS"

    # brief a flight from a saved preset
    python3 main.py brief --preset "CGN-MRS" --dep-time "2026-07-06 0800"

Times are UTC, "YYYY-MM-DD HHMM". Full raw text is written to route_notams.txt.

NB for new readers: this is the DEVELOPER CLI, not the app's code path. It wires
its own copy of fetch -> enrich -> classify -> time-gate (see _report_airport)
and deliberately stops BEFORE the AI/weather/runway/cache layer that the app
uses. The production pipeline lives in notam/briefing.py. When you change
pipeline logic, check whether both this file and briefing.py need it.
See ARCHITECTURE.md.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from notam import profile
from notam.enrich import enrich
from notam.faa import fetch_notams
from notam.relevance import classify
from notam.timing import is_active_during

_OUTPUT_FILE = "route_notams.txt"


# --- briefing helpers ---

def _parse_user_dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)


def _qline_summary(q: dict | None) -> str:
    if q is None:
        return "(ingen Q-linje)"
    fl = f"FL{q['fl_lower']:03d}-{q['fl_upper']:03d}"
    return (f"{q['q_subject']}  {abs(q['lat']):.2f}{'N' if q['lat'] >= 0 else 'S'} "
            f"{abs(q['lon']):.2f}{'E' if q['lon'] >= 0 else 'W'} "
            f"r{q['radius_nm']}NM  {fl}")


def _report_airport(icao: str, window: tuple[datetime, datetime], dump) -> None:
    notams = [enrich(n) for n in fetch_notams(icao)]
    for n in notams:
        n["relevance"] = classify(n)
        n["active"] = is_active_during(n, *window)

    active = [n for n in notams if n["active"]]
    high = [n for n in active if n["relevance"]["tier"] == "high"]
    low = [n for n in active if n["relevance"]["tier"] == "low"]
    inactive = [n for n in notams if not n["active"]]

    name = notams[0]["airport_name"] if notams else ""
    header = (f"{icao}  {name}  —  {len(notams)} NOTAMs  "
              f"({len(high)} relevante, {len(low)} militær, "
              f"{len(inactive)} udenfor flyve-vindue)")
    print(f"\n{'=' * 72}\n{header}\n{'=' * 72}")
    dump.write(f"\n{'=' * 72}\n{header}\n{'=' * 72}\n")

    for n in high:
        print(f"\n[{n['id']}] {n['relevance']['category']}  |  "
              f"{_qline_summary(n['qline'])}")
        print(f"    {n['body'][:110]}")

    if low:
        print(f"\n  ▸ militær — disregarded ({len(low)})")
    if inactive:
        print(f"  ▸ ikke aktiv under flyvningen ({len(inactive)})")

    for n in high + low + inactive:
        dump.write(f"\n[{n['id']}]  {n['relevance']['category']}  "
                   f"(tier={n['relevance']['tier']}, active={n['active']})   "
                   f"{n['start']} -> {n['end']}\n"
                   f"Q-linje: {_qline_summary(n['qline'])}\n{n['body']}\n")


# --- commands ---

def cmd_add(args) -> None:
    profile.add_airport(args.icao, args.note or "")
    print(f"Tilføjet {args.icao.upper()} til databasen.")


def cmd_remove(args) -> None:
    profile.remove_airport(args.icao)
    print(f"Fjernet {args.icao.upper()} fra databasen.")


def cmd_airports(args) -> None:
    airports = profile.list_airports()
    if not airports:
        print("Databasen er tom. Tilføj med:  python3 main.py add EDDK --note ...")
        return
    print("Dine pladser:")
    for a in airports:
        note = f"  ({a['note']})" if a.get("note") else ""
        print(f"  {a['icao']}{note}")


def cmd_presets(args) -> None:
    presets = profile.list_presets()
    if not presets:
        print("Ingen gemte presets endnu.")
        return
    print("Gemte presets:")
    for name, icaos in presets.items():
        print(f"  {name}: {', '.join(icaos)}")


def cmd_brief(args) -> None:
    icaos = profile.load_preset(args.preset) if args.preset else args.airports
    if not icaos:
        raise SystemExit("Ingen pladser valgt. Brug --airports ELLER --preset.")

    now = datetime.now(timezone.utc)
    dep_dt = _parse_user_dt(args.dep_time) if args.dep_time else now
    arr_dt = _parse_user_dt(args.arr_time) if args.arr_time else dep_dt
    window = (min(dep_dt, arr_dt), max(dep_dt, arr_dt))

    if args.save_preset:
        profile.save_preset(args.save_preset, icaos)
        print(f"Gemt preset '{args.save_preset}': {', '.join(c.upper() for c in icaos)}")

    print(f"Flyve-vindue (UTC): {window[0]:%Y-%m-%d %H%M} -> {window[1]:%Y-%m-%d %H%M}")
    with open(_OUTPUT_FILE, "w") as dump:
        for icao in icaos:
            _report_airport(icao.upper(), window, dump)
    print(f"\nFuld tekst skrevet til: {_OUTPUT_FILE}")


def main() -> None:
    parser = argparse.ArgumentParser(description="NOTAM AI route briefing")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="tilføj en plads til databasen")
    p_add.add_argument("icao")
    p_add.add_argument("--note", help="valgfri note, fx 'home base'")
    p_add.set_defaults(func=cmd_add)

    p_rm = sub.add_parser("remove", help="fjern en plads fra databasen")
    p_rm.add_argument("icao")
    p_rm.set_defaults(func=cmd_remove)

    sub.add_parser("airports", help="vis databasen").set_defaults(func=cmd_airports)
    sub.add_parser("presets", help="vis gemte presets").set_defaults(func=cmd_presets)

    p_brief = sub.add_parser("brief", help="kør en briefing")
    src = p_brief.add_mutually_exclusive_group(required=True)
    src.add_argument("--airports", nargs="+", help="ICAO-koder, fx EDDK LFML")
    src.add_argument("--preset", help="navn på gemt preset")
    p_brief.add_argument("--dep-time", help='UTC "YYYY-MM-DD HHMM" (default: nu)')
    p_brief.add_argument("--arr-time", help='UTC "YYYY-MM-DD HHMM" (default: dep-time)')
    p_brief.add_argument("--save-preset", help="gem denne sammensætning under et navn")
    p_brief.set_defaults(func=cmd_brief)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
