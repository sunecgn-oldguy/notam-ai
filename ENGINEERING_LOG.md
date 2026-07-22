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
| D14 | **Vejr-kilde: aviationweather.gov** | Gratis, ingen nøgle, global METAR/TAF (US NWS). Samme filosofi som FAA. |
| D15 | **Deterministisk-først for struktureret data** | Kategori, triggers, tider, vejr = kode (aldrig AI). AI kun til fri-tekst NOTAM-sprog. Krymper hallucination-fladen. |
| D16 | **Gemte ruter = frø i frontenden + on-device-redigering (ingen login)** | Starair-ruterne bages ind som `DEFAULT_ROUTES` (frø); hver enheds egne tilføjelser/sletninger gemmes i browserens `localStorage` og lægger sig ovenpå — realiserer D11's on-device-model for web. Ingen konti/database/server-state; dataen forlader aldrig enheden. Login er kun nødvendigt ved cross-device på fremmede enheder, server-side deling eller central styring (senere, offentligt-app-problem — bringer også auth + GDPR). iCloud-sync kommer gratis i iOS-appen. Bemærk: `data/` er gitignored → deploy-data bages ind i `notam/` eller `web/`. |
| D17 | **Bane-i-brug = deterministisk vind-favorit (OurAirports)** | Baner + retvisende heading fra OurAirports (samme kilde/licens som IATA→ICAO). METAR-vind er også retvisende → ren geometri (headwind-komponent), ingen AI, ingen magnetisk misvisning. Kun et *hint*: støj/preferential/ILS/ATC afgør bane-i-brug — UI siger det. Calm/VRB/<3 kt → intet valg. |
| D18 | **Skalerings-arkitektur: ingest → DB, eager på gemte ruter, lazy resten** | Fetch-per-request skalerer ikke (to pres: tid + tokens). Ved vækst: baggrunds-ingestion (poll → senere SWIM) fylder en database; pilot-kald serveres derfra (millisekunder, ingen live-fetch). Adskil de to omkostninger: **hente NOTAMs = gratis** (hent alt regelmæssigt) vs **AI = tokens** (eager kun på de gemte ruters pladser — lille/kendt/billigt; lazy for ad-hoc-pladser). Tokens ∝ ændringsrate, ikke trafik (målt: 358 civile NOTAMs på de 46 pladser → **~$0,34 at oversætte ALT én gang**). Migrering er *påbygning*: den deterministiske pipeline + content-cache er allerede adskilt fra AI. Fuld plan + faser i §6. |

---

## 4. Status

**Live app:** https://notam-ai.onrender.com (Render, Frankfurt, free-tier). Web-UI på `/`;
API: `POST /briefing`, `GET /health`, `GET /usage`. Env på Render: `ANTHROPIC_API_KEY`,
`NOTAM_LLM=claude`, valgfri `NOTAM_MODEL`. Start: `gunicorn server:app --bind 0.0.0.0:$PORT --timeout 120`.

**Motor** — kernen `notam/` er ren stdlib; kun serveren bruger flask/gunicorn/anthropic:

| Del | Modul | Status |
|-----|-------|--------|
| 1. Hent NOTAMs (FAA, HTML-afkodet) | `notam/faa.py` | ✅ |
| 2. Rens + forkortelser | `notam/clean.py`, `abbreviations.py` | ✅ |
| 3. Q-linje-parser | `notam/qline.py` | ✅ |
| 4. Relevans: kategori (Q-kode) + prioritet + militær | `notam/relevance.py` | ✅ |
| 6. Tid: B/C + D)-skema | `notam/timing.py`, `notam/schedule.py` | ✅ (19 tests) |
| Trigger/AIP-SUP (deterministisk) | `notam/triggers.py` | ✅ (tests) |
| Enrich (2+3+D) | `notam/enrich.py` | ✅ |
| Lufthavns-DB + presets | `notam/profile.py` | ✅ |
| IATA→ICAO (8471 koder) | `notam/airports.py` + `iata_icao.json` | ✅ |
| 5. AI-lag (none/claude/qwen) | `notam/llm.py` | ✅ live (Haiku) |
| Cache (content-addr., tråd-sikker) | `notam/cache.py` | ✅ |
| Token-tæller (udbyder-agnostisk) | `notam/usage.py` | ✅ (`/usage`) |
| Vejr: METAR/TAF + kategorier + vind + Windy | `notam/weather.py` | ✅ (27 tests, TAF-prognose) |
| Baner + vind-favoriseret ende | `notam/runways.py` + `runways.json` | ✅ (17 tests, OurAirports) |
| Briefing (parallel fetch+AI) | `notam/briefing.py` | ✅ |
| HTTP-server | `server.py` | ✅ live |
| Web-UI (mobil, vanilla) | `web/index.html` | ✅ live |
| CLI | `main.py` | ⚠️ ikke opdateret med nyeste felter |

**Live features:** ét-tryk **rute-chips** (Starair-standarder + redigerbare pr. enhed via `localStorage`,
ingen login); DEP/ARR + ALT/ENROUTE (IATA+ICAO),
Today/Tomorrow + ETD/EET → vindue til ETA; sammenfoldelige lufthavne; **bane-linje over vejret**
(`RWY 06/24 · 13L/31R · …` + vind, vind-favoriseret ende fremhævet); NOTAMs sorteret
ILS→Approach→Runway→Navaids→Movement→rest med alder (fx "3mo"); AI-omskrevne linjer + original
ordret i dropdown; militær + outside-window i fuld original; vejr-badge
(CAVOK kun når bogstaveligt rapporteret · GOOD ≥10km/5000ft · OK ≥5km/1500ft · MARGINAL · LOW VIS=Cat I-minima
≤550 m/200 ft) fra TAF-prognosen i flyve-vinduet + "Windy"-chip når vind >20 kt (METAR/TAF-vindue).

**AI-output-spec (i `llm.py` `_SYSTEM`, `_STYLE=9`):** spejl kildens ordform (udvid/forkort aldrig
selv); behold direktiver ordret (DO NOT USE); kopiér tal+units ordret (aldrig konvertér ft↔m);
opfind aldrig; drop validitetstider (vist ⟺ aktiv) + rå lat/long; tabeller → kun kernen.

**Tests:** `python3 test_schedule.py` / `test_triggers.py` / `test_weather.py` / `test_runways.py` (alle grønne).
**Deploy:** push til GitHub (sunecgn-oldguy/notam-ai) → Render auto-deployer (kan pushes herfra;
token i macOS-nøgleringen). Gratis-tier: kold-start ~30–50s efter dvale; cachen tømmes ved redeploy.

**Prototype-artifact** (claude.ai, bagt data) findes stadig som design-reference; den *rigtige* app er web-UI'et.

---

## 5. Filoversigt

```
NOTAM AI/
  server.py                Flask: / (web-UI), /briefing, /health, /usage
  main.py                  CLI (byg DB, kør briefing) — ikke opdateret med nyeste felter
  requirements.txt         flask, gunicorn, anthropic
  DEPLOY_RENDER.md         deploy-guide
  ENGINEERING_LOG.md       dette dokument
  web/index.html           mobil web-UI (vanilla HTML/CSS/JS) — redigerbare ruter (DEFAULT_ROUTES-frø + localStorage-editor)
  tools/build_runways.py   bygger notam/runways.json fra OurAirports (reproducerbart)
  notam/
    faa.py                 trin 1 — hent rå NOTAMs (FAA) + HTML-afkod
    clean.py, abbreviations.py   trin 2 — rens + forkortelses-ordbog
    qline.py               trin 3 — parse Q-linjen
    enrich.py              lim 2+3+D) på en NOTAM
    relevance.py           kategori (Q-kode) + prioritet + militær
    timing.py, schedule.py trin 6 — B/C-periode + D)-skema (tid-relevans)
    triggers.py            AIP-SUP/trigger-NOTAMs (deterministisk, ingen AI)
    llm.py                 trin 5 — udskifteligt AI-lag (none/claude/qwen) + prompt-spec
    cache.py               content-addressed, tråd-sikker cache
    usage.py               udbyder-agnostisk token-tæller
    weather.py             METAR/TAF + 4 farvekategorier (TAF-prognose i vinduet) + vindparser
    runways.py, runways.json   baner pr. ICAO + vind-favoriseret ende (OurAirports, 33.7k AD)
    airports.py, iata_icao.json   IATA→ICAO (8471 koder)
    profile.py             lufthavns-DB + presets
    briefing.py            samler hele kæden (parallel fetch + AI)
  test_schedule.py, test_triggers.py, test_weather.py, test_runways.py   tests
  data/                    (gitignored) presets, notam_cache, m.m.
```

---

## 6. Åbne beslutninger / næste skridt

- ~~**Kold-start (gratis-dvale ~30–50s):** keep-alive-ping~~ ✅ **løst:** GitHub Actions pinger `/health`
  hvert ~10. min (`.github/workflows/keepalive.yml`). Alternativ hvis cron-jitter giver enkelte kold-starts:
  UptimeRobot 5-min, eller betalt Render ($7/md, fjerner den helt + holder cachen varm).
- **Persistent cache:** gratis-tier tømmer cachen ved redeploy/dvale → Render-disk / Redis / SQLite
  for reel cross-user-genbrug ved skala.
- **qwen-sti:** test `NOTAM_LLM=qwen` (Ollama lokalt, qwen2.5:14b) side om side med Claude — den
  ærlige test af om den lokale model holder.
- **Flyvedato ud over i morgen:** kun Today/Tomorrow nu (TAF dækker ~24–30t). Fuldt dato-felt hvis nødvendigt.
- **Flere tests:** qline, clean, relevance er utestede.
- **Naviair-tilladelse** til danske/færøske data før udgivelse.
- **Enroute-geometri:** NOTAMs *langs* ruten (militærområder, GPS-jamming) — geometri-filteret bliver først stærkt her.
- **Kosmetik/valg:** "CAVOK"-badge dækker hele grøn-tieren (ikke kun literal CAVOK); Departure ligger
  i "rest" i sorteringen (pilot kan ønske højere); blandet casing i AI-linjer (kilde=STORT, udvidelser=små).
- ~~Fuld IATA→ICAO~~ · ~~server/live~~ · ~~D)-parser~~ · ~~vejr~~ · ~~token-tæller~~ · ~~sammenfoldelige AD~~ ✅ løst.

### Fase 2-plan — skalering: ingest → database (D18)

**Problemet:** nuværende model henter live fra FAA *ved hvert kald*. Med mange piloter der spørger
til overlappende pladser hentes samme data igen og igen (langsomt + hårdt ved FAA). To pres: **tid** og
**tokens**.

**Nøgle-indsigt: skil de to omkostninger ad.**

| Trin | Koster | Skalerer med |
|------|--------|--------------|
| Hente + parse NOTAMs | CPU + netværk (≈ gratis) | antal pladser |
| AI-oversætte | **tokens (de eneste rigtige penge)** | antal *nye/ændrede* NOTAMs |

**Arkitektur (to afkoblede dele):**

```
INGESTION (baggrund, uafhængig af trafik)
  hvert ~15-30 min:  hent NOTAMs for alle kendte pladser  →  parse (Q/kategori/tid/D)
                     →  AI-oversæt de NYE/ændrede  →  gem i DB
        │
        ▼
   [ Database ]  ← altid opdateret, altid klar
        ▲
        │
SERVING (pr. pilot-kald, millisekunder)
  slå pladser op i DB  →  filtrér på pilotens tidsvindue (deterministisk, billigt)  →  returnér
```

**AI-strategi (løser token-presset):** hent ALT regelmæssigt (gratis), men vær selektiv med tokens:
- **Eager** kun på pladserne i de **gemte ruter** (lille, kendt sæt, kæmpe overlap) → nul ventetid,
  næsten nul tokens. **Målt live (token-frit, 2026-07-05):** 420 NOTAMs på de 46 rute-pladser, heraf
  25 militær + 37 trigger/AIP-SUP = 0 AI (deterministisk); **358 AI-berettigede × ~0,1 øre = ~$0,34**
  at oversætte ALT én gang. Derefter kun *ændringer* (~$0,03/dag) → **~$1-2/md for HELE netværket**,
  uanset antal piloter/checks.
- **Lazy** for ad-hoc-pladser en pilot taster → brænd ikke tokens på noget ingen ser.
- Skalerer: så længe "eager-sættet" (∑ gemte ruter) er afgrænset, forbliver det billigt.

**Token-håndtag:** (1) tokens ∝ *ændringsrate*, ikke request-rate — steady-state er billigt; opdaterings-
frekvens = token-drejeknap. (2) **Prompt caching hjælper IKKE her:** system-prompten er ~600 tokens, langt
under Haiku 4.5's cache-minimum på **4.096 tokens** (verificeret mod Anthropics docs 2026-07-05) → ville
være en no-op. Den rigtige lever ved skala er **batching** (flere NOTAMs pr. kald → system-prompten
amortiseres, ~3× på input) — men præmatur ved ~$0,34/fyld; gemt til hvis token-forbrug nogensinde bliver reelt.

**Faser:**

| Fase | Brugere | Løsning |
|------|---------|---------|
| **Nu** | få | fetch-på-kald + content-cache + parallelisme (16/16) + Render $7 (altid-varm) |
| **Vækst** | snesevis–hundreder | scheduled poll → **Render managed Postgres**; servér fra DB; eager-på-gemte-ruter |
| **Skala** | tusinder / kommercielt | **FAA SWIM** streaming (realtid push) + flere server-instanser |

**Migrering = påbygning, ikke omskrivning:** ingestion-jobbet genbruger *præcis* `enrich`/`classify`/
`summarise` og skriver til DB i stedet for at returnere; serve-delen genbruger `timing.is_active_during`
+ D)-skema oven på gemte data. Vejr (METAR/TAF) holdes separat med kort TTL (ændrer sig tit, let at hente).

**DB-skitse (Postgres):** `notams(id, icao, raw, q_* felter, category, valid_from, valid_to, d_field,
ai_summary, hash, status[active/replaced/cancelled], fetched_at)` + `weather(icao, metar, taf, fetched_at)`.
NOTAM-livscyklus: NOTAMR erstatter, NOTAMC annullerer → markér status ved hver ingest-cyklus.

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
- **Udbyder-agnostisk token-tæller** (`notam/usage.py`, tråd-sikker): hver udbyder rapporterer
  forbrug i samme form (Claude `usage`, qwen `prompt_eval_count`/`eval_count`). Tæller kun ægte
  model-kald (cache-hit/trigger/none = 0). `/usage`-endpoint viser tallene. Følger med til qwen —
  men der er tokens gratis (kun load-mål). Resettes ved server-genstart (in-memory).
- **Sortering efter vigtighed + NOTAM-alder (pilot):** relevante NOTAMs sorteres nu ILS →
  Approach → Runway → Navaids → Movement → rest (`relevance.priority`; stabil). M-gruppen splittet:
  MR/MS/MT/MU→"Runway", MX→"Taxiway", resten→"Movement". **Alder** (fx "3mo", "4d") vises efter
  identifieren (`briefing._age` fra FAA `issueDate`), som i CrewBriefing.
- **Sammenfoldelige lufthavne (pilot):** hver AD er nu en dropdown i web-UI'et — kollapset viser
  kun overskrift + antal (kort dokument), udfoldet viser NOTAMerne for netop den AD. Skalerer til
  mange lufthavne uden at blive uoverskuelig.
- **Flyve-vejr integreret (pilot):** `notam/weather.py` henter METAR/TAF fra aviationweather.gov
  (gratis, ingen nøgle, global — samme filosofi som FAA). **Ingen AI** — METAR/TAF vises råt
  (piloter læser dem flydende); kun en deterministisk **farvekategori** beregnes fra sigt+skybase:
  CAVOK (grøn) / GOOD (blå) / MARGINAL (amber) / LOW VIS (rød) — pilotens tærskler, værste af
  sigt/base afgør. 10 tests (`test_weather.py`). Hentes parallelt pr. AD i `briefing.py`; vises som
  farvet badge på lufthavns-overskriften + Weather-dropdown med rå METAR/TAF.
- **Vejr-farve fra TAF (prognose i flyve-vinduet):** `weather.taf_category()` fortolker TAF'en
  (validitet, FM/BECMG med carry-forward af sigt/skybase, TEMPO/PROB) og tager **værste kategori**
  i [ETD, ankomst]. METAR er fallback. Badge = prognose; dropdown viser "Now X · At ETD Y". 7 nye
  TAF-tests. Projektets mest komplekse parser — men isoleret i `weather.py` og testet.
- **I dag / I morgen-vælger + vindue-note (pilot):** input har nu en Today/Tomorrow-toggle
  (server `day`-param → dato = i dag/+1). Note over resultatet: "NOTAMs and weather … for your
  flight window — <day>, ETD …Z → ETA …Z" (ETA beregnet i UI). Ingen fuld dato nødvendig; TAF
  dækker i dag/i morgen.
- **Today/Tomorrow-vælger + vindue-note** tilføjet (server `day`-param, UI viser ETD→ETA). Log opdateret til live-tilstand (status/filoversigt/beslutninger D14–D15/åbne punkter) før auto-compact.

### 2026-07-05 — Minima, ruter, baner
- **LOW VIS = Cat I-minima (pilot):** vejr-tærsklen for rød ændret fra 1 km/500 ft til **≤550 m RVR /
  ≤200 ft** (`weather._classify`). Rammer nu "på/under minima" i stedet for at farve et moderat loft
  rødt — fx `BKN004` (400 ft) med 10 km sigt er nu MARGINAL, ikke LOW VIS. Løser samtidig et navne-
  problem: "LOW VIS" betød tidligere også lavt loft. MARGINAL-båndet strækker sig nu ned til minima.
  Testene opdateret + kant-cases tilføjet (200 ft/500 m rammer rødt; 300–400 ft er MARGINAL) → 19 tests.
- **Gemte ruter — ét-tryk-chips (pilot):** vandret chip-række øverst i formularen (`web/index.html`,
  `ROUTES`-array). Ét tryk udfylder DEP/ARR/ENR; pilot sætter dag + ETD og trykker Get briefing
  (tidsvinduet kan ikke gættes → ikke auto-hent). Delt statisk crew-liste, **ingen login** (D16).
  Enroute-koder der allerede flyves som dep/arr fjernes → ingen dobbelt-hentning. 10 CGN-ruter lagt ind;
  alle 43 IATA-koder verificeret → ICAO; to slåfejl rettet: `NTS→NTE` (Nantes), `DVB→DBV` (Dubrovnik).
- **Baner over vejret + vind-favoriseret ende (pilot):** `notam/runways.json` (OurAirports, public
  domain, 33.709 AD, keyet på ICAO — samme kilde som IATA→ICAO), bygget reproducerbart via
  `tools/build_runways.py`; ingen runtime-download. `notam/runways.py` slår baner op og markerer den
  ende der er mest op i vinden (D17). `weather._wind` parser METAR-vind (dir/speed/gust, MPS→kt,
  360=nord, VRB/calm → ingen retning). UI viser en linje over vejret: `RWY 06/24 · 13L/31R · 13R/31L
  wind 280/12` med den vind-favoriserede ende fremhævet + caveat (støj/ILS/ATC afgør). 17 nye tests
  (`test_runways.py`). Headings og METAR-vind er begge retvisende → ingen magnetisk misvisning.
- **UI-oprydning + navn (samme dag):** vindue-noten gjort permanent *over* ETD/EET og live-opdateret
  (dag/ETD/EET); vejr-font større + mørkere (METAR/TAF 12→14px, grå→ink); NOTAM-alder større + " old"
  (fx "2w old", men ikke "today"/"new"); ENR slået sammen med ALT → ét **"ALT / ENROUTE"**-felt,
  placeholder "ICAO or IATA" i alle felter; ETD/EET ens højde (native time-chrome fjernet, iOS+desktop);
  ny rute **CGN–BER**, ruter sorteret efter slutdestination, SKG → første ALT på ATH. Navn:
  **NOTAM & WX AI — Route Briefing** ("/" valgt fra: læses som sti-separator i IT/URL; se [[app-branding]]).
- **Rute-editor + `localStorage` (on-device, ingen login — D16/D11):** de bagede Starair-ruter er nu
  `DEFAULT_ROUTES` (frø); hver enheds tilføjelser/sletninger gemmes i `localStorage` (`notamwx.routes.v1`)
  og **overlever browser-lukning**. Edit-knap: slet rute (×), **Save current as route** (overskriver ved
  samme navn, ellers ny; holdt sorteret efter slutdestination), **Reset to Starair**. Robust load
  (fallback til frø ved manglende/korrupt data) + try/catch om skrivning (privat-tilstand kan ikke crashe).
  Realiserer D11's on-device-model for web; iCloud-sync kommer gratis i iOS-appen. Logik verificeret
  (load→gem→genindlæs efter "genstart", slet, reset, dedup).
- **Editor-finpudsning + statisk note:** "Save current as route" lukker nu redigeringen automatisk
  (Done underforstået; sletning med × holder åben, så flere kan fjernes i træk). Rute-labelen udvidet til
  "· tap to fill · press Edit to modify routes". Vindue-noten over ETD/EET er nu en **statisk, fed, mørk**
  opfordring — **"Set times to get correctly tailored WX and NOTAM"** — i stedet for den live ETD→ETA-
  readout; den tilhørende `updateWinnote`/`eta`-JS er fjernet (nettoresultat −26 linjer, koden blev simplere).
- **Parallelisme-bump + Fase 2-plan:** fetch/AI-pools hævet 6/8 → **16/16** i `briefing.py` (I/O-bundet,
  billige tråde → hele ruten hentes i én bølge; barberer den varme tid). Skrevet **Fase 2-planen** ind
  (D18 + §6): ingest → DB, eager-oversæt kun gemte-rute-pladser, lazy resten; token ∝ ændringsrate;
  faser nu/vækst/skala. Baggrund: kold-start-test viste CGN–ATH 1:20 (kold) vs ~25s (varm) — Render $7
  fjerner de ~50s kold-start; parallelisme + cache tager den varme tid videre ned.
- **Live-måling af varm hastighed + eager-omkostning (token-verificeret):** varm CGN–ATH cache-kold
  **31s** (AI-bundet: ~6s hentning + ~25s AI på ~130 nye NOTAMs), cache-varm **5,7s**, CGN–AOI 9,2s.
  Token-frit talt: 420 NOTAMs / **358 AI-berettigede** på de 46 pladser → **eager-fyld ~$0,34** (~$1-2/md
  for hele netværket). **Prompt caching undersøgt → droppet:** Haiku 4.5 kræver 4.096 tokens for caching,
  vores prompt er ~600 → no-op (verificeret mod Anthropics docs). Ikke implementeret; batching er den
  rigtige lever ved skala (senere). Ærlighed frem for en falsk besparelse.
- **Vejr: CAVOK kun når bogstaveligt (pilot):** grøn top viste "CAVOK" hver gang sigt ≥10km & loft
  ≥5000ft — piloter blev skuffede når det ikke var *rigtig* CAVOK ("ser for godt ud i oversigten"). Nu:
  🟢 **CAVOK KUN** når TAF/METAR bogstaveligt skriver CAVOK; 🟢 **GOOD** for godt-uden-CAVOK
  (≥10km/≥5000ft); 🔵 **OK** for det gamle GOOD-bånd (≥5km/≥1500ft); MARGINAL/LOW VIS uændret. Begge
  grønne labels → wx-green; `_SEVERITY` udvidet til 5 (så TAF-værste-i-vindue stadig virker). 19 tests grønne.
- **Keep-alive (kold-start fjernet, gratis):** GitHub Actions-workflow (`.github/workflows/keepalive.yml`)
  pinger `/health` hvert ~10. min → serveren dvaler ikke → ingen ~30-50s kold-start. Gratis+ubegrænset
  (public repo); ekstern GET både nulstiller idle-timeren og vækker en sovende service. Krævede `workflow`-
  scope på GitHub-token (blokerede push to gange før det blev sat). Forbehold: cron-jitter kan sjældent
  glide forbi 15-min-grænsen → enkelt kold-start (UptimeRobot 5-min mere præcist hvis nødvendigt).
  Baggrund: målt at $7 Render fjerner kold-starten; keep-alive tester samme gevinst gratis først.
- **"Windy"-flag (pilot — natflyvning):** amber **Windy**-chip mellem "Weather" og kategorien når vinden
  (rolig ELLER stød) **> 20 kt** — i METAR (nu) eller TAF i flyve-vinduet. TAF-vind læses **vindue-bevidst**
  og bæres frem gennem BECMG/FM/TEMPO. Refaktorering: TAF-periode-udtrækket faktoriseret ud i
  `_taf_conditions` (delt af `taf_category` + ny `taf_windy` + `_wind_kt`) — kategori-adfærd uændret,
  alle 7 gamle TAF-tests grønne + 8 nye = 27 i alt. (Også vejr-polish: "Weather"-fanen 16px+bold; OK-badge
  dybere marineblå for synlighed; OK blev kortvarigt grøn men rullet tilbage — de fire farver var bedre.)
- **Ruter + default ETD:** ny **CGN–BOD** (Bordeaux; enroute TLS MRS CDG HHN BRU LGG LUX BGY) i
  `DEFAULT_ROUTES` → **12 ruter**, alfabetisk efter slutdestination. **Default ETD → 23:30** (natflyvning).
  Bemærk localStorage-fælden: enheder der allerede har gemte ruter ser ikke nye frø-ruter før "Reset to
  Starair" eller manuel tilføjelse — iboende afvejning mellem kode-standarder og brugerens egen kopi (D16).

## 2026-07-08 — Skala, offline & officiel datakilde (session-log til genoptagelse)

- **Deploy + fejlrettelser:** appen kom live på Render (`notam-ai.onrender.com`), env-vars sat
  (ANTHROPIC_API_KEY, NOTAM_LLM=claude, FEEDBACK_SMTP_*). Bug: feedback-modalen sad fast åben — CSS
  `.fbmodal{display:flex}` overtrumfede `[hidden]`; fikset med global `[hidden]{display:none!important}`.
- **Kodegennemgang (streng) + rettelser:** (1) FAA-fejl isoleres nu per plads i `briefing._process_airport`
  (fanget → tom gruppe m. `error="notam_fetch_failed"`, UI viser ⚠️-banner i stedet for misvisende tom
  liste); (2) `cache.put` skriver ikke længere hele filen ved hvert kald — write-coalescing + `flush()` ved
  briefing-slut (~1 skrivning i stedet for N); (4) **rate-limit** på `/briefing`: 20/time/IP
  (`notam/ratelimit.py`, sliding window) → 429 med tydelig banner; (5) `main._qline_summary` crasher ikke
  længere på NULL flight-levels. Alle testfiler grønne.
- **Dokumentation:** `ARCHITECTURE.md` (dataflow + hvem-kalder-hvem), `TEKNISK_RAPPORT.md` (funktion-for-
  funktion, dansk; også genereret som PDF på skrivebordet via xhtml2pdf), og korte `Wiring —`-noter øverst
  i hver `notam/`-fil. QR-plakat (A4 PDF, engelsk) til crewrummet.
- **PWA / offline (stor gevinst, testet virker):** `web/sw.js` (service worker cacher app-skallen offline),
  `web/manifest.json` + genererede ikoner + apple-touch-meta (installerbar "Føj til hjemmeskærm"). **Hver
  "Get briefing" gemmes automatisk i IndexedDB**, keyet på rute; en "Saved briefings"-liste (offline) lader
  piloten gen-åbne **alle** downloadede ruter, hver med UTC-tidsstempel. Ingen "NOT LIVE"-banner (underforstået
  for piloter). server.py serverer /sw.js, /manifest.json, /icon-{192,512}.png fra roden.
- **Token-telemetri der overlever redeploys:** keep-alive-workflow'et fik et isoleret `usage`-job der hvert
  ~10. min henter `/usage` og akkumulerer lifetime-total i en **secret Gist** (`notam-ai-usage.json`) — med
  redeploy-reset-detektion (`_normalise`/single-flight-agtigt). Løser at `/usage` er in-memory og nulstilles
  ved redeploy (Renders disk er ephemeral). Gist-ID + `gist`-scope-PAT som GitHub-secrets. Virker live.
- **Officielt FAA NMS-API som udskiftelig kilde (verificeret):** `faa.py` dispatcher nu på `NOTAM_SOURCE`
  (default "web" = uændret; "nms" = officielt API). Testet mod **live staging** med rigtige credentials
  (den krypterede onboarding-Excel, password = strengen fra CGI's "Follow-up"-mail): **europæisk dækning
  bekræftet** (EDDK gav 24 NOTAMs) og **fuld rå ICAO-tekst** i `notamTranslation[ICAO].formattedText` →
  mapper 1:1 til pipelinens dict-form. OAuth2 client_credentials → cachet bearer (~30 min), GEOJSON,
  ISO→"MM/DD/YYYY HHMM"-konvertering, throttle (`FAA_NMS_MIN_INTERVAL`, staging spike-arrest 1/sek).
  Nøgler kun som env-vars. Det gemte EDDK-svar kørt rent gennem hele pipelinen (24/24 Q-linjer + body).
- **Server-side NOTAM-cache = skalerings-håndtaget:** `notam/fetchcache.py` — delt kort-TTL
  (`NOTAM_CACHE_TTL`, default 300s) + **single-flight** foran `fetch_notams`. Mange piloter der briefer samme
  plads → **ét** FAA-kald (verificeret: 3× EDDK = 1 kald; 30 samtidige tråde coalescer til 1). Virker for
  begge kilder. Ny `test_fetchcache.py`. Gør rate-limit håndterbar ved 5000 piloter.
- **Strategi/beslutninger (parkeret til produktion):**
  - **Mirror-modellen** (pilotens egen idé): seed klyngen af brugte pladser én gang, hold frisk med
    `?lastUpdatedDate=` deltaer + `/notams/checklist` reconciliation ind imellem. Gør FAA-kaldsvolumen
    uafhængig af antal piloter → **rate-limit bliver ligegyldig**. (SWIM/FNS JMS-push er det tunge alternativ;
    mirror er den pragmatiske mellemvej: kræver DB + planlagt poller, ikke messaging-infra.)
  - **FAA-sporet PARKERET til produktion.** Rate-limit-mailen droppet (mirror løser det). FAA-kontakt kun
    nødvendig for (a) **prod-adgang** (staging = testdata; org-navn-spørgsmålet uafklaret) og (b) **tilladelse
    til at spejle/redistribuere** — ikke throughput.
  - **Kilde-resiliens:** den udskiftelige `fetch_notams` gør et kildeskift indeholdt. For et europæisk produkt
    er **EUROCONTROL EAD** den naturlige autoritative kilde (europæisk-drevet), men kommerciel kontrakt +
    royalties (modsat FAA's US public domain/gratis). **Forespørgsels-mail sendt til `ead.service@eurocontrol.int`**
    (venter svar). Lettere alternativer: NavBlue (Airbus), Lido (Lufthansa Systems), Notamify.
- **Status ved session-slut:** live/default kører web-kilden + AI-cache + NOTAM-cache + rate-limit + PWA
  offline + feedback + token-telemetri. NMS-API bygget men slået fra (flag). Intet produktions-tungt tændt →
  prototypen kører let og billigt. **Næste mulige skridt (intet blokeret):** brug + pilot-feedback → iteration;
  app-features; eller produktions-planlægning (hosting, DB+mirror, kilde+licens) når EAD/FAA svarer.
  Ventende eksterne: **FAA prod-adgang** og **EUROCONTROL EAD-tilbud**.

## 2026-07-22 — Server 500 på ruter med Newark: tekstløse NOTAMs (fundet via en tester)

**Symptom:** en tester (pilotens far) fik "Something went wrong (server 500)" på flere forskellige
ruter. Første mistanke var EET-feltet (skærmbilledet viste ETD som `23.30` med punktum, EET som
`01:30` med kolon) — **forkert spor**. Isolering mod live server viste mønsteret: EKVG, BGO, CPH,
EKCH, EGLL → 200; **EWR alene → 500**. Det var altid DEP der væltede den, ikke tiden.

**Årsagskæde (rodfæstet, ikke gættet):**
FAA-web-feeden returnerer for KEWR **7 poster helt uden tekst** (`raw == ""`, id `LTA-EWR-nn` —
kun datoer, intet indhold). Tom tekst → Claude-kaldet får tomt content → API-fejl. Den fejl var
allerede fanget i `_summarise_parallel`, som falder tilbage til `n["body"]` — men den er også tom,
altså falsy. Og `_view` havde `n.get("_summary") or summarise(n)`: den `or`-fallback kaldte AI'en
**igen, uden for try/except** → exception → 500 for hele briefingen. Derfor virkede det lokalt
(AI slået fra, `_none` returnerer tom streng uden at kaste) og fejlede kun i produktion.

**Rettelser (fire lag, så én dårlig NOTAM aldrig kan vælte en briefing igen):**
- `faa.py::_fetch_source` — filtrerer tekstløse poster væk **ved kilden**, virker for begge kilder
  og for CLI'en. KEWR: 30 → 23 NOTAMs, 0 tekstløse.
- `llm.py::summarise` — guard: blank `raw` returnerer tidligt, sender aldrig tomt content til API'et.
- `briefing.py::_view` — `or summarise(n)` fjernet; bruger den rensede body som fallback.
- `server.py::make_briefing` — try/except omkring `briefing.build`: JSON-fejlsvar + traceback i
  Render-loggen i stedet for Flasks bare HTML-500-side.
- **Verificeret:** med *alle* AI-kald tvunget til at kaste → 200, 23 NOTAMs, 0 tomme summaries.

**Tidsinput lavet fejlsikkert (pilotens ønske):** ETD og EET er nu `<select>`-rullemenuer i
halvtimes-spring (ETD 00:00–23:30 = 48 valg, EET 00:30–12:00 = 24 valg) i stedet for tastet tekst.
Baggrund: et telefon-numerisk tastatur har **ingen `:`**, og iOS viser tid som `08.00` i dansk
locale — testeren kunne ikke skrive 08:00. `server.py::_hhmm` er samtidig gjort tolerant: den
ignorerer separatorer (`08:00`/`0800`/`08.00`/`08 00` → 08:00) og **clamper** i stedet for at kaste
— tidligere gav `2530` en `ValueError: hour must be in 0..23` → endnu en 500-kilde. `08.00` blev
før stille fortolket som `00:00` (forkert briefing-vindue, ingen fejl vist) — også væk.

**Læring:** en `or`-fallback der kalder en fejlbar funktion uden for det try/except der beskytter
det oprindelige kald, ophæver beskyttelsen. Og: eksterne feeds leverer tomme poster — filtrér ved
kilden, ikke nedstrøms.
