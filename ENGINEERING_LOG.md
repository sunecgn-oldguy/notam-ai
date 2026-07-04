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
| 6. Dato/tid-filter | `notam/timing.py` | ✅ B/C-periode + D)-skema |
| —  D)-skema-parser | `notam/schedule.py` (+ `test_schedule.py`) | ✅ 19 tests bestået |
| —  Enrich (limer 2+3+D) | `notam/enrich.py` | ✅ |
| —  Lufthavnsdatabase + presets | `notam/profile.py` | ✅ |
| 5. AI-lag (udskifteligt) | `notam/llm.py` | ✅ live: `NOTAM_LLM=claude` på Render skriver NOTAMs om til klar engelsk. (qwen-sti testes senere.) |
| —  Cache af AI-svar | `notam/cache.py` | ✅ skitseret + testet (miss→gem→hit) |
| —  Briefing-samler (JSON) | `notam/briefing.py` | ✅ skitseret + testet (hele kæden → dicts) |
| —  HTTP-server (Flask) | `server.py` + `requirements.txt` | ✅ live på Render (https://notam-ai.onrender.com); Fase 1 (uden AI) verificeret end-to-end mod live data. Guide: `DEPLOY_RENDER.md` |
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
- ~~Fuld IATA→ICAO-opslagstabel~~ ✅ løst (se ændringslog).
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
- Koden lagt på GitHub: **github.com/sunecgn-oldguy/notam-ai** (git init + commit + push).
- **Deployet live på Render:** https://notam-ai.onrender.com (Frankfurt, Free-tier).
  Fase 1 (uden AI) verificeret: `/health` + `/briefing` henter live FAA-data for EDDK/LFML/LFMN
  og returnerer korrekt filtreret JSON — nul token-forbrug.
- **Fase 2 live:** `ANTHROPIC_API_KEY` + `NOTAM_LLM=claude` sat i Render. Claude skriver nu
  NOTAMs om til klar engelsk. **Cache bevist i produktion:** første kald 29,3 s (betalt) →
  samme kald igen 0,9 s (cache-hit, gratis).
  - ⚠️ **Åben:** første kald ~29 s ligger tæt på gunicorns 30 s worker-timeout (per-NOTAM-kald
    sekventielt). Fix: `gunicorn … --timeout 120` i Render-start-kommandoen, og/eller skift til
    Haiku/Sonnet (hurtigere+billigere) — gør evt. modellen til env-variabel `NOTAM_MODEL`.
- **Løst:** `--timeout 120` sat i Render; model gjort valgbar (`NOTAM_MODEL`, standard nu
  `claude-haiku-4-5` — hurtigere+billigere).
- **Browser-UI live:** `web/index.html` serveres på `https://notam-ai.onrender.com/` (samme
  origin → ingen CORS). Rigtig udfyld-og-få-briefing-side på telefonen, drevet af live-motoren.
  Forsiden verificeret oppe (HTTP 200). Erstatter samtidig den tidligere "/"-404.
- **Bugfix — komplet IATA→ICAO:** pilot fandt at fx LIS/BOD/OPO gav 0 NOTAMs (kun demo-koder
  var kendt). Bygget fuld tabel fra OurAirports (`notam/iata_icao.json`, 8471 koder) + `notam/
  airports.py` (`to_icao`). Serveren oversætter nu alle koder; web-siden sender rå koder.
  Verificeret: LIS→LPPT, BOD→LFBD, OPO→LPPR.
- **Pilot-feedback (UX + AI-stil):** (1) kategori-mærkater til engelsk (`relevance.py`);
  (2) mærkat flyttet *over* NOTAM-teksten så teksten får fuld bredde (`web/index.html`);
  (3) AI-prompt strammet — behold luftfarts-forkortelser/units (MHz, NM, AMSL…), skær fyld,
  gentag ikke lufthavnsnavn. Cache-nøgle fik en `_STYLE`-version så gamle gavmilde svar erstattes.
- **⚠️ Sikkerhedsfejl fanget af pilot (units):** AI skrev fx `79FT` hvor kilden vist havde
  `…(79.37M)` — dvs. tog meter-tallet og satte FT på. Prompt hærdet: kopiér tal + UNITS ordret,
  **aldrig** konvertér ft↔m, aldrig relabel. Også presset mod “kortest muligt”. `_STYLE` → "3".
  (Bekræfter værdien af at have den rå NOTAM ét tryk væk.) TODO: verificér på den konkrete NOTAM.
- **Fulde originaler i "military" og "outside flight window":** disse grupper viser nu hele den
  rå NOTAM (ikke kun ID'et) — stadig **ingen AI** brugt på dem. `briefing.py` sender rå tekst
  (`_raw_view`); web-siden folder dem ud som `<pre class="raw">`.
- **Pilot-regel til TODO:** vises ⟺ aktiv på landingstidspunktet (kræver D)-parser); inaktive
  hører i "outside flight window", og tider udelades for viste (underforstået aktive).
- **Rækkefølge-fix (grupper):** militær tjekkes nu FØR tid, så al militær havner i
  "Military — disregarded" (aktiv eller ej). "Outside window" indeholder kun civile inaktive.
  Pilot fandt P5587 (BUNDESWEHR/ETNK, FAA=MILITARY) forkert i outside window.
- **Bedre kategorier + kortere tabeller (pilot):** "P"-gruppen omdøbt fra vildledende
  "ATC procedures" til præcise labels via 2-bogstavs Q-subject (QPO→"Approach minima",
  QPD→"Departure", QPI→"Approach"…). AI-prompt: transskribér IKKE tabeller (minima pr. RWY,
  koordinatlister) — giv kernen ("LPV minima raised, all RWYs"), tal bliver i originalen.
  `_STYLE`→"4".
- **AI dropper gyldighedstider** (`_STYLE`→"5"): vises ⟺ aktiv, så B/C-tider udelades af
  AI-linjen (de er i originalen); kun daglige tidsbegrænsninger nævnes. Interim indtil D)-parser.
- **D)-parser bygget (den rigtige, principielle løsning — ikke patch):** `notam/schedule.py`
  `active_during(D, start, end) → True/False/None`. **None ved uparsbar/manglende D) → skjuler
  ALDRIG** (sikkerhed frem for pænhed). Tolker H24, dagligt bånd, måned+dag(e)+bånd,
  cross-month-range, ugedage. `timing.is_active_during` = B/C-overlap OG D) ikke-sikkert-nej.
  Enrich udtrækker D)-feltet. **19 tests bestået** (`test_schedule.py`), inkl. Porto-kranens
  D). Løser gentagne “tid/outside window”-punkter ved kilden.

- **Trigger-/AIP-SUP-NOTAMs deterministisk** (`notam/triggers.py` + `test_triggers.py`): ingen
  AI, ingen hallucination — udtræk reference (+ evt. SUBJECT) fra NOTAM'ens egen tekst. Løser
  LYS-fejlen hvor AI opdigtede "ILS App" på en tom trigger.
- **AI dropper rå lat/long** (piloter kan ikke bruge dem; positionen er i originalen; behold
  bearing/afstand hvis givet). `_STYLE`→"7".
- **Kategori:** `OB`→"Obstacle", `OL`→"Obstacle lights" (kran stod som "Other").
- **Original NOTAM: HTML-koder afkodes** (`&apos;`→`'`, `&amp;`→`&`) også i den *viste* original
  (`faa._normalise`) — trofast, men læsbart. Malformet kilde (fx tredoblet "121.255MHZ") vises
  trofast; vi "reparerer" aldrig og opfinder aldrig.
- **Trigger-summary udtrækker nu indhold:** boilerplate (reference, TRIGGER NOTAM, validitet,
  URL, "announced by NOTAM") fjernes, resten beholdes. A2931 → "AIP SUP 089/26: TAXIWAY TL
  rehabilitation works" (indhold med); A3951 (tomt) → uændret "see supplement". Testet.
- **⚠️ AI beholder direktiver ordret** (`_STYLE`→"8"): "DO NOT USE"/CLOSED/PROHIBITED må aldrig
  blødes op eller droppes. Pilot fandt at ILS-NOTAM med "DO NOT USE" var reduceret til blot
  "false indications possible" — instruksen er selve pointen.
- **AI spejler kildens ordform** (`_STYLE`→"9"): forkort ved at fjerne fyld, ikke ved at
  forkorte ord. Behold kildens forkortelser; opfind aldrig egne (kilde "MOVEMENT" → behold, ikke
  "Mvt"). Forkortelser med STORT. Pilot fandt AI opfandt "Mvt".
- **Parallelisering + tråd-sikker cache:** FAA-hentninger (6 tråde) og AI-oversættelser
  (8 tråde) kører nu samtidig i `briefing.py`. Cachen er in-memory + lås + atomisk disk-skrivning
  (`cache.py`) — 33 samtidige skrivninger uden korruption. AI-delen forventes ~30 s → ~5 s.
  (Kold-start-dvale på gratis-plan er separat; løses med keep-alive/betalt.)
