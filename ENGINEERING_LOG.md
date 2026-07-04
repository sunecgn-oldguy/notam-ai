# Engineering Log — NOTAM AI

Dette dokument holder styr på **valg, beslutninger og status** for projektet, så vi
altid kan gå tilbage og se processen der førte os hertil. Nyeste øverst i ændringsloggen.

Kommunikation på dansk, kode/tekniske termer på engelsk.

---

## 1. Vision

En app (iOS, App Store) til piloter: vælg dine lufthavne (DEP/ARR/ALT/enroute),
og få de relevante NOTAMs **sorteret, afduplikeret og skrevet om til klar engelsk
tekst** — med den originale NOTAM altid ét tryk væk. Bruger: professionel pilot,
Færøerne. Først til eget brug, siden EU, siden verden.

**Kernen i problemet:** piloter drukner i kryptiske NOTAMs. Tre delproblemer, holdt
adskilt: (1) kryptisk sprog, (2) for meget støj, (3) relevans afhænger af flyvningen.

---

## 2. Arkitektur

Pipeline (deterministisk kode gør det billige; AI gør kun det svære):

```
FAA  →  rens+forkortelser  →  Q-linje  →  grovfilter  →  dato/tid-filter
                                                              │
                                    [ cache-opslag → AI kun ved miss ]  ← trin 5 + cache
                                                              │
                                                     læselig briefing
```

Ansvarsfordeling (vigtig):

```
Server    →  kun regnekraft: henter NOTAMs + kører AI. Holder API-nøgler.
             Cacher offentlige NOTAM-oversættelser. GEMMER INGEN brugerdata.
Telefon   →  brugerens ruter (lokalt + iCloud). Forlader aldrig enheden.
```

---

## 3. Beslutninger (med begrundelse)

| # | Beslutning | Hvorfor |
|---|-----------|---------|
| D1 | **Datakilde: FAA FNS/SWIM** | Eneste kilde der er gratis, et rigtigt API, dækker EKVG (verificeret live), og er lovlig at videredistribuere (US public domain). EAD er den "rigtige" EU-vej, men tung/dyr — gemt til skala. |
| D2 | **Deterministisk kode først, AI sidst** | NOTAMs er strukturerede (Q-linje: område, højde, emnekode). Forkortelser er en fast tabel. Lad kode gøre grovsortering + oversættelse af koder; AI laver kun de sidste 20%. Færre AI-fejl = færre sikkerhedsrisici. |
| D3 | **AI bag udskifteligt interface** | Claude nu → lokal qwen2.5:14b senere. `summarise(notam)` skjuler hvem der svarer. Skift = én miljøvariabel. |
| D4 | **AI skjuler aldrig — kun prioriterer/fletter/kollapser** | Sikkerhedskritisk. Alle rå NOTAMs altid tilgængelige. |
| D5 | **Pilot-kurateret lufthavnsvalg, ikke auto-langs-ruten** | Auto ville trække alle irrelevante pladser med. Pilot vælger fra sin egen database + presets. Fjerner problemet i stedet for at løse det. |
| D6 | **Output på engelsk** | Luftfartssprog. |
| D7 | **Militær = disregarded** (pilotens ord) | Afdæmpes/kollapses for civil flyvning; aldrig slettet. |
| D8 | **Flet NOTAMs om samme facilitet** | Fx 3 overlappende MTG-VOR → ét operationelt faktum. |
| D9 | **Original NOTAM i dropdown, ordret** | Piloten skal kunne efterprøve AI'en løbende — opbygger tillid. |
| D10 | **Input: ETD + EET** (ikke to datoer) | Pilot-native: afgangstid + flyvetid → app udleder ankomst = dato/tid-filterets vindue. |
| D11 | **Ruter gemmes på telefonen + iCloud** | Små data, offline, privat, ingen server/database nødvendig. Server gemmer aldrig ruter. |
| D12 | **Content-addressed cache af AI-svar** | NOTAM ens for alle → oversæt hver NOTAM én gang i verden, genbrug gratis. Nøgle = hash(rå tekst). ~90–98% mindre AI-forbrug ved skala. Ændret tekst → nyt hash → genberegnes automatisk. |
| D13 | **Hosting: Render** (start på free-tier) | suneg har ingen fast IP, manuel genstart ved strømudfald, væk ~50% af tiden → managed host frem for hjemmeserver. Serveren er let (AI kører hos Anthropic), så billigste plan er nok. Nøgle bor i Renders miljøvariabler. |

---

## 4. Status

**Motor (Python, kun stdlib indtil AI):**

| Trin | Modul | Status |
|------|-------|--------|
| 1. Hent rå NOTAMs (FAA) | `notam/faa.py` | ✅ virker (verificeret EDDK 21 / LFML 28) |
| 2. Rens + forkortelser | `notam/clean.py`, `abbreviations.py` | ✅ |
| 3. Q-linje-parser | `notam/qline.py` | ✅ |
| 4. Grovfilter (relevans) | `notam/relevance.py` | ✅ (kategori + militær-afdæmpning) |
| 6. Dato/tid-filter | `notam/timing.py` | ✅ |
| —  Enrich (limer 2+3) | `notam/enrich.py` | ✅ |
| —  Lufthavnsdatabase + presets | `notam/profile.py` | ✅ |
| 5. AI-lag (udskifteligt) | `notam/llm.py` | 🟡 skitseret: `none`/`claude`/`qwen`-udbydere. Live API-test mangler. |
| —  Cache af AI-svar | `notam/cache.py` | ✅ skitseret + testet (miss→gem→hit) |
| —  Briefing-samler (JSON) | `notam/briefing.py` | ✅ skitseret + testet (hele kæden → dicts) |
| —  HTTP-server (Flask) | `server.py` + `requirements.txt` | 🟡 push-klar; ikke deployet endnu. Guide: `DEPLOY_RENDER.md` |
| CLI | `main.py` | ✅ (`add`, `airports`, `presets`, `brief --dep … --etd …`-lignende) |

**Prototype (mobil web-artifact):** ✅ fuld visuel prototype — input-skærm (DEP/ARR/ALT/ENR,
IATA+ICAO, ETD/EET), NOTAM/Weather-faner, burger→About, AI-filtreret briefing med original
NOTAM i dropdown, gem/hent/slet ruter (localStorage). **Data er stadig bagt (EDDK→LFML)** —
ingen live-hentning endnu.

**Ikke live endnu:** ingen server → felterne henter ikke nye NOTAMs; AI-laget er ikke kørt
mod rigtig model.

---

## 5. Filoversigt

```
NOTAM AI/
  main.py                  CLI: byg database, kør briefing
  notam/
    faa.py                 trin 1 — hent rå NOTAMs fra FAA
    clean.py               trin 2 — HTML-afkodning + forkortelses-udvidelse
    abbreviations.py       kurateret ICAO-forkortelsesordbog
    qline.py               trin 3 — parse Q-linjen (område/højde/emne)
    enrich.py              limer trin 2+3 på en rå NOTAM
    relevance.py           trin 4 — kategori + militær-afdæmpning
    timing.py              trin 6 — er NOTAM aktiv i flyve-vinduet?
    llm.py                 trin 5 — udskifteligt AI-lag (none/claude/qwen)
    cache.py               content-addressed cache af AI-svar
    profile.py             pilotens lufthavnsdatabase + presets
  data/                    airports.json, presets.json, notam_cache.json
  route_notams.txt         seneste briefing-dump (til inspektion)
  ENGINEERING_LOG.md       dette dokument
```

---

## 6. Åbne beslutninger / næste skridt

- **Gør den ægte:** lille server (fx Flask) der eksponerer motoren, så app'en henter live.
  Kræver sunegs server eller midlertidig sky-hosting.
- **Kør AI-laget mod rigtig model:** test `NOTAM_LLM=claude` (kræver `ANTHROPIC_API_KEY` på
  serveren) og sammenlign side om side med `NOTAM_LLM=qwen` (Ollama lokalt) — den eneste
  ærlige test af om qwen2.5:14b er god nok.
- **Modelvalg til Claude:** oversættelse er let → `claude-haiku-4-5`/`claude-sonnet-5` er
  billigere og nok. Sat som `_CLAUDE_MODEL` i `llm.py` (ét sted).
- **Fuld IATA→ICAO-opslagstabel** (prototypen har kun en demo-håndfuld).
- **Naviair-tilladelse** til de danske/færøske data som juridisk backup før udgivelse.
- **Enroute-geometri:** geometri-filteret bliver først rigtig stærkt når vi tilføjer
  NOTAMs *langs* ruten (militærområder, GPS-jamming).

---

## 7. Ændringslog

### 2026-07 — Fundament + prototype
- Afklaret vision, bruger, og de tre delproblemer.
- Research af datakilder → valgt FAA FNS (D1). EKVG-dækning verificeret live.
- Bygget motor trin 1–4 + 6 + enrich + profile (kun stdlib, ingen pakker).
- Pilotens output-spec fanget fra hans annoteringer (kondensér, fold-ud, dato-gate,
  militær disregarded, flet dubletter).
- Bygget interaktiv mobil-prototype; itereret efter pilotens skitse (DEP/ARR side om side,
  ETD/EET, faste NOTAM/Weather-faner, gem/hent ruter).
- Trin 5 (AI-lag) + cache skitseret: udskifteligt interface + content-addressed cache;
  testet miss→gem→hit med `none`-udbyder. Live model-test udestår.
- Oprettet denne Engineering Log.
- Valgt **Render** som hosting (D13). Bygget push-klar server: `notam/briefing.py`
  (JSON-samler, testet mod live data), `server.py` (Flask, `/health` + `/briefing`),
  `requirements.txt`, `DEPLOY_RENDER.md`. Deploy udestår (kræver GitHub-repo + Render-konto).
