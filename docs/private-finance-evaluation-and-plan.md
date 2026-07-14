# private-finance — Project Evaluation & Remediation Plan

**Evaluated:** July 2026 · **Scope:** full backend (FastAPI/SQLite), frontend (React/Vite), docs, scripts, tests
**Method:** independent static analysis of all source files; docs used as a reference point for intent, then verified against actual behavior.

---

## 1. Executive Summary

private-finance is a well-conceived local-first personal finance app with a genuinely thoughtful foundation: money is stored as integer cents, imports go through a preview → commit pipeline, deduplication uses content hashes, audit events are append-only at the database layer, and the localhost threat model (Host/Origin allowlists, CSRF, HttpOnly SameSite=Strict cookies, Argon2, login rate limiting) is more disciplined than most hobby projects ever get.

However, the current state has **one crash-level bug that breaks the app's core promise** (duplicate-safe re-imports), **several silent data-corruption paths** (double-counted net worth on re-import, wrong snapshot dates, mis-typed history transactions), and **hardcoded personal data and machine paths** that break the two-person collaboration model the docs describe. The frontend is a 3,568-line single-component monolith with 68 `useState` hooks, no routing, no loading states, no logout, no session-expiry handling, and near-zero accessibility — functional for one careful user on one machine, but at the ceiling of what can be maintained or extended.

The plan below is sequenced so that **correctness lands first** (Phase 0–1), **security hardening second** (Phase 2), then the **frontend re-architecture** that unblocks every future UX improvement (Phase 3–4), then **reporting depth and import robustness** (Phase 5–6), with **quality infrastructure** (CI, API tests, migrations) starting in week one and running throughout.

| Area | Grade | One-line assessment |
|---|---|---|
| Product concept & workflow design | A− | Clear, honest workflow docs; preview-first import is the right model |
| Backend data model | B+ | Sound schema; missing indexes, enums-as-strings, no migrations |
| Backend correctness | C− | Crash bug in the core import path; several silent data-integrity bugs |
| Security posture | B | Strong for localhost v1; backup/restore path handling and session lifecycle are the weak spots |
| Frontend architecture | D+ | Monolith at its scaling limit; full-world refetch after every mutation |
| UX / UI | C+ | Attractive, coherent visual design undermined by missing fundamentals (Enter-to-submit, loading states, logout, a11y) |
| Testing & tooling | C | 30 unit tests but zero API tests, no CI, and the untested path is exactly where the crash bug lives |
| Documentation | B+ | Unusually good; needs a sync pass where requirements have changed (rule application) |

---

## 2. What's Working Well (Keep and Protect)

These strengths should be explicitly preserved through the remediation work:

- **Integer-cents money handling** (`money.py`) with `Decimal` parsing, `ROUND_HALF_UP`, and basis points for share quantities. No floats anywhere in the money path.
- **Preview → commit import pipeline** with staging rows retained (`StagingRow` keeps raw + normalized JSON), giving a forensic trail for every imported row.
- **Content-hash deduplication design** — `source_hash` includes an ordinal counter so legitimate same-day/same-amount duplicates survive while file re-uploads are (intended to be) idempotent.
- **Append-only audit log enforced by SQLite triggers**, not just application discipline, and deliberately excluded from the app-data import/export wipe.
- **Localhost threat model actually implemented**: Host and Origin allowlist middleware (DNS-rebinding protection), per-session CSRF tokens on all mutating routes, Argon2id hashing, formula-escaped CSV export, login backoff.
- **Honest docs** — `threat-model.md` lists its own gaps; `workflow.md` explains why account creation is manual-first. This is a healthy engineering culture signal.
- **Typed destructive actions** — delete flows require typing `DELETE`, and account deletion correctly cascades through splits, transfer links, and back-references.
- **UI design tokens** — a clean CSS variable system, coherent light palette, consistent status badge semantics, resizable sidebar, customizable dashboard widgets, and shift-click range selection in tables.

---

## 3. Findings

### 3.1 Critical Bugs — Correctness & Data Integrity (P0)

These break core functionality or silently corrupt financial data. Each was verified against the source, not inferred from docs.

| ID | Severity | Location | Finding | Status |
|---|---|---|---|---|
| **BUG-01** | 🔴 Crash | `services/importers.py:793` (`commit_import`) | `skipped_by_account_id[account.id] += 1` references a variable that **does not exist in this function** (it belongs to `_commit_categorized_history_rows`). The moment any duplicate row is found during a normal CSV commit, a `NameError` is raised, the endpoint returns 500, and the whole import rolls back. **Re-importing any file that overlaps an earlier import is impossible** — the exact scenario the dedupe system exists for. Verified by AST analysis: the name is loaded at line 793 and never assigned in `commit_import`. | ✅ Fixed + regression tests, including raw-CSV re-import after account merge, reference-first matching, and conflicting-reference review |
| **BUG-02** | 🔴 Data corruption | `commit_import` brokerage branch | `HoldingSnapshot` rows have **no dedupe protection at all** — no unique constraint, no file-hash check against prior `ImportBatch` records, no source hash. Re-importing the same positions CSV (or the same file after BUG-01 is fixed) **doubles reported net worth** for that date. | ✅ Fixed (replace-on-import) + test |
| **BUG-03** | 🔴 Data corruption | `_extract_snapshot_date` | The function is a no-op: both the loop body and the fallback return `date.today()`. Importing a brokerage file from three months ago records the snapshot **as of today**, silently overwriting the meaning of the net-worth timeseries. Combined with BUG-02, historical net worth cannot be trusted. | ✅ Fixed (filename parsing + `snapshot_date` param) + tests |
| **BUG-04** | 🟠 Data quality | `_history_transaction_type` | The fallback returns `"expense"` for everything unmatched — including **positive deposits into checking accounts**, which then inflate expense totals in `cash_flow_summary` (which takes `abs(amount)` per expense row). Income in a categorized-history file without the word "income" in its category is misclassified. | ✅ Fixed + type matrix tests |
| **BUG-05** | 🟠 DoS / consistency | `main.py` `imports_commit` | The commit endpoint **does not enforce `import_file_size_limit_mb`**, though analyze and preview both do. A user (or a script) can commit an arbitrarily large file straight to the pipeline. Same endpoint also lets `UnicodeDecodeError` escape as a 500 on non-UTF-8 files (preview/analyze share this). | ✅ Fixed |
| **BUG-06** | 🟠 Display correctness | `App.tsx` overview metric tiles | The Income/Expenses/Net tiles used a zero-falsy `\|\|` fallback (`reportIncomeCents \|\| totalIncomeCents`), so a period with legitimately $0 income silently displayed the all-time figure instead. | ✅ Fixed |
| **BUG-07** | 🟠 Portability / privacy | `importers.py:277`, `scripts/restart.ps1` | The Venmo importer **hardcodes the string `"matt matt"`** as the account owner's name to determine payment direction — personal data in source, and every other user gets wrong payer/recipient labels. `restart.ps1` hardcodes `C:\Users\YehMa\...` paths for python/node/pnpm with no fallback for pnpm — the collaborator described in `collaboration.md` cannot run `run.ps1`. | ✅ Fixed (`PF_VENMO_SELF_NAME`; PATH-based scripts) |
| **BUG-08** | 🟡 Correctness | `bootstrap.py` migration + `reporting.py` | `category_totals` counts split rows regardless of parent transaction `status` (voided transactions' splits still count) and regardless of transaction type (splits on income count as spending). It also has **no date filtering** — the "Spending" report is all-time on the backend, then re-filtered client-side from a different endpoint, so the two disagree. | ⏳ Open — Phase 1 |
| **BUG-09** | 🟡 Live-DB corruption risk | `services/backups.py` + `main.py` restore | Restore does `shutil.copy2(source, db_path)` **while the SQLAlchemy engine holds open connections** to that same SQLite file. On Windows this can fail outright; anywhere it can corrupt or interleave with WAL state. There is no engine dispose/reopen, no validation that the source is a SQLite file or one of this app's backups, and no automatic pre-restore safety copy. | ✅ Fixed (online backup API, validation, safety copy) |

**Withdrawn finding (for the record):** an earlier draft flagged bulk rule application auto-confirming matched transactions as a contradiction of `workflow.md`. Under the updated requirements this is **intended behavior**, so the remediation was a doc sync (done — `workflow.md` now describes confirm-on-apply), not a code change. Import-time rule matches still land as `suggested` and stay in review; they now also carry the rule's suggested transaction type so both paths agree.

### 3.2 Security Findings

The localhost model is solid; these are the remaining meaningful gaps, roughly in priority order.

- **SEC-01 — Arbitrary filesystem paths in backup/restore.** `POST /api/backups?destination=<any path>` and `/api/backups/restore?source=<any path>` copy files to/from any location the process can reach. Within the threat model (authenticated localhost user) this is survivable, but it is an arbitrary read/write primitive one CSRF-bypass away from being serious. Constrain to an allowlisted backups directory; have the UI offer a folder picker within it.
- **SEC-02 — No password change or rotation.** The single `AppUser` password can never be changed after setup — no endpoint, no UI. Also no re-auth ("sudo mode") before exports, restore, or app-data replacement, which `threat-model.md` itself lists as a gap.
- **SEC-03 — Session lifecycle.** Sessions slide forever (each request extends expiry) with **no absolute maximum lifetime**, expired rows are never purged from `session_tokens`, and there is no logout-all. The frontend has **no logout control at all** (the backend endpoint exists, unused), and no 401 handling — an idle-expired session just makes every action fail with a generic toast while stale data stays on screen.
- **SEC-04 — Full-data export over a GET.** `GET /api/exports/app-data.json` returns the entire financial database. SameSite=Strict protects it cross-site, but combined with SEC-02 (no re-auth) it means any momentary access to an unlocked session exfiltrates everything in one click. Gate behind re-auth once SEC-02 lands.
- **SEC-05 — `verify_password` swallows all exceptions** and never checks `PasswordHasher.check_needs_rehash`, so parameter upgrades never apply. Minor, cheap to fix.
- **SEC-06 — CSV export writes to disk** (`data/exports/transactions.csv`) before serving — an unencrypted plaintext copy of transactions persists on disk after every export, contradicting the "casual disk access" threat-model entry. Stream it instead.
- **SEC-07 — XLSX parsing hardening.** `load_workbook` on user files without row/size caps beyond the 10 MB request limit; the threat model already flags zip-bomb hardening as pending. Add cell/row caps and a decompression-ratio guard.

### 3.3 Backend Architecture & Code Quality

- **ARCH-01 — No migrations framework.** Schema changes are ad-hoc (`ALTER TABLE` sniffing in `bootstrap.py`). This does not scale past the second migration and makes collaborator databases drift. Adopt Alembic now, while the schema is small.
- **ARCH-02 — Missing indexes.** No index on `transactions(account_id, transaction_date)`, `transactions(review_status)`, `holding_snapshots(account_id, snapshot_date)`, or `session_tokens(expires_at)`. Fine at 1k rows, painful at 100k (years of history × multiple accounts is exactly the product goal).
- **ARCH-03 — Unpaginated, unfiltered list endpoints.** `/api/transactions` and `/api/review` return every row, every time. The `TransactionFilter` schema exists in `schemas.py` but is **never used by any route** (dead code). Server-side pagination + filtering is a prerequisite for the frontend fixes.
- **ARCH-04 — String enums everywhere.** `transaction_type`, `review_status`, `account_type`, `status` are free strings validated nowhere — `PATCH /api/transactions/{id}` accepts any `review_status`/`transaction_type` value and any `category_id` (no FK existence check at the API layer). Introduce Python `StrEnum`s + Pydantic validation.
- **ARCH-05 — Deprecated APIs.** `datetime.utcnow()` throughout (deprecated in 3.12; will emit warnings and eventually break) and `@app.on_event("startup")` (replaced by lifespan handlers).
- **ARCH-06 — Vestigial preset system.** `ImportPreset` model + create/list endpoints exist, `config_json` is never read, and detection is five hardcoded header constants. Either remove the endpoints for now or make presets real (Phase 6 makes them real).
- **ARCH-07 — Missing CRUD.** Rules can be created and applied but **never edited or deleted**; categories can be created and renamed but never deleted or merged; the splits and void endpoints exist but have **no UI at all**. Every one of these is a dead end a real user will hit in week one.
- **ARCH-08 — Reporting in Python instead of SQL.** `cash_flow_summary`, `latest_net_worth_by_account`, `latest_investment_allocation`, and `apply_rule` all load full tables into Python loops. Convert to aggregate queries when adding date filters (Phase 5).
- **ARCH-09 — Double commits around audit events** (`setup`, `login`) mean the audited action and its audit record are separate transactions; a crash between them loses the audit trail for a real event. Fold into one transaction.
- **ARCH-10 — "Net worth" naming.** The dashboard field `net_worth_snapshot_cents` and the reports both cover **investments only**; cash balances (which checking imports already carry via `running_balance_cents`) and credit-card debt are excluded. The reports page honestly says "Investment-backed net worth," but the dashboard summary and README oversell it. Phase 5 makes it true net worth.

### 3.4 Frontend Architecture

- **FE-01 — Single-file, single-component monolith.** `App.tsx` is 3,568 lines; the `App()` component alone spans ~2,600 lines and holds **68 `useState` hooks**. Every keystroke in any input re-renders the entire application, and all report aggregates (`totalIncomeCents`, etc.) are recomputed over the full transaction array in the render body on each pass. Only 4 `useMemo`/`useCallback` usages exist in the whole file.
- **FE-02 — Full-world refetch.** `loadData()` fires **11 parallel API calls** (all transactions, all holdings, all rules, all reports…) and is re-run after nearly every mutation — confirming one transaction refetches the entire database. `Promise.all` also means one failed call rejects everything with no partial rendering.
- **FE-03 — No routing.** Views are plain state (`activeView`), so refresh loses your place, the browser back button does nothing, and no screen is linkable. This also blocks the "open this account" / "jump to review" flows that a finance app lives on.
- **FE-04 — No loading or in-flight states.** Zero spinners/skeletons; the initial load renders empty states indistinguishable from "you have no data." No button is disabled while its request is in flight — the import **Commit button can be double-clicked**, which (after BUG-01 is fixed) is saved only by the dedupe hash, and for brokerage files (BUG-02) would double holdings.
- **FE-05 — No 401/session handling.** Expired session → every action shows a generic error toast; user must know to refresh. Pair with the missing logout (SEC-03).
- **FE-06 — No client-side error boundary**, so any render error white-screens the app.
- **FE-07 — `window.confirm` for the most destructive action** in the app (replace-all app-data import), while lesser deletes get the nicer typed-DELETE inline pattern.
- **FE-08 — Type duplication.** All API payload types are hand-written in `App.tsx` and can drift from the backend silently. Generate them from the FastAPI OpenAPI schema.

### 3.5 UX / UI Evaluation

**Visual design: genuinely good.** The token palette, card system, status badges, and report surfaces feel coherent and calm — appropriate for a finance tool. The dashboard widget customization, resizable sidebar, period chips, shift-click selection, and typed-DELETE confirms are above-average touches.

**Interaction fundamentals: several table-stakes misses.**

| ID | Finding | Why it matters |
|---|---|---|
| UX-01 | Login/setup have **no `<form>` and no Enter-to-submit** — the password field only works by clicking the button. | This is the first screen every session; also degrades password-manager autofill. |
| UX-02 | **No logout button** anywhere in the UI. | Security expectation for a finance app; the backend endpoint already exists. |
| UX-03 | **Toasts never dismiss** — no timeout, no close button, no `aria-live`. A success toast sits until the next action replaces it; screen readers never announce results. | Feedback becomes noise; a11y-blocking. |
| UX-04 | **No loading states** (see FE-04). First paint shows "No investment snapshots yet"-style empty text while data is actually loading. | Users can't tell "empty" from "loading" from "broken." |
| UX-05 | **Session expiry is invisible** (see FE-05/SEC-03). | After 30 idle minutes the app looks alive but every action fails. |
| UX-06 | **Accessibility is near-absent**: 7 aria attributes in 3,568 lines; 6 `<label>`s total (placeholder-only inputs); 2 `:focus` styles and no `:focus-visible` system; modals/popups without focus traps or Escape-close consistency (global Escape exists but focus is not returned); no `prefers-reduced-motion`; status conveyed by color alone in bar charts. | Keyboard and screen-reader use is effectively unsupported. |
| UX-07 | **Only 2 media queries** — the layout is desktop-only. Acceptable for v1, but the stated roadmap is mobile access, and none of the tables/toolbars adapt. | Plan responsive work before the mobile milestone, not during. |
| UX-08 | **Dead-end flows**: rules can't be deleted from the UI (or API); categories can't be deleted; a mistaken rule or typo category is permanent. Splits/void features exist server-side with no UI. | Users will create a bad rule in week one and be stuck with it. |
| UX-09 | **No global search** across transactions (only per-view filters), and no URL-shareable filtered views (FE-03). | Finding "that $84 charge in March" is the most common task in this product category. |
| UX-10 | **Import UX gaps**: no drag-and-drop target, no progress for large files, preview caps at 25 rows with no total-row count shown, and after commit the modal closes without linking to the new batch's report/warnings. | The import flow is the product's front door. |
| UX-11 | **Empty/first-run experience**: no onboarding checklist (create account → import → review), even though the workflow doc describes exactly this sequence. | The docs know the golden path; the UI doesn't teach it. |

### 3.6 Testing, Tooling & Docs Gaps

- **TEST-01 — The crash bug lives exactly in the untested gap.** 30 unit tests exist, and categorized-history dedupe *is* tested — but `commit_import`'s duplicate path (BUG-01) has no test. There are **zero API-level tests** despite `httpx` already being a dev dependency, zero frontend tests, and no CI, even though `collaboration.md` builds the whole workflow around PRs that "merge only after the app builds."
- **TEST-02 — `samples/` is empty** except a README promising "redacted golden import fixtures"; test fixtures are inline byte strings instead, so real-world format drift (banks change headers) has no canary.
- **DOC-01 — Docs are out of sync in two places**: `workflow.md` still says bulk rule application never auto-confirms, which no longer matches the updated requirement (confirming matches is now intended behavior), and `preset-format.md` describes a preset system richer than the hardcoded detection that actually exists. Sync docs in the same PR as each related change.
- **TOOL-01 — No lint/format/typecheck gates**: no ruff/black/mypy config for the backend, no eslint/prettier for the frontend, and `tsc --noEmit` isn't wired into any script or hook.

---

## 4. Remediation Plan

> **Implementation status (July 2026 remediation pass):** Phase 0 is fully implemented in the accompanying build, along with a substantial slice of Phases 1–2 and quick UX wins from Phase 4: holdings replace-on-import (BUG-02), snapshot-date parsing + override (BUG-03), history typing matrix (BUG-04), restore safety + constrained backup paths (BUG-09/SEC-01), password change endpoint (SEC-02 partial), absolute session lifetime + purge + sign-out button (SEC-03 partial), Argon2 hygiene (SEC-05), streamed richer CSV export (SEC-06), rule edit/delete endpoints (ARCH-07 partial), real auth forms with Enter-to-submit (UX-01), logout (UX-02), auto-dismissing `aria-live` toasts (UX-03), `duplicate_of_transaction_id` population, double-submit guards, `:focus-visible` outlines and `prefers-reduced-motion` (UX-06 partial). See `CHANGELOG.md` in the repo for the authoritative list. Items below are marked ✅ done, ◐ partial, or left unmarked (open). **As of July 14, 2026, the current backend suite (`151 passed`), frontend type check, six Vitest tests, and production Vite build are verified green.**

Sequenced for risk: correctness first, then security, then the frontend re-architecture that everything UX depends on. Effort sizes: **S** ≤ ½ day, **M** ≤ 2 days, **L** ≤ 1 week. Phases 0–2 are backend-safe (no UI rewrite required) so they can ship immediately.

### Phase 0 — Hotfixes (target: 1–2 days)

Goal: stop the bleeding. Every item is small, isolated, and testable.

1. ✅ **Fix BUG-01** (S): delete the stray `skipped_by_account_id` line in `commit_import` (the `skipped += 1` above it is the correct counter). Add a regression test: commit the same CSV twice, assert second commit returns `inserted=0, skipped=N` with HTTP 200.
2. ✅ **Fix BUG-05** (S): add the size check to `imports_commit`; wrap all `content.decode("utf-8-sig")` sites in a helper that raises a 400 ("File must be UTF-8 CSV") instead of 500 on `UnicodeDecodeError`.
3. ✅ **Fix BUG-07a** (S): replace the hardcoded `"matt matt"` with a `PF_VENMO_SELF_NAME` setting (env/config), defaulting to unset → fall back to sign-based direction only. Document in README.
4. ✅ **Fix BUG-07b** (S): make `restart.ps1` resolve `python`, `node`, and `pnpm` from `PATH` first, using the personal cache paths only as optional overrides via env vars. Verify the collaborator can run `run.ps1` cold.
5. ✅ **Sync `docs/workflow.md`** (S): update the "How Save Rule Works" section to document the current intended behavior — applying a rule in bulk sets the rule's category and type **and confirms** matching transactions (updated requirement). Keep the surrounding review-workflow description accurate.
6. ✅ **Add temporary double-submit guard** (S): disable the Commit/Preview/Restore buttons while their request is in flight (a simple `busy` state per action). Full loading-state system comes in Phase 4.

**Definition of done:** re-importing an overlapping CSV succeeds with correct skip counts; a collaborator can clone and run the app; `workflow.md` matches actual rule-apply behavior; all existing tests pass plus new regression tests for BUG-01/05.

### Phase 1 — Data Integrity & Import Correctness (target: 1 week)

1. ◐ **Holdings idempotency — fix BUG-02** (M): *(replace-on-import implemented + tested; the DB-level unique constraint still lands with Alembic in Phase 7)* add a unique constraint on `holding_snapshots(account_id, snapshot_date, symbol, description)` (via Alembic, see Phase 7), and before inserting a brokerage batch, delete-and-replace that account+date's snapshot set inside the same transaction. Re-importing the same file becomes a clean replace, not a double-count.
2. ◐ **Snapshot dating — fix BUG-03** (M): *(filename parsing, warning fallback, and `snapshot_date` API override implemented + tested; the import-UI date field remains)* actually parse dates from filenames (`Portfolio_Positions_Jul-04-2026.csv` style patterns + ISO tokens); when no date is found, **ask the user**: return a `needs_snapshot_date` flag from analyze/preview and add a date field to the import UI (default today, clearly labeled). Never silently guess.
3. ◐ **History transaction typing — fix BUG-04** (M): *(typing matrix implemented + tested; the retroactive re-type of previously imported rows remains)* positive amounts on checking/savings default to `income` unless the category says otherwise; add unit tests enumerating the sign × account-type × category matrix. Re-type existing mis-typed rows with a one-off maintenance endpoint or Alembic data migration, and surface a "re-typed N rows" audit event.
4. **Category totals correctness — fix BUG-08** (M): join splits to their parent transaction and filter `status == "active"` and `transaction_type == "expense"`; add `start_date`/`end_date` query params (wire the existing `TransactionFilter` schema in); the frontend Spending report then uses server filtering identical to the period chips.
5. ✅ **Restore safety — fix BUG-09** (M): *(implemented with SQLite online-backup API, magic-byte validation, automatic pre-restore copy, engine dispose, and unit tests)* on restore, (a) validate SQLite magic bytes + presence of expected tables, (b) `engine.dispose()` before copy, (c) write an automatic pre-restore safety copy `pre-restore-<timestamp>.sqlite3`, (d) re-run `initialize_database()` after copy. Add an API test.
6. **Enum validation — ARCH-04** (M): introduce `TransactionType`, `ReviewStatus`, `AccountType`, `RowStatus` StrEnums; validate in Pydantic schemas; validate `category_id` existence on transaction PATCH and rule create.
7. ◐ **Duplicate-review UX truthing** (S): *(backend field populated and exposed; the side-by-side review UI remains)* `_is_possible_duplicate` flags same date+amount+different description — surface *which* existing transaction it matched (`duplicate_of_transaction_id` is already in the schema, never populated). Populate it so the review UI can show the pair side-by-side (UI in Phase 4).
8. ✅ **Rule consistency at import time** (S): import-time matching currently sets only the category; also apply `rule.suggested_transaction_type` so import suggestions match what bulk-apply would produce. Imported matches still land as `suggested` (in review), while bulk apply confirms — both by design.

**Definition of done:** importing the same brokerage file twice yields identical net worth; historical files land on their true dates; the sign/type matrix is fully unit-tested; restore is crash-safe and validated.

### Phase 2 — Security Hardening (target: 1 week)

1. ◐ **Password change + re-auth (SEC-02)** (M): *(password change endpoint implemented, revokes other sessions; re-auth/elevated mode and settings UI remain)* `POST /api/password` requiring the current password; a `POST /api/reauth` issuing a short-lived (10 min) elevated flag on the session; require elevation for app-data export, app-data import, restore, and password change. Settings UI section for password change.
2. ◐ **Backup path constraint (SEC-01)** (M): *(constrained to `data/backups/`, list endpoint added, path-escape tests in place; backups/restore UI remains)* default backups to `data/backups/`; accept only paths inside it (resolve + `is_relative_to` check). UI lists existing backups with dates/sizes and offers restore-from-list. Keep an "advanced: custom path" escape hatch behind re-auth if the user insists.
3. ◐ **Session lifecycle (SEC-03)** (M): *(absolute lifetime, purge-on-login, and sign-out button implemented; 401 interceptor/relogin UX remains in Phase 3)* absolute session lifetime (e.g., 12 h) alongside the 30-min idle window; purge expired rows on login and via startup task; add the **logout button** (frontend) wired to the existing endpoint; on any 401, clear client state and return to the login screen with a "session expired" notice (pairs with FE-05 work).
4. ✅ **Streamed CSV export (SEC-06)** (S): return `StreamingResponse` from memory; delete the `data/exports` write. Also widen the export columns (account, institution, category, note, posted date) — the current export is too lossy to be a real backup of the review work.
5. ✅ **Argon2 hygiene (SEC-05)** (S): catch only `VerifyMismatchError`/`VerificationError`; on successful login, `check_needs_rehash` → rehash and store.
6. **XLSX guards (SEC-07)** (S): cap rows (e.g., 50k) and cells read in `_read_history_rows`; reject files whose decompressed size ratio exceeds a threshold.
7. **Encrypted backups — begin SQLCipher track** (L, can run parallel): spike `sqlcipher3`/`pysqlcipher3` compatibility with SQLAlchemy; if viable, key derivation from the login password (with an explicit recovery-key export); if not viable on Windows, fall back to encrypting backup archives (age/AES-GCM via `cryptography`) as the threat model's stated next step. Land at least encrypted backup archives this phase; full at-rest DB encryption may extend into Phase 6 timeframe.

**Definition of done:** password can be rotated; destructive/export actions require fresh re-auth; sessions expire absolutely and visibly; backups are constrained, listed, and encrypted (archive-level at minimum).

### Phase 3 — Frontend Re-architecture (target: 2–3 weeks)

This is the largest single investment and the prerequisite for every UX item in Phase 4. Do it as an incremental strangler migration, not a rewrite: the app keeps working at every merge.

1. **Module extraction (L)** — split `App.tsx` into a real structure:
   ```
   src/
     api/            client.ts (fetch wrapper, 401 handling), generated types
     lib/            money.ts, dates.ts, storage.ts
     components/     Toast, Modal, ConfirmDelete, MultiSelectFilter, MetricTile, ...
     features/
       auth/         LoginScreen, SetupScreen, useSession
       accounts/     AccountsView, AccountForm, taxonomy
       imports/      ImportModal, SmartImport, HistoryImport
       review/       ReviewInbox, RuleManager, TransferReview
       transactions/ TransactionsTable, filters, CategoryPopup
       reports/      Spending, CashFlow, Income, NetWorth
       settings/     Backups, DangerZone, Password
     App.tsx         (~100 lines: providers + router + shell)
   ```
   Mechanical rule: any component > 300 lines gets split again.
2. **Server state via TanStack Query (M)** — replace `loadData()` with per-resource queries and **targeted invalidation** (confirming a transaction invalidates `review` + `transactions` + `dashboard`, not holdings). This kills FE-02, gives retry/stale handling for free, and provides `isLoading` flags Phase 4 consumes.
3. **Routing via React Router (M)** — `/overview`, `/accounts`, `/accounts/:id`, `/review`, `/reports/:tab`, `/settings`; filter state encoded in search params so filtered views are shareable/restorable (feeds UX-09). Preserve the sidebar-width and widget prefs in localStorage as today.
4. **Backend pagination lands together (M)** — implement `limit/offset` (+ existing filters) on `/api/transactions` and `/api/review`, cursor optional later; frontend table switches from slice-based "load more" to query-driven pages. Add the ARCH-02 indexes in the same PR (they make pagination fast).
5. **Generated API types (S)** — `openapi-typescript` from FastAPI's schema in a `pnpm gen:api` script; delete the hand-written payload types (FE-08).
6. **Error boundary + 401 interceptor (S)** — top-level boundary with a "something broke, reload / copy error" card (FE-06); the API client dispatches a session-expired event on 401 (FE-05/SEC-03 UI half).
7. **Escape-hatch consistency (S)** — one `Modal` primitive with focus trap, `aria-modal`, Escape-to-close, and focus return; migrate the import modal, delete confirms, and category popup onto it (foundation for UX-06).

**Definition of done:** no file over ~400 lines; every view has a URL; mutations invalidate only affected queries; typecheck passes with generated API types; Lighthouse a11y baseline recorded for Phase 4 comparison.

### Phase 4 — UX/UI Improvement Pass (target: 1–2 weeks, after Phase 3)

1. ✅ **Auth screens (S)** — wrap in `<form onSubmit>`, Enter submits, `autoComplete="current-password"`/`"new-password"`, `<label>`s, error text tied via `aria-describedby`, submit disabled while pending (UX-01).
2. ◐ **Logout + session UX (S)** — *(logout shipped; idle-expiry banner remains)* — logout in the sidebar footer; idle-expiry banner with one-click re-login preserving the current route (UX-02/05).
3. ✅ **Toast system (S)** — auto-dismiss (5 s) with pause-on-hover, close button, stacked region, `role="status"`/`aria-live="polite"` (UX-03).
4. **Loading & empty states (M)** — skeletons for tables/tiles from TanStack `isLoading`; distinct empty-state copy with a call-to-action ("Import your first CSV") vs. loading shimmer (UX-04, UX-11 seed).
5. **Accessibility sweep (M)** — labels on all inputs; `aria-label` on icon-only buttons; `:focus-visible` ring token applied globally; keyboard-reachable table row actions; `prefers-reduced-motion` guard on transitions; patterned/labelled bars in reports so color isn't the only channel (UX-06). Target: Lighthouse a11y ≥ 95 on all views.
6. **Rules & categories management (M)** — Rules screen: edit match text/category/type/priority, delete rule, dry-run preview of "would match N transactions" before apply; scope selector defaults to unreviewed; since bulk apply confirms matches by design, the dry-run preview is the safety net. Categories: delete-with-reassign flow, merge two categories (ARCH-07/UX-08). Requires small new backend endpoints (`PATCH/DELETE /api/rules/{id}`, `DELETE /api/categories/{id}?reassign_to=`).
7. **Duplicate review UI (M)** — for `possible_duplicate` items, show the matched existing transaction side-by-side (uses Phase 1 item 7) with "keep both / this is a duplicate" actions.
8. **Splits & void UI (M)** — split editor (amounts must sum, live remainder indicator) and a void action with visual strikethrough; both endpoints already exist.
9. **Import flow polish (M)** — drag-and-drop zone, file size/row count shown, preview shows "25 of N rows", post-commit summary links to the batch report incl. warnings; snapshot-date field for brokerage files (from Phase 1 item 2) (UX-10).
10. **Global transaction search (M)** — description/note substring search wired to the paginated endpoint; search box in the header, `/` keyboard shortcut (UX-09).
11. **First-run onboarding (S)** — dismissible 3-step checklist mirroring `workflow.md` (UX-11).

**Definition of done:** keyboard-only walkthrough of login → import → review → report succeeds; a11y ≥ 95; no dead-end object (rule, category, duplicate, split) remains unmanageable from the UI.

### Phase 5 — True Net Worth & Reporting Depth (target: 1–2 weeks)

1. **Cash balances (M)** — derive checking/savings balances from the latest `running_balance_cents` per account (data already imported), with a manual balance-override entry (`AccountBalanceSnapshot` table) for accounts without running balances (credit cards, cash). 
2. **Real net worth (M)** — net worth = investment snapshots + cash balances − credit-card balances, as a dated timeseries table (assets/liabilities split). Rename `net_worth_snapshot_cents` misuse; dashboard tile shows true net worth with an info tooltip on data freshness per account (ARCH-10).
3. **Date-scoped reports in SQL (M)** — move cash-flow/spending aggregation into SQL with `start/end` params (ARCH-08); the period chips drive queries instead of client-side re-filtering; Spending gains month-over-month comparison and per-category drill-down to the filtered transaction list (routing from Phase 3 makes this a link).
4. **Security price refresh (S–M)** — `SecurityPrice` exists with `source="manual"`; add a manual price-entry UI now; defer any online quote fetching (privacy tradeoff — document the decision either way).
5. **Budgets (L, optional this phase)** — per-category monthly targets vs. actuals; the fixed-category design makes this cheap. Ship as a dashboard widget + report tab.

### Phase 6 — Import Robustness & Real Presets (target: 2 weeks)

1. **Make presets real (L)** — a preset = stored column mapping (header signature → field roles, date format, sign convention, skip rules), exactly as `preset-format.md` envisions. Build a mapping UI shown when detection fails ("map your columns"), save as preset, auto-apply on matching header signatures. The five hardcoded formats become built-in presets, ending the vestigial state (ARCH-06).
2. **Format coverage (M)** — XLSX for transaction imports (already supported for history), OFX/QFX parsing (most US banks export it and it's less ambiguous than CSV).
3. **Import batch management (M)** — batches list in Settings with per-batch **undo** (delete this batch's transactions/holdings if none were manually edited; warn otherwise). This is the single best safety net for import mistakes.
4. **Sample fixture library (S)** — populate `samples/` with redacted golden files per preset; wire them into parametrized tests (TEST-02) so bank format drift breaks CI, not the user's ledger.

### Phase 7 — Quality Infrastructure (starts week 1, runs throughout)

1. **CI on GitHub Actions (S, week 1)** — jobs: backend pytest, ruff + mypy, frontend `tsc --noEmit` + eslint + `vite build`. Branch protection: PRs must pass, matching `collaboration.md`'s stated rules (TEST-01/TOOL-01).
2. **Alembic migrations (M, week 1–2)** — baseline the current schema; all Phase 1+ schema changes go through it; delete the ad-hoc ALTER logic (ARCH-01).
3. **API test suite (M, incremental)** — FastAPI `TestClient`/httpx tests over a temp SQLite DB covering: setup/login/CSRF, import commit ×2 (dedupe), rules apply scopes, transfer confirm/reject, backup/restore, app-data round-trip. Every Phase 0/1 bug gets a regression test as it's fixed.
4. **Frontend tests (M, after Phase 3)** — Vitest + Testing Library for money/date/filter utils and key components; one Playwright smoke: login → import sample CSV → confirm a transaction → see it in reports.
5. **Deprecation cleanup (S)** — `datetime.now(timezone.utc)` helper, lifespan handler (ARCH-05); ruff rules to prevent regressions.
6. **Docs truth pass (S, per-PR)** — update `workflow.md`/`preset-format.md`/`threat-model.md` in the same PR as each behavior change; add `docs/architecture.md` describing the post-Phase-3 frontend layout.

---

## 5. Post-Remediation Feature Roadmap

Ordered by leverage once the foundation above exists; aligned with the README's stated product direction.

| Horizon | Feature | Notes |
|---|---|---|
| Near | **Budgets & category targets** | Phase 5 item; fixed categories make this cheap and high-value. |
| Near | **Import undo / batch rollback** | Phase 6 item; biggest trust-builder for the import-centric workflow. |
| Near | **Encrypted-at-rest DB (SQLCipher)** | Completes the threat model's #1 stated gap; spiked in Phase 2. |
| Mid | **Secure mobile/self-hosted access** | Tailscale (or WireGuard) + HTTPS + the responsive work UX-07 defers; re-auth (Phase 2) becomes essential here. Session cookie flips to `secure=True` behind TLS. |
| Mid | **Recurring-transaction detection** | Same-payee cadence detection → "upcoming bills" widget; pure read-model, no schema risk. |
| Mid | **Multi-currency** | `currency` fields already exist; needs FX-rate entry (manual first, consistent with the privacy posture). |
| Later | **Attachment support** | Receipt images/PDFs on transactions; interacts with encryption strategy, so sequence after SQLCipher. |
| Later | **Investment lots & performance** | Cost basis, TWR — only worthwhile once snapshot integrity (Phase 1) has been stable for a while. |
| Explicitly not now | Bank-sync aggregators (Plaid etc.) | Contradicts the local-first privacy thesis; CSV/OFX + presets is the moat. Revisit only with a self-hosted bridge. |

---

## 6. Suggested Sequence & Effort Summary

| Phase | Duration | Can parallelize with |
|---|---|---|
| 0 — Hotfixes | 1–2 days | 7 (CI setup) |
| 1 — Data integrity | 1 week | 2 (security), 7 |
| 2 — Security hardening | 1 week | 1, 7 |
| 3 — Frontend re-architecture | 2–3 weeks | 7 (backend pagination lands here) |
| 4 — UX/UI pass | 1–2 weeks | 5 (backend reporting) |
| 5 — Net worth & reports | 1–2 weeks | 4 |
| 6 — Presets & import robustness | 2 weeks | — |
| **Total** | **~8–10 weeks** for two part-time collaborators | |

**Ground rules for the whole effort** (derived from what let the current bugs through):

1. Every bug fix ships with a regression test in the same PR — no exceptions.
2. Any behavior described in `docs/` is treated as a contract; changing either side requires changing both in one PR.
3. No new endpoint without an API test; no new schema change outside Alembic.
4. Frontend components have a 300-line ceiling; `App.tsx` never grows again.
5. Personal data (names, machine paths) never appears in source — config or env only. Add a pre-commit grep for the patterns that slipped through this time.

---

## Appendix A — Issue Index by File

| File | Issues |
|---|---|
| `backend/app/services/importers.py` | BUG-01 (L793 NameError), BUG-02, BUG-03, BUG-04, BUG-07a, SEC-07, ARCH-06 |
| `backend/app/main.py` | BUG-05, SEC-01, SEC-04, SEC-06, ARCH-03, ARCH-04, ARCH-07, ARCH-09 |
| `backend/app/services/backups.py` | BUG-09, SEC-01 |
| `backend/app/services/reporting.py` | BUG-08, ARCH-08, ARCH-10 |
| `backend/app/security.py` | SEC-02, SEC-03, SEC-05 |
| `backend/app/bootstrap.py` | ARCH-01, ARCH-05 |
| `backend/app/models.py` | ARCH-02, ARCH-04 |
| `backend/app/schemas.py` | ARCH-03 (dead `TransactionFilter`), ARCH-04 |
| `frontend/src/App.tsx` | BUG-06 (fixed), FE-01…FE-08, UX-01…UX-11 |
| `frontend/src/styles.css` | UX-06 (focus styles), UX-07 (2 media queries) |
| `scripts/restart.ps1` | BUG-07b |
| `backend/tests/` | TEST-01 (no API tests; `commit_import` dedupe untested) |
| `samples/` | TEST-02 (empty fixture library) |
| `docs/workflow.md`, `docs/preset-format.md` | DOC-01 |
