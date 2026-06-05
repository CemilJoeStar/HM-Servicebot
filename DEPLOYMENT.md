# Deployment: Vercel + Render

## Zielarchitektur

- Frontend: Vercel, Vite/React
- Backend: Render Web Service, FastAPI
- Daten: Supabase Postgres + pgvector
- LLM/Embeddings: Google Gemini API

## 1. Backend auf Render deployen

Render Web Service anlegen:

- Root Directory: `outputs/rag_prototype`
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn backend_api:app --host 0.0.0.0 --port $PORT`

Environment Variables in Render:

```env
GOOGLE_API_KEY=...
SUPABASE_URL=https://njsxistiwsrqmoxzfwet.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...
ALLOWED_ORIGINS=https://DEIN-VERCEL-PROJEKT.vercel.app
```

Nach dem Deploy bekommst du eine Backend-URL, etwa:

```text
https://hm-servicebot-api.onrender.com
```

Healthcheck:

```text
https://hm-servicebot-api.onrender.com/api/health
```

## 2. Frontend auf Vercel deployen

Vercel Projekt anlegen:

- Framework: Vite
- Root Directory: leer lassen, wenn dieses Verzeichnis der GitHub-Repo-Root ist
- Build Command: `cd frontend && npm run build`
- Output Directory: `frontend/dist`

Alternativ kannst du `frontend` als Root Directory setzen. Dann gelten:

- Build Command: `npm run build`
- Output Directory: `dist`

Environment Variable in Vercel:

```env
VITE_API_BASE_URL=https://DEIN-RENDER-BACKEND.onrender.com
```

Wichtig: Bei Vite muss die Variable mit `VITE_` beginnen, damit sie im Browser verfügbar ist.

## 3. CORS final setzen

Sobald deine Vercel-URL feststeht, in Render setzen:

```env
ALLOWED_ORIGINS=https://DEIN-VERCEL-PROJEKT.vercel.app
```

Für lokale Entwicklung kannst du temporär mehrere Origins erlauben:

```env
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,https://DEIN-VERCEL-PROJEKT.vercel.app
```

## 4. Lokal weiterentwickeln

Backend:

```bash
cd outputs/rag_prototype
python3 -m uvicorn backend_api:app --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd outputs/rag_prototype/frontend
npm run dev
```

## Hinweise

- Die `.env` Datei nicht committen.
- Der Supabase Service Role Key gehoert nur ins Backend, niemals ins Frontend.
- Render Free Services koennen nach Inaktivitaet schlafen. Der erste Request kann dann etwas dauern.
- Chatverlaeufe werden im Prototyp optional gespeichert. Sichtbare Historie ist
  auf eine begrenzte Anzahl begrenzt; alte Chats werden nach 30 Tagen
  anonymisiert. Beim Loeschen bleibt nur ein anonymisierter Audit-Datensatz ohne
  Nachrichteninhalt erhalten.
