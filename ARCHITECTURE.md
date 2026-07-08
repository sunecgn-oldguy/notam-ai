# Arkitektur — hvordan koden hænger sammen

Denne fil er landkortet. Læs den før du dykker ned i en enkelt fil, så du ved
hvor den passer ind. Hver `notam/`-fil har desuden en `Used by:` / `Calls:`-note
øverst, der peger på nabofilerne.

Kernereglen i hele projektet: **alt det deterministiske (kode-logik) sker først;
AI'en bruges KUN til at omskrive én NOTAM til læsbar tekst.** Relevans, tid, og
militær-frasortering afgøres af almindelig kode — aldrig af AI'en. Det er
sikkerheds­arkitekturen: kode kan ikke hallucinere.

## De to indgange (entry points)

Der er to måder at køre motoren på. De deler alle de små byggeklodser i
`notam/`, men wirer dem sammen hvert sit sted:

| Fil | Bruges af | Vej gennem koden |
|-----|-----------|------------------|
| `server.py` | **appen** (telefon/browser) | Flask HTTP → `briefing.build()` → JSON |
| `main.py` | **udvikler-CLI** (test i terminal) | argparse → `_report_airport()` → tekstfil |

> ⚠️ Vigtigt for nye læsere: `main.py` er den GAMLE test-CLI. Den kører kun
> fetch→enrich→classify→tid — **uden** AI, vejr, baner og cache. Den rigtige
> produktionsvej som appen bruger er `briefing.py`. De to filer wirer altså
> pipelinen hver for sig; når du ændrer logik, så tjek om begge skal opdateres.
> (`main.py` og `profile.py` bruges ikke af den deployede app.)

## Dataflow for ét briefing-kald (appen)

```
Browser (web/index.html)
   │  POST /briefing  { dep, arr, alt, etd, eet, day }
   ▼
server.py  ── _airports() + _window() gør input til (icao, rolle)-liste + tidsvindue
   │            airports.to_icao()   IATA→ICAO
   ▼
briefing.build(airports, window)                         ← selve orkestreringen
   │
   ├─ 1. FOR HVER PLADS (parallelt, 16 tråde): _process_airport()
   │        faa.fetch_notams(icao)      → rå NOTAMs fra FAA
   │        enrich.enrich(n)            → tilføjer .body, .qline, .d
   │           ├─ clean.clean()            HTML-afkodning + forkortelser (abbreviations.py)
   │           └─ qline.parse_qline()      Q-linjen → koordinat/FL/emne
   │        relevance.classify(n)       → tier high/low + kategori (militær = low)
   │        timing.is_active_during(n)  → er den aktiv i tidsvinduet?
   │           └─ schedule.active_during()  fortolker D)-feltet (daglige tidsbånd)
   │        weather.fetch(icao, window) → METAR/TAF + farvekategori + vind
   │
   ├─ 2. FOR HVER RELEVANT NOTAM (parallelt, 16 tråde): llm.summarise()
   │        triggers.is_document_ref()  → AIP-SUP? så AI-fri, ærlig tekst (ingen hallucination)
   │        cache.get()                 → set før? gratis genbrug (nøgle = hash af rå tekst)
   │        provider (none/claude/qwen) → omskriv til kort linje
   │        usage.record()              → tæl tokens
   │        cache.put()                 → gem til næste gang
   │
   └─ 3. _airport_view() samler alt til JSON
            runways.view(icao, wind)    → baner + vind-favoriseret ende
   ▼
JSON tilbage til browseren → render() tegner det
```

## Hvorfor cachen er den vigtigste optimering

En NOTAM er ens for alle piloter i verden. `cache.py` nøgler på et hash af den
**rå tekst**, så samme NOTAM kun omskrives af AI'en én gang — derefter er den
gratis for alle. Ændrer FAA teksten, ændrer hashet sig, og den bliver
automatisk lavet om (vi kan aldrig vise en forældet oversættelse). Se `llm.py`
og `cache.py`.

## De sidefunktioner der ikke er i hovedflowet

| Fil | Rolle |
|-----|-------|
| `fetchcache.py` | delt kort-TTL + single-flight cache foran `faa.py` — mange piloter → ét FAA-kald pr. plads (skalering) |
| `feedback.py` | `/feedback` → gem i fil + send email (pilot-feedback) |
| `usage.py` | token-tæller, vises på `/usage` |
| `profile.py` | pilotens plads-database + presets — **kun** CLI'en (appen bruger localStorage) |
| `tools/build_runways.py` | engangs-script: byg `runways.json` fra OurAirports |

## Fejl-filosofi (bevidst design)

Næsten alt fejler **sikkert = vis mere, skjul aldrig ved tvivl**:
- Kan tid/skema ikke fortolkes → NOTAM'en vises (over-show er den sikre retning).
- Fejler en AI-oversættelse → vi falder tilbage til den rene tekst.
- Fejler vejr-hentning → tom streng, resten af briefingen kører videre.

Også FAA-hentningen fejler nu sikkert i produktionsvejen: `briefing.py`
fanger en fejl per plads og markerer den med et `error`-flag (UI'en advarer i
stedet for at vise en misvisende tom liste), så én plads' fejl aldrig vælter
hele ruten. Den gamle CLI (`main.py`) fanger det stadig ikke — acceptabelt for
et dev-værktøj.
