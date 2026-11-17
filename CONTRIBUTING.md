# Contributing

Thanks for wanting to help. This project is **maintainer-led**: the maintainer
([@SakthiQ](https://github.com/SakthiQ)) decides what gets built, opens the issues, assigns
them, reviews every pull request, and is the only person who merges into `main`. If you have
taken part in a Google Summer of Code style project, the flow will feel familiar.

## How work is assigned

1. **Find an issue.** Open issues labelled
   [`good first issue`](../../labels/good%20first%20issue) are the best place to start;
   [`help wanted`](../../labels/help%20wanted) are open to anyone with some experience.
2. **Ask for it.** Comment on the issue saying you would like to work on it, and briefly how
   you plan to approach it. Please do not start until you are assigned.
3. **Wait to be assigned.** The maintainer assigns the issue to you. An issue that already has
   an assignee is taken; pick another one.
4. **One issue at a time.** Finish (or hand back) your current issue before asking for the next.
5. **Keep it moving.** If there is no update on an assigned issue for 7 days, the maintainer may
   unassign it so someone else can pick it up. If you are stuck or out of time, say so on the
   issue; that is always fine.

Pull requests for issues that are not assigned to you, or with no issue at all, will usually be
closed. Found a bug or have an idea? Open an issue with the matching template first and the
maintainer will triage it.

## Getting set up

You will work on your own copy (a *fork*); you do not need write access to this repository.

**Follow [docs/local-setup.md](docs/local-setup.md)** for step-by-step instructions on
Windows, macOS and Linux. It covers installing the tools, running the backend and frontend,
signing in with demo accounts, running the tests and troubleshooting.

The short version, for those who have done this before (Python 3.12+, Node 22 LTS or 24 LTS):

```bash
git clone https://github.com/<your-username>/Healthcare-Appointment-Follow-up-Manager.git
cd Healthcare-Appointment-Follow-up-Manager
git remote add upstream https://github.com/SakthiQ/Healthcare-Appointment-Follow-up-Manager.git

cd backend                    # then create and activate a virtual environment
pip install -r requirements.txt -c constraints.txt
cp .env.example .env          # defaults work: SQLite + DEMO_MODE, no accounts or keys needed
alembic upgrade head
python -m scripts.seed_demo   # demo admin, doctor and patient (password: demo-password)
python -m uvicorn app.main:app --reload     # http://localhost:8000/api/v1/docs

cd frontend                   # in a second terminal
npm ci
cp .env.example .env
npm run dev                   # http://localhost:5173
```

`DEMO_MODE=True` replaces the AI, email and calendar integrations with offline mocks, so the
whole app runs without any API keys. You never need the maintainer's credentials, and you
should never put your own in a committed file.

## Making a change

1. **Branch from an up-to-date `main`:**
   ```bash
   git fetch upstream && git switch -c 123-short-description upstream/main
   ```
   (Start the branch name with the issue number.)
2. **Keep the change focused** on the issue. Unrelated fixes belong in their own issue.
3. **Add or update tests.** Bug fixes need a test that fails without the fix; new behaviour needs
   tests that describe it.
4. **Run the checks locally** before pushing. CI runs the same ones:
   ```bash
   cd backend  && python -m pytest -q
   cd frontend && npm run typecheck && npm test && npm run build
   ```
5. **Update the docs** (README, `docs/`, `.env.example`) when you add a setting or change behaviour.
6. **Never commit secrets** or local files: `.env`, `*.db`, API keys or tokens.
7. **Database changes** need an Alembic migration in `backend/alembic/versions/` that applies to an
   empty database (`alembic upgrade head`).
8. **Dependencies:** do not add or upgrade packages unless the issue asks for it. Backend versions
   are pinned in `backend/constraints.txt`.

## Opening a pull request

- Open it against `main` and fill in the template. Write `Closes #123` so the issue is linked and
  closed on merge.
- CI must be green. The first time you contribute, the maintainer has to approve CI before it runs
  on your pull request; that is a GitHub safety measure, not a problem with your change.
- The maintainer will review. Expect questions and change requests; push new commits to the same
  branch to address them (please do not force-push during review).
- Only the maintainer merges. Pull requests are usually squash-merged, so your branch's commit
  history does not need to be tidy.

## Code style

Follow the patterns already in the code around your change. In short: routes in
`backend/app/api/`, business rules in `backend/services/`, database access in
`backend/repositories/`; comments explain *why*, not *what*. On the frontend, keep API calls in
`frontend/src/api/client.ts` and add a test next to the component you change.

## Security issues

Do **not** open a public issue for a security problem. See [SECURITY.md](SECURITY.md).

## Code of conduct

Everyone taking part is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
