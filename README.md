# private-finance

Local-first personal finance system with a secure FastAPI backend, encrypted SQLite-ready storage, and a React frontend for import, review, reporting, and net-worth tracking.

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

## Running Locally

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
- session cookies are `HttpOnly` and `SameSite=Strict`
- mutating endpoints require CSRF
- exports escape formula-like cells
- audit events are append-only at the database layer

