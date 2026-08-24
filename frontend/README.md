# Frontend — Patient, Doctor & Admin Portals

React 18 + TypeScript + Vite. Three role-specific portals over the existing
backend API. No mock data anywhere — every screen calls real endpoints.

## Setup

```bash
npm install
cp .env.example .env   # optional; defaults work for local dev
npm run dev            # http://localhost:5173
```

The backend must be running on `http://localhost:8000`:

```bash
cd ../backend && python -m uvicorn app.main:app --reload
```

`vite.config.ts` proxies `/api` to the backend in dev (so no CORS issues).
For production set `VITE_API_BASE_URL` to the deployed backend origin.

| Script | Purpose |
|---|---|
| `npm run dev` | Dev server with HMR |
| `npm run build` | Typecheck + production build to `dist/` |
| `npm run preview` | Serve the production build |
| `npm run typecheck` | Types only |

> On Windows, if the repository path contains `&`, `npx` may fail to resolve
> paths. Run binaries directly instead, e.g.
> `node ./node_modules/vite/bin/vite.js build`.

## Structure

```
src/
  api/       client.ts (fetch wrapper, auth, error normalisation), types.ts
  auth/      AuthContext (session), ProtectedRoute (role guard)
  components/ Layout (role-based nav), ui.tsx (shared primitives)
  lib/       format.ts (UTC-safe dates), useAsync.ts (loading/error state)
  pages/     Login, Register, patient/, doctor/, admin/
```

## Portals

**Patient** — register, log in, search doctors by specialisation, view a
doctor's weekly availability and per-date slots, hold a slot (with live
expiry countdown), describe symptoms, confirm, review the AI pre-visit
summary, list/inspect appointments, reschedule, cancel, read the post-visit
summary.

**Doctor** — log in, dashboard with today/upcoming counts, appointment list
with status filters, per-appointment view showing the patient's pre-visit AI
summary, consultation notes + prescription entry (multiple medications), and
post-visit AI summary generation.

**Admin** — log in, dashboard aggregates, create/manage doctors, edit
specialisation and slot duration, activate/deactivate, configure weekly
working hours, add/remove leave dates, review conflicted appointments.

## Conventions

- **The backend is the source of truth.** `ProtectedRoute` only shapes
  navigation; authorisation, slot availability, appointment state, AI state
  and notification state are all decided server-side. Availability shown in
  the UI is never treated as final — the booking call can still be rejected,
  and that rejection is surfaced.
- **Errors are real.** `ApiError` carries the backend's own `detail` and
  `error_code`; `ErrorBanner` renders that text rather than a generic message.
  FastAPI 422 validation arrays are flattened into readable field messages.
- **Times are UTC.** The backend generates and stores slots in UTC, so the UI
  renders and labels UTC to stay consistent. `parseServerDate()` treats a
  timestamp with no timezone designator as UTC — values read back from the
  database serialise without one, and parsing those as local time silently
  shifts every appointment by the viewer's offset.
- **Loading and confirmation states** are explicit: spinners while fetching,
  disabled buttons with progress labels while submitting, and a confirmation
  dialog before destructive actions (cancel appointment, remove leave).

## Booking-flow ordering

The UI collects symptoms *before* the patient presses Confirm, matching the
intended experience. The API calls run in the order the backend requires:
create appointment (from the hold) → submit symptom report → generate the AI
summary, since the symptom report and AI summary are both keyed to an
appointment id. If the AI step fails, the booking is still shown as confirmed —
it already is, server-side — with a note that the summary can be generated
later.
