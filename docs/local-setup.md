# Running the app on your own computer

This guide takes you from nothing to the app running locally, signed in as a patient, a doctor
and an admin, with the tests passing. It takes about 15 minutes.

You don't need any accounts, API keys or a database server. By default the app uses a local
SQLite file, and `DEMO_MODE` replaces the AI, email and Google Calendar services with offline
stand-ins. Nothing you do locally touches the real deployment.

Commands are given for **Windows (PowerShell)** and **macOS / Linux**. Where they differ, both
are shown.

---

## 1. Install the tools

| Tool | Version | Check with |
|---|---|---|
| [Git](https://git-scm.com/downloads) | any recent | `git --version` |
| [Python](https://www.python.org/downloads/) | 3.12 or newer (CI and production use 3.12) | `python --version` (`python3 --version` on macOS/Linux) |
| [Node.js](https://nodejs.org/) | 22 LTS (22.22 or newer) or 24 LTS | `node --version` |

On Windows, tick **"Add python.exe to PATH"** in the Python installer.

## 2. Fork and clone

1. Open the repository on GitHub and click **Fork** (top right). This makes your own copy
   under your account.
2. Clone **your fork**, not the original:

   ```bash
   git clone https://github.com/<your-username>/Healthcare-Appointment-Follow-up-Manager.git
   cd Healthcare-Appointment-Follow-up-Manager
   ```

3. Add the original repository as `upstream`, so you can pull in new changes later:

   ```bash
   git remote add upstream https://github.com/SakthiQ/Healthcare-Appointment-Follow-up-Manager.git
   ```

> **Windows tip:** clone into a short path without spaces or `&`, such as `C:\dev\`. A path
> containing `&` breaks `npm run` (see [Troubleshooting](#troubleshooting)).

## 3. Start the backend

Open a terminal in the repository folder.

**Create and activate a virtual environment.** This keeps the project's Python packages
separate from the rest of your system.

Windows (PowerShell):

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
```

Your prompt now starts with `(.venv)`. Activate it again in every new terminal you open for
the backend.

**Install the packages, create your settings file and set up the database:**

```bash
pip install -r requirements.txt -c constraints.txt
```

Windows: `copy .env.example .env` · macOS / Linux: `cp .env.example .env`

```bash
alembic upgrade head
```

`.env` is your own settings file. Git ignores it, so it is never uploaded. The defaults need no
changes. `alembic upgrade head` creates the tables in a file called `healthcare_dev.db`.

**Create demo accounts:**

```bash
python -m scripts.seed_demo
```

This creates three accounts, all with the password `demo-password`:

| Role | Email |
|---|---|
| Admin | `admin@demo.example.com` |
| Doctor | `doctor@demo.example.com` (works Monday to Friday, 09:00–17:00 UTC) |
| Patient | `patient@demo.example.com` |

It is safe to run again. It refuses to run when `DEMO_MODE` is off or `ENVIRONMENT` is
`production`.

**Start the API:**

```bash
python -m uvicorn app.main:app --reload
```

Leave this terminal running. Check that it works by opening
<http://localhost:8000/health>, which should show `"status": "ok"`. The interactive API docs are at
<http://localhost:8000/api/v1/docs>.

## 4. Start the frontend

Open a **second** terminal in the repository folder:

```bash
cd frontend
npm ci
```

Windows: `copy .env.example .env` · macOS / Linux: `cp .env.example .env`

```bash
npm run dev
```

Open <http://localhost:5173>. The frontend forwards API calls to the backend on port 8000, so
both terminals must stay running.

## 5. Try it out

1. Sign in as the **patient**, find Dr Demo, pick a weekday slot and book it.
2. Sign out and sign in as the **doctor**. The booking appears in the appointment list; open it
   to record a consultation.
3. Sign in as the **admin** to see the dashboard, manage doctors, invite staff and read the audit
   log.

New patients can also sign up from the Register page. Doctors and admins can't sign
themselves up; an admin creates or invites them.

**Emails in demo mode** (booking confirmations, password resets, invitations) are not sent. Set
`LOG_LEVEL="DEBUG"` in `backend/.env` and restart the backend to see their content, including
links, in the backend terminal.

**Background jobs** (reminder emails, calendar sync, expiring slot holds) don't run by default.
To run them inside the API process, set `RUN_WORKERS_IN_PROCESS=True` in `backend/.env` and
restart the backend.

## 6. Run the tests

Run these before every pull request. CI runs the same ones.

Backend (with the virtual environment active):

```bash
cd backend
ruff check .        # lint: unused imports, undefined names
python -m pytest -q
```

Frontend:

```bash
cd frontend
npm run typecheck
npm test
npm run build
```

The backend tests use their own in-memory database, so they never touch your
`healthcare_dev.db`.

## 7. Keep your fork up to date

Before starting each new issue:

```bash
git fetch upstream
git switch -c 123-short-description upstream/main
```

After pulling new changes, run `pip install -r requirements.txt -c constraints.txt` and
`alembic upgrade head` in `backend`, and `npm ci` in `frontend`, in case dependencies or the
database changed.

Then follow [CONTRIBUTING.md](../CONTRIBUTING.md) to make your change and open a pull request.

---

## Optional: use PostgreSQL locally

SQLite is enough for almost every issue. Use PostgreSQL only when an issue involves locking,
concurrency or database constraints.

1. Start PostgreSQL. The quickest way is Docker:

   ```bash
   docker run --name healthcare-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=healthcare_db -p 5432:5432 -d postgres:16
   ```

2. In `backend/.env`, comment the SQLite `DATABASE_URL` line and uncomment the `postgresql` one.
3. Run `alembic upgrade head` and `python -m scripts.seed_demo` again, then restart the backend.

## Troubleshooting

| Problem | Fix |
|---|---|
| `python` not found (Windows) | Reinstall Python with "Add python.exe to PATH" ticked, or use `py` instead of `python`. |
| `Activate.ps1 cannot be loaded because running scripts is disabled` | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then activate again. |
| `ModuleNotFoundError` when starting the backend | The virtual environment isn't active. Activate it (step 3) and try again. |
| `no such table` errors | Run `alembic upgrade head` in `backend`. |
| `npm run ...` fails with "cannot find module" on Windows | Your path contains `&`. Clone into a path without it, or run the tool directly, e.g. `node node_modules/vite/bin/vite.js`. |
| Port 8000 or 5173 already in use | Stop the other program, or start the backend with `--port 8001` and set `VITE_DEV_API_TARGET="http://localhost:8001"` in `frontend/.env`. |
| The frontend loads but every request fails | The backend isn't running, or it's on a different port than `VITE_DEV_API_TARGET`. |
| A login says "Too many failed login attempts" | Wait 15 minutes, or delete `healthcare_dev.db` and repeat `alembic upgrade head` and `seed_demo`. |
| You want a fresh start | Delete `backend/healthcare_dev.db`, then repeat `alembic upgrade head` and `python -m scripts.seed_demo`. |

Still stuck? Ask on your assigned issue, and include the command you ran and the full error.
