"""Tests for document-reference (trigger) NOTAM handling and obstacle category.

Run:  python3 test_triggers.py
"""

from notam import triggers
from notam.enrich import enrich
from notam.relevance import category


def n(raw):
    return enrich({"raw": raw, "start": "", "end": ""})


TRIG1 = n(
    "A3951/26 NOTAMN\n"
    "Q) LFMM/QMNHW/IV/BO /A /000/999/4544N00505E005\n"
    "A) LFLL B) 2606220400 C) 2607301600\n"
    "E) AIRAC AIP SUP 089/26 - PAHASE 1 ACT"
)
TRIG2 = n(
    "A1642/26 NOTAMN\n"
    "Q) LFMM/QMPTT/IV/BO /A /000/999/4326N00513E025\n"
    "A) LFML B) 2603190000 C) 2610292359\n"
    "E) TRIGGER NOTAM - AIRAC AIP SUP 014/26 MODIFIED : NEW VALIDITY DATES.\n"
    "SUBJECT : AD USE RESTRICTIONS DUE TO MODIFICATION OF THE AD LFML PARKING AREA."
)
TRIG3 = n(  # A2931/26 — a trigger that DOES carry content (taxiway works)
    "A2931/26 NOTAMN\n"
    "Q) LFMM/QMNTT/IV/BO /A /000/999/4544N00505E005\n"
    "A) LFLL B) 2606220000 C) 2610312359\n"
    "E) TRIGGER NOTAM - AIRAC AIP SUP 089/26.\n"
    "TAXIWAY TL REHABILITATION WORKS ON THE AD.\n"
    "WORKS DATE OF PHASES WILL BE ANNOUNCED BY NOTAM.\n"
    "THIS AIP SUP IS AVBL AT WWW.SIA.AVIATION-CIVILE.GOUV.FR"
)
CRANE = n(
    "P4062/25 NOTAMN\n"
    "Q) LFBB/QOBCE/IV/M  /A /000/999/4338N00122E005\n"
    "A) LFBO B) 2512100600 C) 2702261700\n"
    "E) 2 OBSTACLES : FIX CRANE AND MOBILE CRANE :\n"
    "- PSN 433835.318N 0012023.081E\n"
    "- FIX CRANE : HEIGHT 98FT, ELEV 600FT, LIGHTING DAY AND NIGHT."
)

fails = 0


def chk(name, cond):
    global fails
    if not cond:
        fails += 1
    print(f"[{'ok' if cond else 'FAIL'}] {name}")


chk("trig1 detected", triggers.is_document_ref(TRIG1))
s1 = triggers.summary(TRIG1)
chk("trig1 keeps ref", "AIP SUP 089/26" in s1)
chk("trig1 invents NO ILS", "ILS" not in s1.upper())
chk("trig1 has no content -> see supplement", "see supplement" in s1)
print("    trig1:", s1)

chk("trig3 detected", triggers.is_document_ref(TRIG3))
s3 = triggers.summary(TRIG3)
chk("trig3 keeps taxiway content", "TAXIWAY TL" in s3.upper())
chk("trig3 drops URL boilerplate", "WWW" not in s3.upper())
print("    trig3:", s3)

chk("trig2 detected (TT + text)", triggers.is_document_ref(TRIG2))
s2 = triggers.summary(TRIG2)
chk("trig2 keeps real subject", "PARKING" in s2.upper())
print("    trig2:", s2)

chk("crane is NOT a trigger", not triggers.is_document_ref(CRANE))
chk("crane category = Obstacle", category(CRANE) == "Obstacle")
print("    crane category:", category(CRANE))

print()
print("ALL PASSED" if fails == 0 else f"{fails} FAILED")
raise SystemExit(1 if fails else 0)
