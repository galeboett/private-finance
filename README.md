# private-finance

Local-first personal finance system with a FastAPI backend, SQLite storage, and a React frontend for import, review, reporting, reconciliation, and net-worth tracking.

The database and backups are currently plaintext at rest. The application password protects access through the local API, but disk encryption such as BitLocker is still recommended for financial data and PII. See the [privacy assessment](docs/privacy-risks.md).

## What This Is

This project is designed to replace a manual Excel workflow with:

- deterministic CSV/XLSX imports
- deduplication and cleanup
- human-reviewed categorization
- cash-flow and net-worth reporting
- optional later private mobile access

## Repository Layout

- `backend/` FastAPI application, data model, services, tests
- `frontend/` React/Vite application and extracted feature modules
- `docs/` current guides, security assessments, implementation plans, and historical evaluations
- `samples/` sample preset definitions for shared import formats

## Current Status

The implemented application includes:

- local setup/login, session expiry, CSRF protection, and localhost-only serving
- CSV, OFX/QFX, and balance-only PDF ingestion through a private Import Inbox
- staged import review, sign normalization, reliable-reference dedupe, and ledger-wide duplicate review
- transaction categorization, saved rules, bulk editing, Trash, Activity, and conflict-aware Undo/Redo
- transfer, card-payment, refund, and reconciliation workflows
- anchored net worth, investment holdings, tax lots, manual balances, and statement checkpoints
- filter-driven cash-flow, spending, and net-worth analysis
- constrained SQLite backup/restore APIs plus JSON app-data export/import

Iteration 3 Phase 12—the settings/navigation overhaul and frontend decomposition—is in progress. See the [documentation index](docs/README.md), [active implementation plan](docs/pf-implementation-plan-iteration-3-7-14-26.md), and [changelog](CHANGELOG.md).

## Workflow

See [docs/workflow.md](docs/workflow.md) for the current user workflow and the split between automated import work and human review.

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

Near-term work is tracked in the active implementation plan. The main remaining themes are the Phase 12 settings/decomposition work, percentage-based splits, stronger encrypted backup/storage options, and an explicitly secured remote-access design if non-local use is added later.
