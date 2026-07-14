# Changelog

## Phased game-plan implementation — July 13, 2026

- Phase 0 gates and hygiene: the Import Inbox now defaults outside the repository at `~/PrivateFinance/import-inbox`; both `PF_IMPORT_INBOX` and the older `PF_IMPORT_INBOX_DIR` override are supported; package stores, databases, logs, pytest temp data, and `backend/data/` are ignored; Git history was audited without finding committed statement/data files; and the pre-merge pytest plus production-build gate is documented.
- Phase 0 frontend shell: API access and route exports were extracted from `App.tsx`, feature/shared-component directories were established, and Vitest coverage now protects transaction-filter URL round-tripping.
- Phase 1 sign architecture: per-account/preset sign profiles are persisted, journaled, undoable, and preserved across account merges. Credit-card and payroll plausibility checks prompt on contradictory files without silently changing signs, saved choices apply automatically, and later anomalies remain visible in Import Review.
- Import Review and sign prompting now live under `features/imports/`, reducing `App.tsx` while establishing the strangler pattern for later phases. The canonical sign contract and cleanup guidance are documented in `docs/amount-signs.md`.
- Phase 2 duplicate review: Review now shows candidate/original transactions side by side with differing account, reference, date, amount, description, category, notes, labels, and import-source fields highlighted. Remove-new, keep-both, replace-old, and bulk exact-match resolution are journaled as one undoable operation; replace-old preserves user categories, notes, labels, and splits.
- Duplicate and transfer review moved into `features/review/`; `App.tsx` is 5,509 lines, down from 5,528 at the end of Phase 1 and 5,638 at the start of the phased plan.
- Phase 3 transfer hardening: confirmed transactions can now be matched after both sides arrive, brokerage and retirement ACH transfers use a seven-day window, and confirmed credit-card payment links power per-card payment verification with warnings for stale unmatched payments.
- Phase 3 account balancing: imported running balances create statement checkpoints automatically, existing running balances are backfilled at startup, and manual statement balances are journaled and undoable. Account pages show reconciled/off-by status, an exact investigation date range, and card-payment verification. Checkpoints survive account merges and are covered by account deletion/undo. The account page, reconciliation badge, and payment verification panel live under `features/`; `App.tsx` is 5,506 lines.
- Import compatibility: compact brokerage position exports with report metadata above a `Symbol / Qty / Price / Market Value` header are now detected automatically. Position and cash rows import as holdings, summary totals are excluded, and the snapshot date is read from the export filename.
- Review rules now support categoryless Card payment and Transfer classifications. Single and bulk confirmation no longer require a category for those types; saved rules can classify and confirm them without creating a spending category; and changing or confirming a transfer/payment clears any stale category to prevent payment double-counting. Existing rule tables are upgraded in place without losing saved rules.
- Phase 5 net-worth data management: acquisition date, quantity, and cost basis now live in journaled `holding_lots` records instead of daily market-value snapshots. Fidelity-compatible exports populate lots when acquisition/basis columns are present, refreshed imports replace only imported lots, and manual lots remain intact. Holdings show aggregate basis, unrealized gain/loss, and oldest-lot age. A shared canonical-sign manual transaction form is available from account pages and Net Worth for asset accounts; both lot and transaction creation support Activity undo. `HoldingsPanel`, `ManualTransactionForm`, and delete confirmation are extracted components, reducing `App.tsx` to 5,390 lines.

## Remediation pass — July 2026

IDs reference `private-finance-evaluation-and-plan.md`.

### Fixed

- Raw CSV transaction dedupe no longer depends on a mutable internal account ID. New normalized fingerprints are account-independent; reliable Bank of America and Venmo references take precedence; matching reference/date/amount rows are skipped even when descriptions change; conflicting reference details are linked and sent to review; and ordinary CSV fingerprints are reconciled during account merges. Duplicate warnings now count only active rows. Categorized-history importing is intentionally unchanged.
- Categorized-history credit-card and Venmo amounts now normalize from the legacy Excel convention (positive charges, negative refunds) into one ledger convention (negative charges, positive refunds). A preview-first, journaled maintenance action repairs legacy imports, including soft-deleted rows, dependent splits/allocations, and Venmo's account type with one Undo operation. Its preview shows each historical cutoff and later direct-CSV range, leaves direct imports unchanged, and warns about date overlap, repeated direct-import references, or likely duplicate account aliases. Future history imports conservatively match existing accounts by institution, last four, and safe label aliases to avoid creating those duplicate account records.
- Deleted-transaction Activity details now show a readable Active → Moved to Trash timestamp instead of blank `deleted_at` values; new deletions also journal the exact deletion timestamp.
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

- Import Inbox discovery is user-initiated. The app no longer scans the folder on startup or every 30 seconds; files are searched and staged only after the user selects **Scan inbox**.
- Applying a saved rule to existing transactions confirms them by design (requirement changed; `docs/workflow.md` updated to match). Import-time rule matches now also carry the rule's suggested transaction type and remain in review as `suggested`.

### Added

- Import Inbox scanning now includes account-specific subfolders and uses the relative folder path for matching, allowing generic filenames such as `stmt.csv` to route reliably by a folder's institution/account last four. Manual import preview can reverse a detected sign convention and shows the interpreted transaction type before staging.
- Completed the remaining user-facing B/C/D/E Tier 1 work: manual uploads now enter the same review inbox as folder-scanned files; the user explicitly starts each inbox scan; unknown CSV layouts can be mapped once and remembered by the browser; spending has a drag-selectable stacked monthly comparison; category parents include their child transactions; transaction tags, bulk date/label edits, and backend-powered select-all are supported; and Trash automatically purges items after the configured retention period (90 days by default).
- Fixed Import Inbox discard and permanent single-transaction deletion responses that could fail after the requested change had already succeeded.
- Overview now owns the Cash Flow, Spending, Income, and Net Worth analysis tabs; the duplicate Reports navigation destination was removed and old `/reports` links resolve to Overview. The analysis toolbar stays visible while scrolling, and Overview cards are limited to high-level account, cash-flow, and spending context instead of repeating review/import work or duplicating cards inside dedicated tabs.
- Net Worth now uses a context-specific asset-change drawer that ranks checking, savings, brokerage, and other accounts by their contribution to a selected range. The selected gain/date/high/low summary sits above a zero-based, multi-tick chart. Spending categories and their peek transactions are ranked by largest amount, include relative-share comparisons, and use the app's blue palette.
- Completed Problem D dashboard details: manual per-account net-worth balances are journaled and undoable, chart range selections have adjustable edge handles, account rows include six-month sparklines, and reporting-date filters preserve split and monthly-allocation spending semantics.
- Completed Problem C drill-down coverage: canonical category/account/time-series aggregation endpoints share the transaction predicate, dashboard/report values use those aggregates, transaction-type filters round-trip in URLs, and spending, income, and cash-flow surfaces use a reusable filtered transaction peek with an exact full-ledger handoff.
- Completed Problem B mutation coverage for ordinary finance changes: mixed-entity Activity operations and undo now cover accounts, categories, rules, splits, allocations, transfers, holdings, app-data imports, and categorized-history imports. Bulk review/rule actions are journaled as one user action, and related editing screens share selection, bulk-action, and undo-toast behavior.
- Problem B/C/D recovery and drill-down polish: conflict-aware operation undo/redo APIs, row-level Activity details, 10-second undo actions for bulk edits/imports/deletes/restores, a recoverable transaction Trash with explicit delete-forever confirmation, and a net-worth transaction peek drawer that preserves dashboard context.
- Problem D foundation: durable per-account net-worth snapshots populated from imported running balances and brokerage positions, startup backfill for existing data, forward/backward balance reconstruction, day/week/month series and range-stat APIs, and an interactive net-worth chart with period controls, hover details, drag-to-compare statistics, and transaction drill-through.
- Problem E Tier 1 foundation: a configurable private Import Inbox with manual scanning, exact and semantic SHA-256 deduplication (independent of filename suffixes and harmless CSV formatting), account/preset matching, staged previews, confirm/discard review, unchanged source files, and one mutation-journal operation per confirmed import.
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

- The backend suite passes (`154 passed`). The frontend passes TypeScript checking, ten Vitest tests, and the full production Vite build (verified outside the desktop filesystem restriction used by esbuild).
