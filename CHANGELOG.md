# Changelog

## Remediation pass — July 2026

IDs reference `private-finance-evaluation-and-plan.md`.

### Fixed

- **BUG-01** — Re-importing a CSV that overlaps an earlier import crashed with a 500 (`NameError` in `commit_import`) and rolled the whole import back. Duplicates are now skipped and counted correctly. Regression test: `tests/test_import_commit.py::test_commit_import_skips_duplicates_on_reupload`.
- **BUG-02** — Re-importing a brokerage positions file double-counted net worth. Importing positions for an account/date now replaces that snapshot instead of appending to it.
- **BUG-03** — Brokerage snapshot dates were always recorded as "today". Dates are now parsed from the filename (Fidelity `Jul-04-2026` style, ISO, `MM-DD-YYYY`, `YYYYMMDD`); an explicit `snapshot_date` query parameter on `/api/imports/commit` overrides the filename; when neither is available the import warns and uses today.
- **BUG-04** — Categorized-history imports typed positive deposits into checking/savings as expenses, inflating spending totals. Deposits now default to `income` (with `refund` labels respected).
- **BUG-05** — `/api/imports/commit` did not enforce the file-size limit and non-UTF-8 uploads produced a 500. Size is now checked and undecodable files return a clear 400.
- **BUG-06** — Overview metric tiles silently switched data sources when a period's cash-flow total was exactly $0 (`||` fallback). The fallback now triggers only when cash-flow data is absent entirely.
- **BUG-07** — The Venmo importer hardcoded a personal name; it is now the `PF_VENMO_SELF_NAME` setting, with a neutral From→To fallback when unset. `scripts/restart.ps1` no longer hardcodes machine-specific tool paths; tools resolve from `PATH` with `PF_PYTHON` / `PF_PNPM` / `PF_NODE_DIR` overrides and an npm fallback.
- **BUG-09 / SEC-01** — Backups now use SQLite's online backup API (consistent while the app runs), are constrained to `data/backups/`, and restores validate the file, write an automatic `pre-restore-<timestamp>.sqlite3` safety copy, and dispose pooled connections before swapping the database.
- **SEC-05** — `verify_password` no longer swallows unexpected errors, and hashes are transparently upgraded on login when Argon2 parameters change.

### Changed (requirements update)

- Applying a saved rule to existing transactions confirms them by design (requirement changed; `docs/workflow.md` updated to match). Import-time rule matches now also carry the rule's suggested transaction type and remain in review as `suggested`.

### Added

- Problem C foundation: a canonical transaction-filter contract shared by the backend query builder and frontend URL codec, real app paths with browser back/forward support, bookmarkable transaction filters, and removable active-filter chips.
- Problem B foundation: operation and row-change journal tables, atomic before/after mutation recording for transaction edits, bulk edits, voids, and deletes, plus recoverable transaction soft deletion and one shared live-transaction query predicate.
- `POST /api/password` — change the local password (requires the current password; revokes all other sessions). **SEC-02 partial**
- `PATCH /api/rules/{id}` and `DELETE /api/rules/{id}` — rules are no longer permanent. **ARCH-07 partial**
- `GET /api/backups` — list existing backups and the backups folder.
- Absolute session lifetime (`PF_ABSOLUTE_SESSION_HOURS`, default 12 h) alongside the idle timeout; expired sessions are purged on login. **SEC-03 partial**
- Sign out button in the sidebar; login/setup are real forms (Enter submits, labeled fields, password-manager autocomplete). **UX-01/02**
- Toasts auto-dismiss, are manually dismissible, and announce via `aria-live`. **UX-03**
- Double-submit protection on import preview/commit, categorized-history import, and app-data restore. **FE-04 partial**
- Global `:focus-visible` outlines and `prefers-reduced-motion` support. **UX-06 partial**
- `duplicate_of_transaction_id` is now populated for possible duplicates and exposed by `/api/transactions` and `/api/review`.
- Transactions CSV export streams from memory and includes account, institution, posted date, category, and note columns. **SEC-06**
- Regression/unit test suites: `tests/test_import_commit.py`, `tests/test_backups.py`.

### Review pass (code review of this remediation)

- Backup and pre-restore safety-copy SQLite connections are now explicitly closed (`contextlib.closing`); `with sqlite3.connect(...)` only scopes transactions, so the previous code leaked file handles that could hold locks on Windows.
- `test_preview_venmo_ignores_crypto_summary_rows` now sets `venmo_self_name` like its sibling tests; it previously asserted self-name-aware phrasing without configuring the name and would have failed.
- Finding IDs above were updated to match the renumbered evaluation plan (the rule auto-confirm item was withdrawn per the requirements change, and the metric-tile fallback is now BUG-06).

### Notes for reviewers

- The backend test suite could not be executed in the authoring environment (no package installs available); all edits were verified by compilation and static analysis. Run `pytest` in `backend/` before merging.
- The frontend was syntax-checked with `tsc`; run `pnpm build` (or `npm run build`) to fully verify.
