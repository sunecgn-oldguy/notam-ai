"""Text cleanup for NOTAMs (step 2).

Two deterministic jobs, done in plain code so the LLM never has to:
  1. decode HTML entities the FAA feed leaves in the text (&apos; -> ')
  2. expand curated ICAO abbreviations into plain English words

Only whole-token matches are expanded, so navaid identifiers and names
(e.g. "MRM", "COL") are never touched.
"""

# Wiring — Used by: enrich.py (via clean()).  Calls: abbreviations.py (the word
#          list).  See ARCHITECTURE.md for the full map.

from __future__ import annotations

import html
import re

from notam.abbreviations import CONTRACTIONS

# One regex for all abbreviations. Longest keys first so "U/S" wins over "U".
# A token boundary here means "not a letter or digit" on both sides, which also
# works for slash-containing keys like "U/S".
_keys = sorted(CONTRACTIONS, key=len, reverse=True)
_pattern = re.compile(
    r"(?<![A-Za-z0-9])(" + "|".join(re.escape(k) for k in _keys) + r")(?![A-Za-z0-9])"
)


def decode_entities(text: str) -> str:
    """Turn HTML entities (&apos;, &amp;, ...) back into normal characters."""
    return html.unescape(text)


def expand_abbreviations(text: str) -> str:
    """Replace known ICAO contractions with their plain-English expansion."""
    return _pattern.sub(lambda m: CONTRACTIONS[m.group(1)], text)


def clean(text: str) -> str:
    """Full cleanup: decode entities, then expand abbreviations."""
    return expand_abbreviations(decode_entities(text))
