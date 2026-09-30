# Deployment

## Status: not deployed

No hosting-provider account, API token, or credential exists in this environment, and
creating one (Render/Railway/Vercel account, payment method if required, DNS) is a
decision for a human, not something an autonomous session should do unattended. This
document is the concrete, step-by-step path to a hosted URL — nothing below requires a
code change, since both halves were already built to be deployed as-is.

## Order of operations

Database → Backend → Frontend → (optionally) real LLM/Email/Google credentials. Each
step below only needs the output of the one before it — nothing is circular except that
the backend's `CORS_ALLOWED_ORIGINS` needs the frontend's URL, which doesn't exist until
after the backend is already deployed once; that's why the backend is deployed *before*
the frontend, then redeployed once with the real CORS value.

## 1. Database (any managed PostgreSQL)

Render, Railway, Supabase, Neon, or AWS RDS all work — nothing in this codebase is
provider-specific, it's plain SQLAlchemy/Alembic against a `postgresql://` URL.

1. Create a PostgreSQL instance (Render/Railway: one click "New PostgreSQL"; note the
   region — put it in the same region as the backend to avoid cross-region latency).
2. Copy the connection string. It usually looks like
   `postgresql://user:password@host:5432/dbname`. Some providers hand you a
   `postgres://` URL — SQLAlchemy accepts either.
3. That's it — no manual schema creation. The backend's start command (`alembic upgrade
   head`, below) creates every table, index, and constraint from the 4 migrations in
   `backend/alembic/versions/` the first time it boots against this URL.

## 2. Backend (Render, Railway, or any host that runs a Python web process)

1. Create a web service from this repo, root directory `backend/`.
   - Build command: `pip install -r requirements.txt`
   - Start command: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
     (most platforms inject `$PORT`; hardcode e.g. `--port 10000` if the platform doesn't)
2. Set environment variables (see `backend/.env.example` for the full list; **do not**
   copy `backend/.env` — it's a local dev file, excluded from git):
   - `DATABASE_URL` → the managed Postgres connection string from step 1
   - `SECRET_KEY` → a freshly generated random value (**not** the dev default)
   - `DEMO_MODE=True` to launch without any AI/email/calendar credentials (recommended
     for an evaluator-facing deployment — see `README.md#demo_mode`), or `False` plus
     `AI_PROVIDER_*`/`SMTP_*`/`GOOGLE_*` for real integrations (steps 4-6 below)
   - `CORS_ALLOWED_ORIGINS` → placeholder for now (e.g. `http://localhost:5173`) — you'll
     update this to the frontend's real URL and redeploy once section 3 gives you one
   - `ALLOW_PRIVILEGED_SELF_REGISTRATION` → leave `False`/unset; flip to `True` only for
     the single request needed to bootstrap the first admin (see README), then unset
     and redeploy
3. Deploy. Confirm `GET /health` returns `{"status": "ok", ...}`.
4. Bootstrap the first admin account (README "Creating the first admin account"), then
   redeploy with `ALLOW_PRIVILEGED_SELF_REGISTRATION` unset/`False`.

## 3. Frontend (Vercel, Netlify, or any static host)

1. Create a project from this repo, root directory `frontend/`.
   - Build command: `npm run build`
   - Output directory: `dist`
2. Set `VITE_API_BASE_URL` to the backend's deployed origin from the previous section
   (e.g. `https://your-backend.onrender.com`) — must include the scheme, no trailing slash.
3. Deploy. Open the resulting URL, confirm `/login` renders and a login attempt reaches
   the backend (check the Network tab for a request to `VITE_API_BASE_URL`).
4. Go back to the backend service and update `CORS_ALLOWED_ORIGINS` to this frontend's
   real URL (e.g. `https://your-app.vercel.app`), then redeploy the backend. Until this
   step, login/register calls from the deployed frontend will fail as CORS errors in
   the browser console even though the backend itself is healthy.

## 4. LLM API (AI provider) — optional, DEMO_MODE works without it

Leave `DEMO_MODE=True` and skip this entirely — `MockAIProvider` generates schema-valid
pre/post-visit summaries with zero external calls, which is enough to demonstrate every
AI-related workflow. To wire up a real LLM:

1. Get an API key from any OpenAI-compatible provider — OpenAI itself, or any
   OpenAI-API-compatible endpoint (Azure OpenAI, Groq, Together, OpenRouter, a local
   vLLM/Ollama server with an OpenAI-compatible shim, Google Gemini, etc.). `RealAIProvider`
   (`backend/providers/ai_provider.py`) speaks the standard `/chat/completions` shape —
   no vendor SDK, so any of these work without a code change.
2. Set on the backend service:
   - `AI_DEMO_MODE=False` — switches only the AI to the real provider; email and
     calendar keep following `DEMO_MODE`
   - `AI_PROVIDER_API_KEY` → the key
   - `AI_PROVIDER_BASE_URL` → the provider's API base (default `https://api.openai.com/v1`)
   - `AI_PROVIDER_MODEL` → a model name that provider serves (default `gpt-4o-mini`)

   For **Google Gemini**: `AI_PROVIDER_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai`
   and `AI_PROVIDER_MODEL=gemini-2.5-flash`, with a Gemini API key from Google AI Studio.
3. Redeploy. `GET /health` should report `"ai_provider": "real"`. Generate a pre-visit
   summary through the app and confirm it's no longer the Mock provider's keyword-based
   output.

> Each integration has its own switch — `AI_DEMO_MODE`, `EMAIL_DEMO_MODE`,
> `CALENDAR_DEMO_MODE`. Unset, each follows `DEMO_MODE`; `DEMO_MODE=False` alone turns
> on all three real providers at once. `GET /health` reports which one each is using.

## 5. Email (SMTP) — optional, DEMO_MODE works without it

`MockEmailProvider` records what *would* be sent with zero network calls when
`DEMO_MODE=True`. To send real email, any SMTP relay works — Gmail (with an App
Password), SendGrid, Mailgun, Amazon SES all expose one:

1. Get SMTP host/port/username/password from your provider.
2. Set on the backend service: `SMTP_HOST`, `SMTP_PORT` (587 for STARTTLS is standard),
   `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_FROM_ADDRESS` (must usually be a verified
   sender for the provider).
3. Redeploy, then confirm the `notification_worker` process (see below) is actually
   running — email is only *sent* by the worker claiming `PENDING` jobs, not inline.

## 6. Google Calendar & OAuth 2.0 — optional, DEMO_MODE works without it

Full walkthrough (Cloud project, OAuth consent screen, obtaining a refresh token) in
**[docs/google-calendar-setup.md](google-calendar-setup.md)**. Quick version:

1. Create OAuth 2.0 credentials in Google Cloud Console, enable the Calendar API.
2. Obtain a refresh token with the `calendar.events` scope (OAuth 2.0 Playground is the
   fastest path — see the linked doc).
3. Set on the backend service: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
   `GOOGLE_REFRESH_TOKEN`.
4. Redeploy. Book an appointment and confirm an event appears on the connected Google
   Calendar once the `calendar_worker` process runs.

## 7. Background workers

`workers/notification_worker.py` and `workers/calendar_worker.py` are standalone
processes (`python -m workers.notification_worker`, `python -m workers.calendar_worker`),
not started automatically by the web process — see `docs/architecture.md#background-job-architecture`.
Most platforms support a second "worker" process type in the same service/repo pointed
at these entrypoints with the same environment variables as the web process. Without
them running, notification/calendar jobs still get created and are visible in the
database, they just won't be *delivered* until a worker process claims them — booking,
rescheduling, and cancellation all still work correctly (see `docs/failure-handling.md`).

## 8. Verifying a hosted deployment

Once both halves are live:
1. `GET {backend}/health` → `{"status": "ok", "database": "connected", "demo_mode": true}`
2. Open `{frontend}` → register a patient → confirm the request reaches the backend
   (not a CORS error — if `CORS_ALLOWED_ORIGINS` wasn't set to the frontend's real
   origin, this is where it would surface)
3. Bootstrap an admin (see README), log in on all three portals, and run through the
   patient booking → doctor consultation → admin leave-conflict workflows described in
   `docs/requirement-mapping.md`
4. With `DEMO_MODE=True`, every workflow above works with zero external credentials —
   that's the point of DEMO_MODE for an evaluator who doesn't want to provision a real
   LLM/SMTP/Google account just to see the app function.
