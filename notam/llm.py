"""The swappable AI layer (step 5).

One simple interface — summarise(notam) -> readable text — hides which engine
answers. Switch Claude for a local qwen2.5:14b by setting the NOTAM_LLM
environment variable; nothing else in the code changes (Ousterhout: a deep
module behind a simple interface).

The call is deliberately flight-INDEPENDENT: it sees a single raw NOTAM and
nothing about the flight. That is what makes its result identical for every
pilot and cacheable globally (see cache.py). Flight-specific relevance stays in
the deterministic layer (relevance.py) — it is cheap and never needs the AI.

Providers (env NOTAM_LLM):
  none   — no AI; return the deterministic cleaned text. Runs today, costs
           nothing, and lets the whole pipeline work before any key/model.
  claude — Anthropic API. The key lives on the server (ANTHROPIC_API_KEY),
           never in the app.
  qwen   — local qwen2.5:14b via Ollama on localhost.
"""

# Wiring — Used by: briefing.py (_summarise_parallel + _view call summarise()).
#          Calls: triggers.py (skip AI for AIP-SUP refs), cache.py (global reuse),
#          usage.py (token counting), timing.py (parse_notam_dt for cache expiry).
#          See ARCHITECTURE.md for how this fits the pipeline.

from __future__ import annotations

import json
import os
import urllib.request

from notam import cache, triggers, usage
from notam.timing import parse_notam_dt

_SYSTEM = (
    "Rewrite one aviation NOTAM as the shortest possible line for a professional "
    "pilot. Shorten by dropping filler, NOT by abbreviating. Mirror the NOTAM's own "
    "wording: keep its aviation shorthand and units (RWY, ILS, MHz, FT, NM, U/S) — "
    "do not spell them out — and do NOT invent your own abbreviations for words it "
    "spells out (if it writes MOVEMENT keep MOVEMENT, never 'Mvt'). Any abbreviation "
    "stays UPPERCASE, as in the source.\n"
    "SAFETY-CRITICAL: use ONLY what the NOTAM text says. Never add a system, "
    "facility, procedure or detail that is not written. Do NOT guess what an AIP "
    "Supplement, procedure or referenced document contains — if the NOTAM only "
    "points to a supplement/document, say just that (e.g. 'AIP SUP 089/26 active, "
    "Phase 1').\n"
    "SAFETY-CRITICAL: any number, coordinate, frequency or UNIT you include must be "
    "copied exactly as the source writes it. NEVER convert feet<->metres, never "
    "round, never relabel a unit. If the source gives metres keep metres; if feet "
    "keep feet.\n"
    "If the NOTAM lists many values (minima per runway, a table, coordinate lists, "
    "several frequencies), give ONLY the gist — e.g. 'LPV minima raised, all RWYs' — "
    "and do NOT transcribe the numbers; the exact figures stay in the original NOTAM "
    "(one tap away).\n"
    "Otherwise keep the operational essentials: what is affected, where, and key "
    "limits. Keep explicit directives and prohibitions verbatim — DO NOT USE, "
    "CLOSED, PROHIBITED, MANDATORY, CONTACT … — never soften, paraphrase away, or "
    "drop them; the instruction is the whole point.\n"
    "Do NOT state the NOTAM's validity or effective dates/times — if it is shown it "
    "is active, and the exact times are in the original. Only mention time if the "
    "NOTAM limits activity to specific daily hours a pilot must plan around.\n"
    "Do NOT include raw latitude/longitude coordinates — pilots can't use them and "
    "the exact position is in the original; if the NOTAM gives a bearing/distance "
    "from the airport (e.g. RDL179/2.3NM), keep that instead.\n"
    "Drop filler and the airport name (already grouped). No preamble."
)

# Bump this when the prompt/style changes, so old cached summaries are re-made.
_STYLE = "9"


def summarise(notam: dict) -> str:
    """Readable text for one enriched NOTAM, cached across all users."""
    if triggers.is_document_ref(notam):
        return triggers.summary(notam)         # deterministic, no AI (no hallucination)
    ckey = _STYLE + "\x00" + notam["raw"]      # style version folded into the key
    hit = cache.get(ckey)
    if hit is not None:
        return hit                        # free — someone already processed it
    provider = os.environ.get("NOTAM_LLM", "none")
    text, in_tok, out_tok = _provider()(notam)
    if in_tok or out_tok:                 # only real model calls cost tokens
        usage.record(provider, in_tok, out_tok)
    cache.put(ckey, text, expires=_expiry(notam), model=provider)
    return text


def _expiry(notam: dict) -> float | None:
    end = parse_notam_dt(notam.get("end", ""))
    return end.timestamp() if end is not None else None


def _provider():
    name = os.environ.get("NOTAM_LLM", "none")
    return {"none": _none, "claude": _claude, "qwen": _qwen}.get(name, _none)


# ---------------- providers ----------------

def _none(notam: dict):
    """No AI: the deterministic cleaned body from enrich.py (already readable)."""
    return notam["body"], 0, 0             # (text, input_tokens, output_tokens)


# Translation is an easy task, so the default is the cheapest/fastest model.
# Override per-deploy with the NOTAM_MODEL env var (e.g. claude-sonnet-5) — no
# code change needed.
_CLAUDE_MODEL = os.environ.get("NOTAM_MODEL", "claude-haiku-4-5")
_claude_client = None


def _claude(notam: dict):
    global _claude_client
    import anthropic  # only imported for this provider
    if _claude_client is None:
        _claude_client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY
    msg = _claude_client.messages.create(
        model=_CLAUDE_MODEL,
        max_tokens=300,
        system=_SYSTEM,
        messages=[{"role": "user", "content": notam["raw"]}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    return text, msg.usage.input_tokens, msg.usage.output_tokens


_OLLAMA_URL = "http://localhost:11434/api/generate"


def _qwen(notam: dict):
    body = json.dumps({
        "model": "qwen2.5:14b",
        "system": _SYSTEM,
        "prompt": notam["raw"],
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        _OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    # Ollama reports token counts too, so the counter carries over to qwen.
    return (data.get("response", "").strip(),
            data.get("prompt_eval_count", 0), data.get("eval_count", 0))
