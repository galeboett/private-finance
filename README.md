# private-finance

Local-first personal finance system with a secure FastAPI backend, encrypted SQLite-ready storage, and a React frontend for import, review, reporting, and net-worth tracking.

## What This Is

This project is designed to replace a manual Excel workflow with:

- deterministic CSV/XLSX imports
- deduplication and cleanup
- human-reviewed categorization
- cash-flow and net-worth reporting
- optional later private mobile access

## Repository Layout

- `backend/` FastAPI application, data model, services, tests
- `frontend/` React/Vite UI shells
- `docs/` threat model and implementation notes
- `samples/` sample preset definitions for shared import formats

## Current Status

This initial implementation includes:

- local setup and login flow
- localhost security middleware
- core schema and category seeding
- account and preset management
- import preview and commit pipeline for CSV files
- review inbox and dashboard summaries
- backup and CSV export foundation

## Workflow

See [docs/workflow.md](docs/workflow.md) for the intended user workflow and the split between automated import work and human review.

For working with a co-worker, see [docs/collaboration.md](docs/collaboration.md).

## Running Locally

### One-command start

```powershell
.\run.ps1
```

This rebuilds the frontend, prepares the backend environment, and starts the app at `http://127.0.0.1:8000`.

### Restart after code changes (keeps your data)

```powershell
.\scripts\restart.ps1
```

This rebuilds the frontend, stops anything on port 8000, and starts the backend again. It does **not** delete your SQLite database.

Useful flags:

```powershell
.\scripts\restart.ps1 -Background      # start backend detached (for git hooks)
.\scripts\restart.ps1 -SkipBuild       # backend-only restart
.\scripts\restart.ps1 -SkipDeps        # skip pip install
```

### Auto-restart after `git pull`

Install the git hook once:

```powershell
.\scripts\install-git-hooks.ps1
```

After that, whenever you `git pull` and the update touches `backend/`, `frontend/`, or the restart scripts, the app rebuilds and restarts automatically in the background.

### Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev]
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

## Security Notes

- v1 binds to `127.0.0.1` only
- session cookies are `HttpOnly` and `SameSite=Strict`, with idle timeout and an absolute session lifetime
- mutating endpoints require CSRF
- the password can be changed from a logged-in session (`POST /api/password`); changing it revokes all other sessions
- exports escape formula-like cells and stream from memory (no plaintext copy is left on disk)
- backups use SQLite's online backup API and are constrained to `data/backups/`
- audit events are append-only at the database layer

## Configuration

Settings can be provided via a `.env` file in `backend/` or environment variables prefixed with `PF_`:

- `PF_IMPORT_INBOX` — where statement files are scanned and staged (default `~/PrivateFinance/import-inbox`, outside the repository; the older `PF_IMPORT_INBOX_DIR` name is also accepted).

- `PF_VENMO_SELF_NAME` — your display name as it appears in Venmo statement `From`/`To` columns. When set, imported Venmo descriptions correctly phrase who paid whom; when unset, descriptions keep the statement's own From/To order.
- `PF_BACKUP_DIR` — where database backups are stored (default `data/backups`).
- `PF_ABSOLUTE_SESSION_HOURS` — maximum session lifetime regardless of activity (default 12).

## Product Direction

The app is intended to grow toward:

- unified bank and credit card transactions
- fixed spending categories
- investment snapshot tracking
- net-worth summaries
- secure self-hosted mobile access later
