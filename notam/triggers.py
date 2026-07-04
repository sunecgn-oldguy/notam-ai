"""Document-reference ("trigger") NOTAMs — handled deterministically, no AI.

A trigger NOTAM just announces that an AIP Supplement or Amendment is in effect;
the real content lives in the referenced document, NOT in the NOTAM. There is
nothing for the AI to simplify — it can only guess, which caused a hallucination
(inventing "ILS App" for a bare AIP-SUP trigger). So we detect these in code and
build an honest summary from the NOTAM's own words only.
"""

from __future__ import annotations

import re

_REF = re.compile(r"\bAIP\s+(?:SUP|AMDT)\s+[\w/]+", re.I)
_SUBJECT = re.compile(r"SUBJECT\s*:?\s*(.+)", re.I | re.S)
_PHASE = re.compile(r"\bPHASE\s*(\d)", re.I)


def is_document_ref(notam: dict) -> bool:
    """True for AIP SUP / AMDT / trigger NOTAMs (Q-code condition 'TT' or text)."""
    text = notam.get("body", "").upper()
    q = notam.get("qline") or {}
    return (q.get("q_condition") == "TT"
            or "AIP SUP" in text or "AIP AMDT" in text or "TRIGGER NOTAM" in text)


def summary(notam: dict) -> str:
    """Honest, AI-free summary built only from the NOTAM's own text."""
    text = " ".join(notam.get("body", "").split())
    ref_m = _REF.search(text)
    ref = ref_m.group(0).upper() if ref_m else "AIP document"

    subj_m = _SUBJECT.search(text)
    if subj_m:
        subject = " ".join(subj_m.group(1).split()).rstrip(" .,")
        if len(subject) > 140:
            subject = subject[:140].rstrip(" .,") + "…"
        return f"{ref}: {subject}"

    ph = _PHASE.search(text)
    tail = f", Phase {ph.group(1)}" if ph else ""
    return f"{ref} active{tail} — see supplement"
