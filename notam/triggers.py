"""Document-reference ("trigger") NOTAMs — handled deterministically, no AI.

A trigger NOTAM just announces that an AIP Supplement or Amendment is in effect;
the real content lives in the referenced document, NOT in the NOTAM. There is
nothing for the AI to simplify — it can only guess, which caused a hallucination
(inventing "ILS App" for a bare AIP-SUP trigger). So we detect these in code and
build an honest summary from the NOTAM's own words only.
"""

# Wiring — Used by: llm.py (checked first in summarise(); if is_document_ref()
#          is True we return summary() and spend no AI). Calls nothing internal.
#          See ARCHITECTURE.md.

from __future__ import annotations

import re

_REF = re.compile(r"\bAIP\s+(?:SUP|AMDT)\s+\d[\w/]*", re.I)   # number starts with a digit
_PHASE = re.compile(r"\bPHASE\s*(\d)", re.I)
_BARE_PHASE = re.compile(r"P\w*HASE\s*\d\s*(?:ACT|ACTIVE)?", re.I)  # tolerate 'PAHASE' typo

# Segments that add no operational content — dropped when extracting the subject.
_BOILER = ("WWW", "HTTP", "AVAILABLE AT", "AVBL AT", "VALIDITY",
           "ANNOUNCED BY NOTAM", "WILL BE ANNOUNCED")


def is_document_ref(notam: dict) -> bool:
    """True for AIP SUP / AMDT / trigger NOTAMs (Q-code condition 'TT' or text)."""
    text = notam.get("body", "").upper()
    q = notam.get("qline") or {}
    return (q.get("q_condition") == "TT"
            or "AIP SUP" in text or "AIP AMDT" in text or "TRIGGER NOTAM" in text)


def summary(notam: dict) -> str:
    """Honest, AI-free summary built only from the NOTAM's own text.

    Strip boilerplate (reference, TRIGGER NOTAM, validity, URL, "announced by
    NOTAM") and keep whatever real content is left — e.g. "TAXIWAY TL
    rehabilitation works". If nothing meaningful remains, defer to the supplement.
    """
    text = " ".join(notam.get("body", "").split())
    ref_m = _REF.search(text)
    ref = ref_m.group(0).upper() if ref_m else "AIP document"

    body = re.sub(r"\bTRIGGER NOTAM\b\s*-?\s*", " ", text, flags=re.I)
    body = re.sub(r"\bAIRAC\b", " ", body, flags=re.I)
    body = _REF.sub(" ", body)
    body = re.sub(r"\bSUBJECT\b\s*:?\s*", " ", body, flags=re.I)

    keep = []
    for seg in re.split(r"\.\s+|\n", body):
        seg = seg.strip(" -.:")
        if not seg or _BARE_PHASE.fullmatch(seg.upper()):
            continue
        if any(k in seg.upper() for k in _BOILER):
            continue
        keep.append(seg)

    content = " ".join(keep).strip(" -.:")
    if content:
        if len(content) > 140:
            content = content[:140].rstrip(" .,") + "…"
        return f"{ref}: {content}"

    ph = _PHASE.search(text)
    tail = f", Phase {ph.group(1)}" if ph else ""
    return f"{ref} active{tail} — see supplement"
