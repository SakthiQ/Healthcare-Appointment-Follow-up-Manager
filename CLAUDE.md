# CLAUDE.md

Guidance for AI coding assistants (Claude Code and similar) working in this repository. Human contributors: [CONTRIBUTING.md](CONTRIBUTING.md) is the full guide, and everything here agrees with it.

## What this is

Healthflow is a hospital appointment and follow-up platform with patient, doctor and admin portals, AI visit summaries, reminders and calendar sync.

- **Backend (`backend/`):** FastAPI with synchronous handlers, SQLAlchemy 2, Alembic, pytest and ruff.
- **Frontend (`frontend/`):** React 19, TypeScript 7, Vite and vitest.
- **Databases:** production runs on PostgreSQL; local development and the tests use SQLite.

## Commands

The required CI checks run these same commands:

```bash
# backend
cd backend
pip install -r requirements.txt -c constraints.txt
ruff check .
python -m pytest -q
DATABASE_URL=sqlite:///./ci_migration_check.db alembic upgrade head   # migrations on an empty DB

# frontend
cd frontend
npm ci
npm run typecheck && npm test && npm run build
```

- **Running the app:** see [docs/local-setup.md](docs/local-setup.md), or run `docker compose up --build` for the full stack on PostgreSQL.
- **Demo accounts:** `python -m scripts.seed_demo` (in `backend/`).
- **`&` in the folder path:** if the checkout's path contains `&`, `npm run` fails on Windows. Call the tools directly instead (`node node_modules/vitest/vitest.mjs run`, `node node_modules/typescript/bin/tsc --noEmit`), or work from a path without `&`.

## Where code goes

**Backend:**
- `app/api/`: routes;
- `services/`: business rules;
- `repositories/`: database access;
- `models/`: SQLAlchemy models;
- `schemas/`: Pydantic schemas;
- `providers/`: AI, email and calendar integrations, each with a mock;
- `workers/`: background jobs.

**Frontend:**
- all API calls go in `src/api/client.ts`, with their types in `src/api/types.ts`;
- pages go in `src/pages/`;
- user-facing strings go in `src/locales/` (`en`, `ta`, `hi`). Missing keys fall back to English.

## Rules

- **Secrets:** never commit them: no `.env` files, `*.db` files, keys, tokens or passwords, not even placeholder ones, because GitGuardian runs on every PR. `DEMO_MODE=True` swaps every integration for an offline mock, so no change should need real credentials.
- **Scope:** keep each change to the issue it's for. Don't add or upgrade dependencies unless the issue asks; backend pins live in `backend/constraints.txt`.
- **Tests:**
  - every change needs tests: a bug fix needs one that fails without the fix;
  - a new page test should call `await expectNoA11yViolations(document.body)` from `src/test/a11y.ts`;
  - tests run with `RATE_LIMITING_ENABLED=False`, and an autouse fixture empties the tables after each test.
- **Migrations:** every schema change needs an Alembic migration that applies to an empty database. Keep a single head.
  - SQLite needs `batch_alter_table` for column changes.
  - To add a value to a PostgreSQL enum, use `ALTER TYPE ... ADD VALUE IF NOT EXISTS` inside `op.get_context().autocommit_block()`, guarded to PostgreSQL only.
- **Side effects:** emails, calendar sync and waitlist notices run after the main transaction commits, and they're best-effort: if one fails, the booking must not fail.
- **Audit:** access to patient data is audited through `audit_service`. New endpoints that read patient or clinical data must record an audit entry.
- **AI output:** it's validated against a Pydantic schema. Store invalid output as a FAILED `AISummary` and never show it to the user. AI features must work with `MockAIProvider`.
- **Docs:** update the README, `docs/` and `.env.example` when you add a setting or change behaviour.
- **Comments:** explain *why*, not *what*. Follow the patterns already around your change.

## Pull requests and issues

The project is maintainer-led: issues are assigned before work starts, and only the maintainer merges.

- **Branches:** branch from an up-to-date `main` and start the branch name with the issue number.
- **Before you start:** don't take an issue that's already assigned to someone else.
- **Opening the PR:** open it against `main`, fill in the template, and write `Closes #N`.
- **Merging:** don't merge PRs or enable auto-merge on the maintainer's behalf.
- **Security problems:** report them privately (see [SECURITY.md](SECURITY.md)), never in a public issue.
