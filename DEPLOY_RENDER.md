# Deploy til Render

Serveren er push-klar. Render bygger fra et GitHub-repo — så du behøver ikke din
egen maskine kørende. Her er de trin **du** tager.

## Én gang: læg koden på GitHub

```bash
cd "NOTAM AI"
git init
git add .
git commit -m "NOTAM AI engine + server"
```

Opret et tomt repo på github.com, og følg deres to linjer (`git remote add …` +
`git push -u origin main`).

> Tip: tilføj en `.gitignore` med `data/` og `__pycache__/`, så lokale cache- og
> databasefiler ikke ryger med op.

## På Render (render.com)

1. **New → Web Service**, og forbind dit GitHub-repo.
2. Render genkender Python. Sæt:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn server:app --bind 0.0.0.0:$PORT`
3. **Environment → Add Environment Variable:**
   - `ANTHROPIC_API_KEY` = din nøgle (fra console.anthropic.com)
   - `NOTAM_LLM` = `claude`  *(eller lad den være tom/`none` indtil du vil tænde AI'en)*
4. Vælg **Free** for at teste (går i dvale ved inaktivitet — første kald ~30 sek;
   keep-alive-workflow'et holder den vågen gratis). Renders billige faste plan er
   udgået — næste betalte trin er ~$25/md, så bliv på Free til prototypen.
5. **Create Web Service.** Render giver dig en fast adresse, fx
   `https://notam-ai.onrender.com`.

## Test at den lever

```bash
curl https://DIN-APP.onrender.com/health
# -> {"ok": true}

curl -X POST https://DIN-APP.onrender.com/briefing \
  -H "Content-Type: application/json" \
  -d '{"dep":"EDDK","arr":"LFML","alt":"LFMN","etd":"0800","eet":"0130"}'
```

## Nøglen er sikker

`ANTHROPIC_API_KEY` bor kun i Renders miljøvariabler — aldrig i koden og aldrig i
app'en. App'en (telefonen) taler kun med din Render-adresse, aldrig direkte med
Anthropic.

## Lokalt (valgfrit, kræver `pip install flask`)

```bash
python3 server.py            # kører på http://localhost:8000
```
