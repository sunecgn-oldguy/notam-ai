# Teknisk rapport — NOTAM & WX AI

En gennemgang af hele applikationen: alle scripts, alle funktioner, og hvordan de
arbejder sammen. Rapporten er tænkt som en **læse-guide til koden** — den følger
samme rækkefølge som data bevæger sig gennem systemet, så du kan læse den side om
side med kildefilerne.

Fagudtryk (function, endpoint, thread pool, cache, parse, regex …) og
luftfarts­termer (NOTAM, METAR, TAF, Q-line, FL, ILS …) står på engelsk med vilje;
de forklares i **Ordliste** til sidst.

> Se også `ARCHITECTURE.md` (kort dataflow-diagram) og de `Wiring —`-noter der
> står øverst i hver `notam/`-fil. Denne rapport går et lag dybere: funktion for
> funktion.

---

## Indhold

1. [Kernefilosofi](#1-kernefilosofi)
2. [De to entry points](#2-de-to-entry-points)
3. [En request fra ende til anden](#3-en-request-fra-ende-til-anden)
4. [Lag 1 — Input og HTTP (`server.py`)](#4-lag-1--input-og-http-serverpy)
5. [Lag 2 — Hentning af rådata (`faa.py`, `weather.py`)](#5-lag-2--hentning-af-rådata)
6. [Lag 3 — Berigelse og parsing (`enrich`, `clean`, `qline`, `abbreviations`)](#6-lag-3--berigelse-og-parsing)
7. [Lag 4 — Deterministisk filtrering (`relevance`, `timing`, `schedule`)](#7-lag-4--deterministisk-filtrering)
8. [Lag 5 — AI-laget (`llm`, `triggers`, `cache`, `usage`)](#8-lag-5--ai-laget)
9. [Lag 6 — Baner (`runways`, `airports`)](#9-lag-6--baner-og-kodeopslag)
10. [Orkestrering (`briefing.py`)](#10-orkestrering-briefingpy)
11. [Sidefunktioner (`feedback`, `ratelimit`, `profile`)](#11-sidefunktioner)
12. [Front-end (`web/index.html`)](#12-front-end-webindexhtml)
13. [Build-scripts og datafiler](#13-build-scripts-og-datafiler)
14. [Tests](#14-tests)
15. [Infrastruktur og deploy](#15-infrastruktur-og-deploy)
16. [Gennemgående design-mønstre](#16-gennemgående-design-mønstre)
17. [Ordliste](#17-ordliste)

---

## 1. Kernefilosofi

Hele applikationen bygger på én regel:

> **Al beslutnings-logik ligger i deterministisk kode. AI'en bruges KUN til at
> omskrive én NOTAM til kortere, læsbar tekst.**

Det betyder at *relevans*, *tidsvindue*, *militær-frasortering*, *vejr-kategori*
og *bane-valg* alle afgøres af almindelige funktioner, som du kan læse, teste og
stole på. AI'en ser aldrig din rute og træffer aldrig en sikkerheds­beslutning —
den kan ikke hallucinere en NOTAM væk eller opfinde en. Det er grunden til at
koden er lagdelt som den er.

En anden gennemgående regel er **fail-safe = vis mere, skjul aldrig ved tvivl**:
kan en tid eller et skema ikke fortolkes, vises NOTAM'en (se `timing.py`,
`schedule.py`); fejler en AI-oversættelse, falder vi tilbage til den rene tekst
(`briefing.py`); fejler vejr eller NOTAM-hentning for én plads, kører resten
videre (`weather.py`, `briefing.py`).

---

## 2. De to entry points

Der er to måder at køre motoren på. De deler alle byggeklodserne i `notam/`, men
samler dem hvert sit sted:

| Fil | Kaldes af | Output | Bruger AI/vejr/cache? |
|-----|-----------|--------|-----------------------|
| **`server.py`** | appen (browser/telefon) via HTTP | JSON | Ja — hele pipelinen |
| **`main.py`** | udvikler i terminalen | tekst + `route_notams.txt` | Nej — stopper efter tidsfiltrering |

> ⚠️ **Vigtigt for læsning:** `main.py` er den *gamle* test-CLI. Den wirer sin egen
> kopi af pipelinen (fetch → enrich → classify → time-gate) og stopper bevidst
> før AI-, vejr-, bane- og cache-lagene. Den rigtige produktionsvej som appen
> bruger, er `briefing.py`. Når du læser `main.py`, ser du altså *ikke* det appen
> faktisk gør — kun de fire første trin. `profile.py` bruges også kun af CLI'en.

---

## 3. En request fra ende til anden

Det følgende er hele rejsen for ét tryk på **"Get briefing"** i appen. Læs det som
et kort; de nummererede trin uddybes i afsnit 4–10.

```
Browser (web/index.html, render-flow)
   │  POST /briefing  { dep, arr, alt, etd, eet, day }
   ▼
server.py
   ├─ _BRIEFING_LIMIT.allow()      (ratelimit.py)   20/time pr. IP — ellers 429
   ├─ _airports(data)              gør dep/arr/alt til [(icao, role)] via airports.to_icao()
   ├─ _window(data)                gør day+etd+eet til (start, end) i UTC
   ▼
briefing.build(airports, window)
   │
   ├─ TRIN 1 · pr. plads, parallelt (ThreadPoolExecutor, 16 tråde) — _process_airport():
   │     weather.fetch(icao, window)          METAR/TAF → farvekategori + vind
   │     faa.fetch_notams(icao)               rå NOTAMs (fanges hvis FAA fejler)
   │     enrich.enrich(n)                      → n.body, n.qline, n.d
   │        clean.clean()                        HTML-decode + abbreviation-expand
   │        qline.parse_qline()                  Q-line → koordinat/FL/subject
   │     relevance.classify(n)                 → tier (high/low) + kategori
   │     timing.is_active_during(n)            aktiv i vinduet? (→ schedule.active_during)
   │
   ├─ TRIN 2 · pr. relevant NOTAM, parallelt (16 tråde) — _summarise_parallel():
   │     llm.summarise(n):
   │        triggers.is_document_ref()?        AIP-SUP → AI-fri, ærlig tekst
   │        cache.get()                        set før? gratis genbrug
   │        provider (none/claude/qwen)        omskriv til kort linje
   │        usage.record() + cache.put()       tæl tokens, gem
   │     cache.flush()                         skriv cachen én gang til disk
   │
   └─ TRIN 3 · _airport_view() pr. plads:
         runways.view(icao, wind)              baner + vind-favoriseret ende
         _view()/_raw_view()                   byg JSON-felter
   ▼
JSON → browseren → render() tegner accordions
```

---

## 4. Lag 1 — Input og HTTP (`server.py`)

Flask-serveren er en **tynd adapter**: den oversætter en HTTP-request til
funktions­kald ind i motoren, og motorens dict-resultat til JSON. Al forretnings­logik
ligger i `notam/`; Flask findes kun her. Render kører den med
`gunicorn server:app`.

### Endpoints (routes)

| Route | Funktion | Gør |
|-------|----------|-----|
| `GET /` | `index()` | Sender `web/index.html` (browser-UI'en, samme origin) |
| `GET /health` | `health()` | Returnerer `{"ok": true}` — bruges af keep-alive-pingeren |
| `GET /usage` | `usage_report()` | Token-forbrug siden serverstart (`usage.snapshot()`) |
| `POST /briefing` | `make_briefing()` | **Hovedendpointet** — se nedenfor |
| `POST /feedback` | `make_feedback()` | Gemmer + emailer pilot-feedback (`feedback.submit()`) |

### `make_briefing()` — hovedendpointet
1. `_BRIEFING_LIMIT.allow(_client_key())` — rate-limit-tjek. Overskredet → svar
   `429` med en besked (se `ratelimit.py`).
2. `request.get_json(force=True, silent=True) or {}` — læs JSON, tolerér skrald
   (bliver til en tom briefing i stedet for en fejl).
3. `briefing.build(_airports(data), _window(data))` — kør motoren, returnér JSON.

### Hjælpefunktioner (input-parsing)

| Funktion | Signatur | Gør |
|----------|----------|-----|
| `_client_key()` | `→ str` | Klient-IP til rate-limiting. Render sidder bag en proxy, så den bruger `X-Forwarded-For`s første hop, ellers `remote_addr` |
| `_codes(raw)` | `str → list[str]` | Splitter en streng på mellemrum/komma/punktum, kører hver kode gennem `airports.to_icao()`, og skærer af ved 20 koder (`[:20]`) |
| `_airports(data)` | `dict → list[(icao, role)]` | Bygger den samlede plads-liste med roller: `dep→DEP`, `arr→ARR`, `alt→ALT`, `enr→ENR` |
| `_hhmm(s)` | `str → (int, int)` | Parser `"0800"` eller `"08:00"` til `(8, 0)` |
| `_window(data)` | `dict → (datetime, datetime)` | Bygger flyve-vinduet i UTC: dagens (eller morgendagens) dato + ETD som start, + EET som varighed → slut |

**Samspil:** `server.py` importerer `briefing`, `feedback`, `ratelimit`, `usage`
og `airports.to_icao`. Det er det eneste sted `flask` optræder.

---

## 5. Lag 2 — Hentning af rådata

### `faa.py` — rå NOTAMs fra FAA

Henter NOTAMs fra FAA's gratis, offentlige NOTAM Search-service. Kun Python
standard library (ingen pakker at installere).

| Funktion | Signatur | Gør |
|----------|----------|-----|
| `fetch_notams(icao)` | `str → list[dict]` | POST'er en form-request til FAA-endpointet for én ICAO-kode, læser JSON, og normaliserer hver NOTAM |
| `_normalise(n)` | `dict → dict` | Plukker kun de felter vi bruger og giver dem klare navne (`id`, `airport`, `airport_name`, `keyword`, `issued`, `start`, `end`, `raw`). `raw` HTML-decodes med `html.unescape` så fx `&apos;` bliver til `'` |

**Robusthed:** `fetch_notams` har med vilje *ingen* `try/except` — den kaster ved
FAA-fejl. Kalderen bestemmer selv: produktions­vejen (`briefing._process_airport`)
fanger det per plads; CLI'en (`main.py`) gør ikke. **Kaldes af:**
`briefing._process_airport` og `main._report_airport`.

### `weather.py` — METAR/TAF og vejr-farve

Henter METAR (aktuelt vejr) og TAF (prognose) fra `aviationweather.gov` og
udregner en **farvekategori** (green/blue/amber/red) deterministisk — ingen AI.
Badge-farven afspejler prognosen *i flyve-vinduet* (den værste kategori en
TAF-periode forudser mens du er der), med fallback til den aktuelle METAR.

| Funktion | Signatur | Gør |
|----------|----------|-----|
| `fetch(icao, window)` | `→ dict` | Hovedfunktionen. Henter METAR+TAF, udregner `metar_category`, `taf_category`, den viste `category`, `wind` og `windy`-flaget |
| `_wind(metar)` | `→ {dir, speed, gust}` | Parser vind-gruppen (fx `28015G25KT`), konverterer MPS→kt, markerer calm/VRB som `dir=None` |
| `_wind_kt(text)` | `→ int\|None` | Max vind (steady eller gust) i knob, eller `None` hvis teksten slet ikke har en vind-gruppe (så kalderen kan bære forrige vind videre) |
| `taf_category(taf, ws, we)` | `→ str\|None` | Værste kategori under `[ws, we]` |
| `taf_windy(taf, ws, we)` | `→ bool` | True hvis en TAF-periode i vinduet forudser vind > 20 kt |
| `_taf_conditions(taf, ws, we)` | `→ list[(cavok, vis, ceil, wind)]` | **Kernen** — bygger en tidslinje af TAF-perioder (`FM`, `BECMG`, `TEMPO`, `PROB`) og returnerer forholdene for hver periode der overlapper vinduet. Bærer vis/ceiling/vind fremad gennem ændringer der ikke gentager dem |
| `_ddhh(dd, hh, ref)` | `→ datetime\|None` | Oversætter en TAF dag-time (`DDHH`) til en `datetime`, forankret på flyve-datoen. Håndterer `HH=24` og månedsskift |
| `_classify(cavok, vis_m, ceil_ft)` | `→ str\|None` | Regel-tabellen: CAVOK/GOOD/OK/MARGINAL/LOW VIS ud fra den værste af sigt og skydække |
| `_visibility_m(metar)` | `→ int\|None` | Sigt i meter — håndterer både statute miles (`SM`) og den metriske 4-cifrede gruppe |
| `_ceiling_ft(metar)` | `→ int\|None` | Laveste skyhøjde i fod fra `BKN`/`OVC`/`VV`-grupper |
| `_get(url)` | `→ str` | HTTP-GET der **fejler pænt** (returnerer `""` ved enhver fejl), så vejr-problemer aldrig vælter en briefing |

**Samspil:** `_wind` bruges af både `_wind_kt` og `fetch`; `fetch`s vind føres
videre til `runways.view()`. **Kaldes af:** `briefing._process_airport`.

---

## 6. Lag 3 — Berigelse og parsing

### `enrich.py` — limet mellem clean og qline

Tager en rå NOTAM-dict fra `faa.py` og returnerer en *kopi* med tre ekstra felter.

| Funktion | Signatur | Gør |
|----------|----------|-----|
| `body_text(raw)` | `str → str` | Trækker `E)`-beskeden ud (selve NOTAM-teksten) som én ren linje; klipper hvor `F)`/`G)`-højdegrænserne begynder |
| `d_field(raw)` | `str → str` | Trækker `D)`-skema-feltet ud (teksten mellem `D)` og `E)`) |
| `enrich(notam)` | `dict → dict` | Returnerer `{**notam, body, qline, d}` hvor `body = clean(body_text(raw))`, `qline = parse_qline(raw)`, `d = d_field(raw)` |

**Kaldes af:** `briefing._process_airport` og `main._report_airport`.
**Kalder:** `clean.clean`, `qline.parse_qline`.

### `clean.py` — tekstoprydning

To deterministiske jobs så AI'en aldrig skal: (1) HTML-decode, (2) udvid kuraterede
ICAO-abbreviations til almindelige ord.

| Funktion | Signatur | Gør |
|----------|----------|-----|
| `decode_entities(text)` | `str → str` | `html.unescape` — `&amp;` → `&` osv. |
| `expand_abbreviations(text)` | `str → str` | Erstatter kendte forkortelser med deres udvidelse |
| `clean(text)` | `str → str` | Kører begge: `expand_abbreviations(decode_entities(text))` |

**Detalje:** ved import bygges ét stort regex (`_pattern`) af alle nøgler i
`CONTRACTIONS`, sorteret længste-først (så `U/S` vinder over `U`). Token-grænserne
gør at kun *hele* tokens matches — navaid-navne som `MRM` røres aldrig.
**Kalder:** `abbreviations.CONTRACTIONS`. **Kaldes af:** `enrich.py`.

### `qline.py` — parsing af Q-line

Q-linjen pakker den strukturerede metadata der lader os filtrere med ren matematik
i stedet for at gætte. Eksempel: `Q) EDGG/QNMXX/IV/BO /AE/000/999/5047N00736E025`.

| Funktion | Signatur | Gør |
|----------|----------|-----|
| `parse_qline(raw)` | `str → dict\|None` | Finder Q-linjen, splitter på `/`, og udtrækker `fir`, `qcode`, `q_subject` (tegn 2-3), `q_condition` (tegn 4-5), `traffic`, `purpose`, `scope`, `fl_lower`/`fl_upper` (flight levels), `lat`/`lon` (decimalgrader) og `radius_nm`. Returnerer `None` hvis der ingen brugbar Q-line er |
| `_find_qline(raw)` | `str → str\|None` | Finder linjen der starter med `Q)` og returnerer teksten efter markøren |
| `_dm_to_degrees(deg, min, hemi)` | `→ float` | Grader+minutter + halvkugle-bogstav → fortegns-decimalgrader (`S`/`W` = negativ) |

> ⚠️ `fl_lower`/`fl_upper` er `None` hvis FL-feltet ikke er rene cifre. Kaldere der
> formaterer dem, skal guarde (det gør `main._qline_summary` nu).

**Kaldes af:** `enrich.py`. Resultatet bruges videre af `relevance.py`,
`briefing.py` og `main.py`.

### `abbreviations.py` — data

Ét kurateret dict, `CONTRACTIONS`, fra ICAO/FAA-forkortelse til almindeligt
engelsk (`"RWY": "runway"`, `"CLSD": "closed"`, `"U/S": "unserviceable"` …).
Bevidst konservativt: kun koder vi er sikre på, så station-identifiers ikke rammes.
**Bruges af:** `clean.py`.

---

## 7. Lag 4 — Deterministisk filtrering

### `relevance.py` — kategori og militær-frasortering

Den "grovfilter" der (1) sætter en menneske-læsbar kategori på hver NOTAM ud fra
Q-code subject, og (2) demoterer åbenlys støj (militære items på en civil
IFR-flyvning). **Intet slettes nogensinde** — hver NOTAM får en `tier` (`high`
eller `low`); `low` betyder bare "vis nederst / foldet sammen".

| Funktion | Signatur | Gør |
|----------|----------|-----|
| `classify(notam, context=None)` | `→ {tier, reason, category}` | Hovedfunktionen. Militær (hvis `demote_military`) → `tier="low"`; ellers `tier="high"` |
| `category(notam)` | `→ str` | Menneske-kategori fra Q-code subject: slår først den finere 2-bogstavs-tabel op (`_Q_SUBJECT`: `MR`→Runway, `PI`→Approach …), ellers gruppen fra første bogstav (`_Q_GROUPS`: `I`→ILS, `M`→Movement …) |
| `priority(cat)` | `→ int` | Sorterings-rang — lavere vises først. Rækkefølgen er `_ORDER` (ILS, Approach, Runway …); ukendte kategorier havner sidst |
| `_is_military(notam)` | `→ bool` | True hvis `keyword == "MILITARY"` eller teksten indeholder `[US DOD` / `MIL PART` |

`DEFAULT_CONTEXT = {ifr: True, demote_military: True}` — det ene sted policy
ændres. **Kaldes af:** `briefing.py` og `main.py`.

### `timing.py` — tidsvindue-gate

Afgør om en NOTAM overlapper flyve-vinduet. To gates: (1) B)/C)-gyldigheds­perioden
skal overlappe vinduet, OG (2) D)-dagsskemaet (hvis det kan parses) må ikke
udelukke det.

| Funktion | Signatur | Gør |
|----------|----------|-----|
| `is_active_during(notam, start, end)` | `→ bool` | Kombinerer de to gates. Returnerer False kun hvis B/C ikke overlapper ELLER `schedule.active_during` returnerer eksplicit `False` |
| `parse_notam_dt(s)` | `str → datetime\|None` | Parser FAA's `"MM/DD/YYYY HHMM"`. `None` = permanent/åben (`PERM`) eller uparsbar. `EST`-markøren (estimated) ignoreres |
| `_bc_overlap(notam, start, end)` | `→ bool` | Overlapper NOTAM'ens start/slut vinduet? Uparsbar start behandles som "allerede aktiv", uparsbar slut som "åben" (begge fail-safe) |

**Kaldes af:** `briefing.py` + `main.py` (`is_active_during`) og `llm.py` +
`briefing.py` (`parse_notam_dt` til cache-udløb og NOTAM-alder). **Kalder:**
`schedule.active_during`.

### `schedule.py` — D)-skemaet (det sværeste felt)

D) er semi-fritekst i mange formater. Vi parser de almindelige, entydige og falder
**altid** tilbage til "antag aktiv" når vi ikke er sikre.

Returkontrakt: `active_during(d, start, end) → True | False | None`
- `True` = aktiv på et tidspunkt i vinduet
- `False` = med sikkerhed inaktiv (den *eneste* måde en NOTAM skjules)
- `None` = intet D)-felt eller et format vi ikke forstår → kalderen beholder den synlig

| Funktion | Signatur | Gør |
|----------|----------|-----|
| `active_during(d, start, end)` | `→ True\|False\|None` | Hovedfunktionen. `H24` → True. Ellers parses hvert komma-segment til en regel og der itereres dag-for-dag gennem vinduet for at finde et overlap |
| `_parse_segment(seg)` | `→ {applies, bands}\|None` | Deler et segment i tidsbånd (`0700-1630`) og en dato/ugedag-prædikat |
| `_parse_dates(prefix)` | `→ predicate\|None` | Bygger en `applies(date)→bool`-funktion for de forskellige formater: månedsspænd på tværs af måneder (`JUN 29-JUL 04`), samme-måned-spænd (`JUN 26-30`), dagliste (`JUN 26 28 30`), ugedagsspænd (`MON-FRI`), ugedagsliste (`SAT SUN`) |
| `_mins(hhmm)` | `→ int` | `"0730"` → minutter siden midnat (450) |
| `_overlaps(w1, w2, b1, b2)` | `→ bool` | Overlapper vinduets minut-interval et tidsbånd? Håndterer bånd der krydser midnat |
| `_window_minutes_on(date, start, end)` | `→ (float, float)` | Vinduets minut-interval på en given dato (eller `(None, None)` hvis dagen ikke berøres) |

**Kaldes af:** `timing.py`.

---

## 8. Lag 5 — AI-laget

### `llm.py` — det udskiftelige AI-interface

Ét simpelt interface — `summarise(notam) → str` — skjuler hvilken engine der
svarer. Skift Claude ud med en lokal `qwen2.5:14b` ved at sætte miljø­variablen
`NOTAM_LLM`; intet andet i koden ændrer sig (et *deep module* bag et simpelt
interface). Kaldet er bevidst **flight-uafhængigt**: det ser én rå NOTAM og intet
om flyvningen — det er dét der gør resultatet ens for alle piloter og globalt
cachebart.

| Funktion | Signatur | Gør |
|----------|----------|-----|
| `summarise(notam)` | `dict → str` | Hovedfunktionen. (1) Er det en trigger/document-ref? → `triggers.summary` (AI-fri). (2) Cache-hit? → returnér gratis. (3) Ellers: kald provider, `usage.record`, `cache.put`, returnér |
| `_provider()` | `→ callable` | Slår `NOTAM_LLM` op og returnerer `_none`, `_claude` eller `_qwen` (default `_none`) |
| `_none(notam)` | `→ (str, 0, 0)` | Ingen AI: returnerer den rene, oprydede `body` fra `enrich`. Koster 0 tokens |
| `_claude(notam)` | `→ (str, in, out)` | Kalder Anthropic-API'et (model fra `NOTAM_MODEL`, default `claude-haiku-4-5`). Klienten lazy-initieres og genbruges. Læser nøglen fra `ANTHROPIC_API_KEY` |
| `_qwen(notam)` | `→ (str, in, out)` | Kalder en lokal Ollama på `localhost:11434` |
| `_expiry(notam)` | `→ float\|None` | NOTAM'ens slut­tidspunkt som Unix-timestamp → bruges som cache-udløb |

`_SYSTEM` er den lange system-prompt der styrer omskrivnings-stilen (kort, spejl
kildens ordvalg, aldrig konvertér enheder, behold direktiver som `CLOSED`
verbatim). `_STYLE = "9"` er en versions-tæller der foldes ind i cache-nøglen —
hæv den når prompten ændres, så gamle cachede summaries laves om.
**Kaldes af:** `briefing.py`. **Kalder:** `triggers`, `cache`, `usage`,
`timing.parse_notam_dt`.

### `triggers.py` — document-ref-NOTAMs (ingen AI)

En trigger-NOTAM annoncerer bare at et AIP Supplement/Amendment er i kraft; det
rigtige indhold ligger i *dokumentet*, ikke i NOTAM'en. Der er intet for AI'en at
forkorte — den kan kun gætte (hvilket gav en hallucination). Så vi opdager dem i
kode og bygger et ærligt resumé af NOTAM'ens *egne* ord.

| Funktion | Signatur | Gør |
|----------|----------|-----|
| `is_document_ref(notam)` | `→ bool` | True hvis Q-code condition er `TT`, eller teksten indeholder `AIP SUP`/`AIP AMDT`/`TRIGGER NOTAM` |
| `summary(notam)` | `→ str` | Fjerner boilerplate (reference, "TRIGGER NOTAM", validity, URL, "announced by NOTAM") og beholder det reelle indhold. Er der intet tilbage, henvises der ærligt til supplementet (fx `AIP SUP 089/26 active, Phase 1 — see supplement`) |

**Kaldes af:** `llm.summarise` (tjekkes *først*, så trigger-NOTAMs aldrig bruger AI).

### `cache.py` — global, indholds-adresseret cache

Den vigtigste token-besparelse. En NOTAM er ens for alle piloter i verden, så en
rå NOTAM behøver kun omskrives *én gang*. Vi nøgler på et hash af den rå tekst:
samme tekst → samme resultat, genbrugt gratis af alle. Ændrer FAA teksten, ændrer
hashet sig, og NOTAM'en laves automatisk om — vi kan aldrig vise en forældet
oversættelse.

| Funktion | Signatur | Gør |
|----------|----------|-----|
| `key(raw)` | `str → str` | Stabilt SHA-256-hash af den whitespace-normaliserede tekst (16 tegn) |
| `get(raw, now=None)` | `→ str\|None` | Cachet tekst, eller `None` ved miss/udløb |
| `put(raw, text, expires, model)` | `→ None` | Opdaterer hukommelsen med det samme; skriver til disk **højst hvert par sekunder** (write-coalescing) |
| `flush()` | `→ None` | Tvinger ventende ændringer til disk nu — kaldes af `briefing.build` til sidst |
| `cleanup(now=None)` | `→ int` | Fjerner udløbne entries, returnerer antal fjernede |
| `_ensure_loaded` / `_read_file` / `_write_file` | interne | Loader dict'en én gang; skriver atomisk (skriv til `.tmp`, `os.replace`) så en samtidig læsning aldrig ser en halv fil |

**Trådsikkerhed:** hele store'et er et dict i hukommelsen bag en `threading.Lock`
(summaries kører parallelt, se `briefing.py`). **Effektivitet:** med
write-coalescing + `flush()` laver en briefing ~1 skrivning i stedet for N.
**Åben ende:** `cleanup()` kaldes ikke nogen steder endnu (på Renders free-disk
nulstilles cachen dog ved redeploy). **Kaldes af:** `llm.py` + `briefing.py`.

### `usage.py` — token-tæller

Provider-agnostisk tæller. Både Claude og qwen rapporterer token-tal, som
akkumuleres i én form. Tæller kun *rigtige* model-kald (cache-hits, trigger-NOTAMs
og `none`-provideren koster intet). In-memory og per-proces → nulstilles ved
serverstart.

| Funktion | Signatur | Gør |
|----------|----------|-----|
| `record(provider, input_tokens, output_tokens)` | `→ None` | Lægger til totalerne og til `by_provider` (trådsikkert) |
| `snapshot()` | `→ dict` | Læser totalerne (til `/usage`-endpointet) |
| `reset()` | `→ None` | Nulstiller (bruges i test) |

**Kaldes af:** `llm.record` og `server.usage_report`.

---

## 9. Lag 6 — Baner og kodeopslag

### `runways.py` — baner + vind-favoriseret ende

| Funktion | Signatur | Gør |
|----------|----------|-----|
| `view(icao, wind=None)` | `→ list[dict]` | Banerne for en plads (længste først), hver tagget med den vind-favoriserede ende (`fav = "le"\|"he"\|None`). Ved calm/variable/vind under 3 kt vælges ingen ende |
| `_angle(a, b)` | `→ int` | Mindste vinkel (0–180°) mellem to bearings |
| `_load()` | `→ dict` | Lazy-loader `runways.json` én gang |

Headings er grader **TRUE** — samme reference som METAR-vind — så den favoriserede
ende er en direkte sammenligning, ingen magnetisk variation. "Favoured" betyder
kun "mest op i vinden af de to ender"; det er *ikke* et runway-in-use-valg.
**Kaldes af:** `briefing._airport_view` (med METAR-vinden). **Læser:**
`notam/runways.json` (bygget af `tools/build_runways.py`).

### `airports.py` — IATA → ICAO

| Funktion | Signatur | Gør |
|----------|----------|-----|
| `to_icao(code)` | `str → str` | 3-bogstavs IATA slås op i tabellen → ICAO; 4-tegns kode antages allerede at være ICAO; ukendt kode returneres uændret |
| `_lookup()` | `→ dict` | Lazy-loader `iata_icao.json` (~8500 koder) én gang |

**Kaldes af:** `server._codes`. **Læser:** `notam/iata_icao.json`.

---

## 10. Orkestrering (`briefing.py`)

Det ene sted hele pipelinen wires sammen for **produktions­vejen**. Ren stdlib —
returnerer almindelige dicts, så det serialiserer direkte til JSON.

| Funktion | Signatur | Gør |
|----------|----------|-----|
| `build(airports, window)` | `→ dict` | **Indgangen.** Trin 1: kør `_process_airport` for hver plads i en `ThreadPoolExecutor` (16 tråde). Trin 2: `_summarise_parallel` for alle relevante NOTAMs, så `cache.flush()`. Trin 3: `_airport_view` for hver plads |
| `_process_airport(airport, window)` | `→ dict` | Pr. plads: hent vejr, hent+enrich NOTAMs (**fanget** — FAA-fejl → tom gruppe med `error="notam_fetch_failed"`), classify + tidsfiltrér, split i `military`/`high`/`inactive`. `high` sorteres efter kategori-prioritet |
| `_summarise_parallel(notams)` | `→ None` | Fylder `n["_summary"]` for hver NOTAM i en trådpulje. En fejlet AI-kald vælter aldrig briefingen (fallback = `body`) |
| `_airport_view(g)` | `→ dict` | Bygger plads-JSON: `icao`, `role`, `name`, `counts`, `error`, `weather`, `runways`, og lister af `relevant`/`military`/`inactive` |
| `_view(n)` | `→ dict` | Fuldt view af én relevant NOTAM: `id`, `age`, `category`, `summary`, `raw`, `start`, `end`, og `area` (koordinat/radius/FL fra Q-line) |
| `_raw_view(n)` | `→ dict` | Kun `id` + rå tekst — der bruges ingen AI på frasorterede/udenfor-vindue NOTAMs |
| `_age(n)` | `→ str` | Hvor længe siden NOTAM'en blev udstedt, kompakt: `today`, `3d`, `2w`, `5mo`, `1y` |

**Hvorfor to trådpuljer?** Begge trin er I/O-bundne (venter på FAA / vejr / Claude),
så ekstra tråde er billige og skærer wall-clock: en hel rute fanges ud på én gang
i stedet for i bølger. **Kaldes af:** `server.make_briefing`.

---

## 11. Sidefunktioner

### `feedback.py` — pilot-feedback (fil + email)

Gemmer feedback til en lokal fil (**backup**) og emailer den (den holdbare kanal,
da Renders free-disk slettes ved redeploy). Credentials i miljø­variabler, aldrig
i koden (`FEEDBACK_SMTP_USER`, `FEEDBACK_SMTP_PASS`, `FEEDBACK_TO`).

| Funktion | Signatur | Gør |
|----------|----------|-----|
| `submit(message, email, context)` | `→ dict` | Validerer (tom besked afvises), bygger en entry, gemmer + emailer, og returnerer hvad der faktisk skete (`{ok, saved, emailed}`) |
| `_save(entry)` | `→ bool` | Appender én JSON-linje til `data/feedback.jsonl`. Fejler pænt |
| `_send_email(entry)` | `→ bool` | Bygger en MIME-mail med pilotens skærm vedhæftet som `feedback.json` og sender via Gmail SMTP (STARTTLS). Er SMTP-vars ikke sat, springes email over (fil-backup kørte stadig). En mail-fejl bryder aldrig requesten |

**Kaldes af:** `server.make_feedback`.

### `ratelimit.py` — sliding-window rate limiter

Beskytter det dyre `/briefing`-endpoint (mange FAA- og Claude-kald pr. kald) mod
cost/DoS på en offentlig URL.

| Metode | Signatur | Gør |
|--------|----------|-----|
| `RateLimiter(max_calls, per_seconds)` | konstruktør | Fx `(20, 3600)` = 20 kald i timen |
| `allow(key, now=None)` | `→ bool` | Registrerer et kald for `key` (klient-IP) og returnerer True hvis det er inden for grænsen. Ved False registreres intet (en blokeret klient skubber ikke sit eget vindue) |
| `_sweep(now, cutoff)` | intern | Rydder lejlighedsvist nøgler uden nylige kald, så dict'en holdes bounded |

**Sliding window** (ikke faste buckets), så man ikke kan burste 2× over en
bucket-kant. In-memory og per-proces. **Kaldes af:** `server.make_briefing`.

### `profile.py` — pilotens plads-database (kun CLI)

To JSON-filer under `data/`: `airports.json` og `presets.json`.

| Funktion | Gør |
|----------|-----|
| `list_airports()` / `add_airport(icao, note)` / `remove_airport(icao)` | Læs/tilføj/fjern pladser |
| `list_presets()` / `save_preset(name, icaos)` / `load_preset(name)` | Navngivne plads-sammensætninger |
| `_load(path, default)` / `_save(path, data)` | Interne JSON-hjælpere |

> Bruges **kun** af `main.py` (CLI'en). Den deployede web-app gemmer ruter i
> browserens `localStorage`, så `profile.py` er ikke i appens request-vej.

---

## 12. Front-end (`web/index.html`)

Én selvstændig fil: HTML + CSS + vanilla JavaScript, ingen frameworks, ingen
build. Serveres af `server.index()`. Bygger request'en, kalder `/briefing` og
`/feedback`, og tegner svaret som fold-ud accordions.

### Layout (HTML)
Top-bar med **Feedback**-knap · **Starair Routes** (chips man trykker på for at
udfylde) · **DEP** / **ARR** · **ALT / ENROUTE** · **Day** (Today/Tomorrow) ·
**ETD** (UTC, default 23:30) / **EET** (hh:mm) · **Get briefing** · resultat-området
`#out` · en skjult feedback-modal.

### Vigtige JS-funktioner

| Funktion | Gør |
|----------|-----|
| `codes(raw)` | Normaliserer en input-streng til mellemrums-separerede store-bogstav-koder |
| `esc(s)` | Escaper `& < >` — **XSS-beskyttelse** anvendt konsekvent på al utrusted tekst før den sættes ind i DOM'en |
| `render(data)` | Hovedtegneren: bygger en accordion pr. plads med badge, vejr, baner, relevante NOTAMs (hver med rå tekst i en fold-ud) og de sammenfoldede grupper |
| `showBanner(msg, kind)` | Viser en tydelig farvet banner (`warn`/`crit`) i resultat-området — bruges til rate-limit/fejl |
| `weatherBlock(w)` / `wxBadge(w)` / `wxPill(cat)` | Tegner vejr-boksen, farve-badgen og de små Now/ETD-piller |
| `runwayLine(a)` | Tegner bane-linjen med den vind-favoriserede ende accentueret |
| `windText(wind)` / `z2` / `z3` | Formaterer vind (`wind 280/15G25`) med nul-padding |
| `ageText(a)` | `"2w"` → `"2w old"`; lader `today`/`new` stå |
| `foldRaw(title, items)` | En sammenfoldet gruppe med hver NOTAMs fulde rå tekst |

### Ruter (localStorage)
`DEFAULT_ROUTES` er Starair-seed'et. Hver pilots egne ændringer gemmes i browseren
(`RKEY = 'notamwx.routes.v1'`) og lægges ovenpå — ingen login, privat til enheden.

| Funktion | Gør |
|----------|-----|
| `loadRoutes()` / `saveRoutes()` | Læs/gem ruter fra/til `localStorage` |
| `applyRoute(r)` | Udfylder DEP/ARR/ALT-ENROUTE fra en rute; dropper koder der allerede er dep/arr (så ingen plads hentes to gange) |
| `renderRoutes()` | Tegner rute-chips (med slet-knap i edit-mode) |
| `sortRoutes()` / `lastCode(s)` | Sortér ruter efter destination |

### Handlers og feedback
- **Get briefing** (`#go`): bygger `body`, POST'er til `/briefing`, håndterer `429`
  (→ `showBanner('warn')`) og andre fejl (→ `showBanner('crit')`).
- **Feedback**-modal: `fbContext()` fanger den aktuelle skærm som data (rute, tider,
  åbne NOTAMs, sidste briefing), `fbSummary()` laver en kort visning, og
  `fbSend`-handleren POST'er til `/feedback`. `fbClose()` lukker modalen (bemærk den
  globale CSS-regel `[hidden]{display:none!important}` der får `hidden`-attributten
  til at vinde over `display:flex`).

---

## 13. Build-scripts og datafiler

### `tools/build_runways.py` — engangs-script
Bygger `notam/runways.json` fra det offentlige OurAirports-datasæt.

| Funktion | Gør |
|----------|-----|
| `build()` | Henter `runways.csv`, springer lukkede baner over, beholder `le`/`he`-idents, TRUE headings og længde pr. ICAO. Sorterer længste bane først |
| `_heading(raw, ident)` | TRUE heading fra datasættet; fallback til ident (`06` → `060`) |

Køres manuelt (`python3 tools/build_runways.py`) når data skal opdateres.

### Datafiler
| Fil | Indhold | Bygget af |
|-----|---------|-----------|
| `notam/iata_icao.json` | IATA→ICAO-tabel (~8500) | OurAirports (offentligt) |
| `notam/runways.json` | Baner pr. ICAO (~2,6 MB) | `tools/build_runways.py` |
| `notam/abbreviations.py` | Forkortelses-dict | Kurateret i hånden |
| `data/*.json` (runtime) | cache, airports, presets, feedback | Genereres ved kørsel — `.gitignore`'d |

---

## 14. Tests

Fire selvstændige test-scripts (ren stdlib, ingen pytest — kør `python3 test_X.py`).
De dækker de rene, deterministiske funktioner; netværkslag (FAA/vejr/LLM) testes
bevidst ikke.

| Fil | Dækker |
|-----|--------|
| `test_runways.py` | `runways.view` + `_angle` (vind-favoriseret ende) |
| `test_schedule.py` | `schedule.active_during` (D)-feltets formater) |
| `test_triggers.py` | `triggers.is_document_ref` + `summary` |
| `test_weather.py` | `weather._wind`, `_wind_kt`, kategori-klassifikation |

**Utestet endnu** (foreslåede næste tests): `qline.parse_qline`,
`timing._bc_overlap`, `relevance.classify`, `cache` (get/put/expiry).

---

## 15. Infrastruktur og deploy

| Fil | Rolle |
|-----|-------|
| `requirements.txt` | `flask`, `gunicorn`, `anthropic` — motoren selv er ren stdlib |
| `server.py` | Køres af Render som `gunicorn server:app --bind 0.0.0.0:$PORT` |
| `.github/workflows/keepalive.yml` | Pinger `/health` hvert ~10. min, så den gratis Render-service ikke går i dvale (ellers ~30-50s cold start) |
| `.gitignore` | Holder `data/` og `route_notams.txt` (runtime-state) ude af git |
| `DEPLOY_RENDER.md` | Trin-for-trin deploy-guide |
| `ENGINEERING_LOG.md` | Beslutnings-log (source of truth for status) |

**Miljøvariabler (sat i Render):** `ANTHROPIC_API_KEY`, `NOTAM_LLM` (`none`/`claude`/`qwen`),
`NOTAM_MODEL` (valgfri model-override), `FEEDBACK_SMTP_USER`, `FEEDBACK_SMTP_PASS`,
`FEEDBACK_TO`.

---

## 16. Gennemgående design-mønstre

Genkend disse fem mønstre — de forklarer *hvorfor* koden ser ud som den gør:

1. **Deterministisk-først, AI-sidst.** Alle beslutninger i kode; AI kun til prosa.
   Se lag 4 vs. lag 5.
2. **Fail-safe = over-show.** Ved tvivl vises NOTAM'en; en fejl i ét lag vælter
   ikke briefingen. Se `timing`, `schedule`, `weather._get`, `briefing`.
3. **Deep module bag et simpelt interface** (Ousterhout). `llm.summarise(notam)`
   skjuler tre providers; `cache`/`profile` skjuler lagringen. Du kan skifte
   implementering uden at røre kalderne.
4. **Content-addressed caching.** Nøgle = hash af indhold → automatisk
   invalidering når kilden ændrer sig, og globalt genbrug på tværs af piloter.
5. **I/O-bunden parallelisme.** `ThreadPoolExecutor` fanger hele ruten ud på én
   gang; trådsikre delte ressourcer (`cache`, `usage`) bag `Lock`.

---

## 17. Ordliste

| Term | Betydning |
|------|-----------|
| **NOTAM** | *Notice to Air Missions* — officiel besked om forhold der påvirker flyvning (lukket bane, ude-af-drift ILS, luftrums­restriktion …) |
| **METAR** | Aktuel, observeret vejr-rapport for en flyveplads |
| **TAF** | *Terminal Aerodrome Forecast* — vejr-prognose for en flyveplads |
| **Q-line** | Den kodede linje i en ICAO-NOTAM (`Q) …`) med subject, luftrum, koordinat, radius og flight levels |
| **Q-code** | 5-tegns kode i Q-linjen; tegn 2-3 = subject (emne), 4-5 = condition (status) |
| **FL (Flight Level)** | Højde i hundreder af fod ved standardtryk (`FL090` = 9000 ft) |
| **ILS** | *Instrument Landing System* — præcisions-indflyvningshjælp |
| **ICAO / IATA** | 4-tegns hhv. 3-tegns flyveplads-koder (EKVG / FAE) |
| **CAVOK** | *Ceiling And Visibility OK* — godt vejr pr. definition |
| **Ceiling** | Skyhøjde (laveste BKN/OVC-lag) i fod |
| **Cat I minima** | Nedre grænse for standard-præcisions­indflyvning (~550 m sigt / 200 ft ceiling) |
| **AIP SUP / AMDT** | Supplement / Amendment til *Aeronautical Information Publication* — dokumentet en trigger-NOTAM peger på |
| **ETD / EET** | *Estimated Time of Departure* / *Estimated Elapsed Time* (flyvetid) |
| **IFR** | *Instrument Flight Rules* — professionel instrument-flyvning |
| **endpoint** | En HTTP-adresse serveren svarer på (fx `/briefing`) |
| **thread pool** | En pulje af tråde der kører opgaver samtidigt |
| **cache** | Mellemlager der genbruger et resultat i stedet for at genberegne |
| **regex** | *Regular expression* — tekst-mønster til søgning/parsing |
| **fail-safe** | Fejler i den sikre retning (her: viser mere frem for at skjule) |

---

*Rapporten dækker koden pr. commit `565f767`. Ændrer du en signatur, så opdatér
den relevante række her og i `Wiring —`-noten i den pågældende fil.*
