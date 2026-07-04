"""Deterministic relevance classification (step 4).

This is the plain-math grovfilter. It does NOT try to decide fine-grained
relevance ("is this about the runway I'll land on?") — that needs flight detail
and is the LLM's job in step 5. Its honest job here is:

  1. tag each NOTAM with a human category from the ICAO Q-code subject, and
  2. demote obvious noise (military items on a civil IFR flight)

Nothing is ever deleted. Every NOTAM gets a tier ("high" or "low"); "low" just
means "show it lower / collapsed". The raw text always stays available.
"""

from __future__ import annotations

# ICAO Q-code subject groups: the first letter of the 2-letter subject
# (e.g. "MP" -> "M" -> movement/landing area). Danish labels for the UI.
_Q_GROUPS: dict[str, str] = {
    "A": "Airspace",
    "C": "Comms / radar",
    "F": "Facilities",
    "G": "GPS / GNSS",
    "I": "ILS",
    "L": "Lighting",
    "M": "Runway / movement",
    "N": "Navaids",
    "O": "Other",
    "P": "ATC procedures",
    "R": "Airspace restr.",
    "S": "ATS services",
    "W": "Warnings",
    "X": "Other",
}

# Default flight context. Overridable — this is the one place to change policy.
DEFAULT_CONTEXT = {
    "ifr": True,             # professional IFR flight
    "demote_military": True,  # push military-only NOTAMs to the bottom
}


def category(notam: dict) -> str:
    """Human category for a NOTAM, from its Q-code subject group."""
    q = notam.get("qline")
    if not q or not q["q_subject"]:
        return "Unknown"
    return _Q_GROUPS.get(q["q_subject"][0], "Other")


def _is_military(notam: dict) -> bool:
    body = notam.get("body", "").upper()
    return (
        notam.get("keyword", "").upper() == "MILITARY"
        or "[US DOD" in body
        or "MIL PART" in body
    )


def classify(notam: dict, context: dict | None = None) -> dict:
    """Return {tier, reason, category} for one enriched NOTAM."""
    ctx = context or DEFAULT_CONTEXT
    cat = category(notam)

    if ctx.get("demote_military") and _is_military(notam):
        return {"tier": "low", "reason": "militær (civil flyvning)", "category": cat}

    return {"tier": "high", "reason": "", "category": cat}
