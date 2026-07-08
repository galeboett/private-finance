# private-finance

# Secure Local-First Personal Finance System — Plan v2

## Summary
Build a **single-user, Windows-first, local web app** that replaces the Excel workflow with deterministic imports, staging, deduplication, rule-based cleanup, and a **human-confirmed review queue**. The system stores all financial data locally, supports clean CSV/XLSX import and export, unifies bank and credit card transactions first, and adds investment snapshots plus net-worth views next. Mobile access remains a later self-hosted option, not part of the critical first release.

**v2 changes:** hardens the localhost web attack surface (CSRF/DNS rebinding), specifies auth and encryption concretely, fixes dedupe to survive identical legitimate transactions and reformatted re-exports, mandates integer-cents money handling, designs transfer pairing and refund semantics, resolves the splits/category dual-source-of-truth, adds backups, and rescopes investment "performance" to value-over-time.

## Key Changes

### Architecture
- Backend: `FastAPI` with local `SQLite` in WAL mode.
- Frontend: local-first React web UI with a calm, dashboard-first finance design. Production build must bundle all assets locally — no CDN fonts, scripts, or analytics.
- Storage: no external aggregators, no telemetry, no cloud data storage.
- The server binds to `127.0.0.1` only. A startup check refuses to run if configured to bind any other interface in v1.

### Money and Currency Invariants
- All amounts are stored as **integer minor units** (cents) in SQLite `INTEGER` columns. Floats never appear in storage, arithmetic, or API payloads (APIs use integer cents or string decimals).
- Every monetary column carries a `currency` code (ISO 4217). v1 behavior is single-currency (USD) with the column present so multi-currency is a data migration, not a schema rewrite.
- Rounding rules for splits: split amounts must sum exactly to the parent transaction amount; the API rejects splits that don't.

### Canonical Data Model
- Core tables: `institutions`, `accounts`, `import_presets`, `import_batches`, `staging_rows`, `transactions`, `categories`, `category_rules`, `transaction_splits`, `transfer_links`, `holding_snapshots`, `audit_events`.
- `transactions` include `account_id`, `date`, `posted_date`, `amount` (integer cents), `currency`, `raw_description`, `normalized_payee`, `transaction_type`, `category_id`, `review_status`, `source_hash`, `source_reference` (bank-provided reference number when available), `source_ordinal` (occurrence index within the import file for identical rows), `running_balance`, `import_batch_id`, `status` (`active` | `voided`), `linked_transaction_id` (e.g., refund → original purchase).
- `transfer_links` pairs two transactions across accounts as one transfer (or card payment), with a `match_confidence` and `confirmed` flag.
- `holding_snapshots` store dated positions and balances for brokerage and retirement accounts: `snapshot_date`, `account_id`, `symbol`, `description`, `quantity`, `price` (integer minor units), `market_value` (integer cents), `asset_class`.
- `running_balance` is optional and used when provided by bank exports.
- Accounts are **archived**, never hard-deleted, once they have transactions.
- Transactions are **voided**, never hard-deleted; voided rows are excluded from reports but retained for audit.

### Deduplication and Reconciliation Design
- `source_hash` = hash of (account_id, raw date fields, raw amount, raw description, `source_reference` if present, `source_ordinal`). The ordinal counts identical raw rows within a single file, so N genuinely identical transactions on the same day all survive import.
- Exact-hash matches on re-import are skipped silently (idempotent re-import of the same file).
- **Near-matches** — same account, date, and amount but different raw description (banks reformat between pending/posted and between export formats) — are *not* silently deduped or duplicated. They land in the review queue as "possible duplicate" with both rows shown; the user confirms merge or keep-both.
- Hashes are computed from **raw source fields only**. Committed transactions are never mutated by later imports: user edits to `normalized_payee`, `category_id`, splits, or review status are permanent unless the user changes them.
- When `running_balance` is provided, the importer computes expected balances from transaction deltas and flags mismatches (parse error or missing rows) in the import report. Gaps between the last imported statement period and the new file's start are flagged as "possible missing statement."

### Import Preset System
- Presets are attached to accounts. **An account may have multiple presets** (formats change over time; CSV and XLSX exports coexist).
- Each preset defines a header signature (used for auto-detection), header detection, skipped rows, footer filters, column mappings, date parsing (explicit format string — no ambiguous MM/DD vs DD/MM guessing), amount parsing, sign conventions, optional running-balance parsing, and row classification.
- On import, the file's header is matched against the account's preset signatures; a confident match is preselected, otherwise the user chooses. Preview **hard-fails** if the file does not match the selected preset's signature — no partial or coerced parses.
- Preview-before-commit is required for new formats. Commit is transactional: a failed commit leaves no partial batch.
- Import files are untrusted input: enforce file-size limits, reject nested/oversized zip payloads inside XLSX (zip-bomb protection), parse XLSX with a library configured to ignore external references/entities, and treat all cell content as inert text.
- Date validation: reject or flag dates in the future or implausibly old for the account.
- Support the sample families already shared:
  - card export with `Posted Date/Reference Number/Payee`
  - card export with `Transaction Date/Post Date/Description`
  - checking export with summary rows plus running balance
  - brokerage position exports with totals/footer text and multi-account rows

### Review and Categorization Workflow
- Normalize first, determine transaction type second, assign category third.
- Default transaction types: `expense`, `income`, `transfer`, `credit_card_payment`, `refund`, `investment_flow`, `balance_marker`, `adjustment`.
- New or ambiguous rows go to `needs_review`. Possible duplicates and unpaired transfer candidates get their own review sub-states so the inbox distinguishes "categorize me" from "resolve me."
- Manual corrections can be saved as merchant or description rules for future **suggestions**. Rules never auto-commit; they pre-fill the review queue. Rules have an explicit priority order, most-specific-first; when multiple rules match, the highest-priority rule supplies the suggestion and the conflict is visible in the rule editor.
- **Transfer pairing:** transfers and card payments are detected by matching opposite-sign amounts across accounts within a configurable date window (default ±5 days). Matches above a confidence threshold are proposed as `transfer_links` for one-click confirmation; unmatched transfer-typed transactions surface in review as "unpaired transfer" so cash-flow never silently drifts.
- **Refund semantics:** refunds are typed `refund`, optionally linked to the original transaction via `linked_transaction_id`, carry the original's category, and **reduce that category's spend** in reporting. They never count as income.
- **Splits:** when a transaction has splits, the splits are the single source of truth for categorization; `transactions.category_id` is ignored for split transactions. All reporting reads through a resolver (SQL view) that yields per-category amounts uniformly for split and unsplit rows.
- Transfers and card payments are excluded from spending totals.

### Fixed Spending Categories
Seed the app with these flat expense categories:
- `groceries`, `rent`, `household`, `restaurants`, `auto_transport`, `travel`, `entertainment`, `gift`, `moving`, `shopping`, `utilities`, `health_fitness`, `work`

These are expense-only categories. Income, transfers, refunds, and investment flows are typed separately rather than forced into spending buckets. Categories are flat in v1; the schema includes a nullable `parent_id` so nesting later is a migration, not a redesign.

### Product Surfaces
- Home dashboard: review inbox (with duplicate/transfer resolution counts), month-to-date spend, cash-flow summary, unusual-spend alerts, recurring/subscription candidates, net-worth summary.
- Credit cards: transaction review, category trends, recurring charge detection, unusual spending flags.
- Bank accounts: consolidated cash-flow, transfer-aware views, account balance verification (computed vs. imported running balance).
- Investments: imported holdings snapshots, allocation by asset class/account, **value-over-time** from imported snapshots. (True return calculations are out of scope for v1 — see Non-Goals.)
- Export: clean transaction ledger CSV and spreadsheet-friendly summary exports.
- Recurring detection is a **derived view** in v1 (heuristics over the ledger: same payee, similar amount, regular cadence) with no dedicated tables; persisting confirmed subscriptions is v1.5.

### Security Baseline
**Threat model (v1):** protect a single user's financial data on one Windows machine against (a) malicious websites attacking the localhost API from the user's own browser, (b) malicious or malformed import files, (c) casual access to the machine or its disk, and (d) data loss. Out of scope for v1: multi-user isolation, remote network attackers (no remote access exists), and forensically motivated attackers with admin access to the running machine.

- **Local web hardening (required, v1):**
  - Bind `127.0.0.1` only.
  - Validate `Host` and `Origin` headers against an allowlist (`localhost`, `127.0.0.1` with the configured port); reject everything else to defeat DNS rebinding.
  - No wildcard CORS; the API sets no CORS headers beyond what the local UI origin needs.
  - Session cookie: `HttpOnly`, `SameSite=Strict`, session expiry with idle timeout; re-authentication required for export downloads and settings changes.
  - CSRF tokens on all mutating endpoints (defense in depth alongside SameSite).
- **Authentication:** local password, hashed with **Argon2id** (tuned parameters documented in config). Login rate limiting with lockout/backoff. No password recovery backdoor — document that a lost password means restoring from backup.
- **Encryption at rest:** application-layer database encryption via **SQLCipher** (covers the DB, WAL, and temp files) keyed from the user's password via KDF. First-run setup also checks for and recommends BitLocker, but the app does not rely on it.
- **Exports are sensitive artifacts:** the export UI states this; exports are written to a user-chosen location (never a predictable temp path), and XLSX exports offer optional password protection. Server-side temp files used during export generation are securely deleted.
- **CSV/formula-injection protection:** all exported CSV/XLSX cells whose content begins with `=`, `+`, `-`, or `@` are escaped (prefixed with `'` or safely quoted), since `raw_description` is attacker-influenced merchant data.
- No bank credentials stored; imports are manual.
- **Append-only audit trail:** `audit_events` records imports, edits, voids, rule changes, and auth events. The application has no update/delete path for audit rows, enforced with SQLite triggers that reject `UPDATE`/`DELETE` on the table.
- **Backups (v1, not later):** built-in encrypted backup export (single encrypted archive of the DB) with versioned retention and a **tested restore path** exercised in CI. Data loss is the dominant real-world risk for a local single-user app.
- **Dependencies:** pinned lockfiles for Python and JS; CI check that the built frontend makes zero external network requests.
- Logging: application logs exclude transaction contents and PII; the audit table is the record of change, logs are for diagnostics only.
- Later remote access only through private self-hosted networking (e.g., WireGuard/Tailscale) with authentication — explicitly a separate threat-model revision, not a config flag on v1.

## Public Interfaces / Types

### Import Endpoints
- `POST /imports/preview`
- `POST /imports/commit`
- `GET /imports/:id/report` — includes balance-mismatch and statement-gap flags
- `POST /import-presets` / `GET /accounts/:id/import-presets`

### Ledger Endpoints
- `GET /transactions` — cursor-paginated; filters: account, date range, type, category, review status, search on payee/description
- `PATCH /transactions/:id`
- `POST /transactions/:id/void`
- `POST /transactions/bulk-review`
- `POST /transactions/:id/splits`
- `POST /transfer-links` / `PATCH /transfer-links/:id` (confirm/reject)
- `POST /rules` / `GET /rules` / `PATCH /rules/:id` (priority reorder)
- Accounts: create, read, update, **archive** (no delete)

### Analytics / Export Endpoints
- `GET /dashboard/summary`
- `GET /cash-flow`
- `GET /net-worth/timeseries`
- `GET /investments/allocation`
- `GET /investments/value-timeseries`
- `GET /exports/transactions.csv`
- `GET /exports/summary.xlsx`
- `POST /backups` / `POST /backups/restore`

All mutating endpoints require a valid session and CSRF token.

## Test Plan

### Money Handling
- Property tests: no float ever enters storage or aggregation; sums of integer cents round-trip exactly through import → report → export.
- Split amounts must sum to the parent; API rejects mismatches.

### Import Parsing
- Checking CSV with summary header plus ledger rows parses only real ledger rows into transactions.
- Beginning/ending balance and totals rows are captured as metadata or ignored, not counted as spending.
- Each shared card/brokerage format normalizes correctly into the canonical schema (golden-file tests per preset).
- Multi-account brokerage exports split holdings into the correct accounts.
- Wrong-preset file fails preview loudly; oversized and malformed/zip-bomb XLSX files are rejected safely; commit is all-or-nothing.

### Dedupe and Reconciliation
- Re-importing the same file does not duplicate rows (idempotent).
- Two genuinely identical transactions in one file both survive (ordinal in hash).
- Overlapping statements with reformatted descriptions produce "possible duplicate" review items, not silent dupes or silent merges.
- Re-import never overwrites user edits to committed transactions.
- Computed vs. imported running balances match, or mismatches and statement gaps are flagged in the import report.

### Review and Categorization
- Unknown merchants land in review.
- Confirmed manual corrections can become reusable rules; rule priority resolves multi-match conflicts deterministically; rules suggest, never auto-commit.
- Transfer pairing links opposite-sign amounts across accounts within the window; unpaired transfers surface in review; payments and transfers are excluded from expense summaries.
- Refunds reduce the linked category's spend and never appear as income.
- Split transactions report through splits only; unsplit through `category_id`; the resolver view returns consistent totals either way.
- Transactions can be assigned to the fixed spending categories listed above.

### Reporting
- Cash-flow aggregates across multiple bank accounts with different file formats.
- Category summaries match only expense-type transactions, net of linked refunds.
- Net-worth totals combine cash, liabilities, and investment snapshots consistently.
- Voided transactions are excluded from all reports but present in audit.
- Exports are clean, formula-injection-escaped, and round-trip well into spreadsheets.

### Security
- Auth is required before any ledger data is returned; export endpoints require recent re-auth.
- Requests with foreign `Origin`/`Host` headers are rejected (DNS-rebinding/CSRF tests with simulated cross-origin requests).
- Mutating requests without CSRF tokens are rejected.
- Login rate limiting locks out after repeated failures.
- Database file, WAL, and temp files are unreadable without the key (SQLCipher).
- Exported CSV cells starting with `=`, `+`, `-`, `@` are escaped.
- Audit rows cannot be updated or deleted (trigger tests).
- Backup archive restores to a byte-identical, working database.
- No outbound telemetry or external requests from backend or built frontend (network-capture test in CI).

## Non-Goals for v1
- Multi-currency behavior (schema-ready only).
- True investment performance (TWR/IRR), cost basis, and tax lots — v1 shows value-over-time and allocation only, clearly labeled to avoid implying returns.
- Nested categories (schema-ready only).
- Remote/mobile access of any kind — requires its own threat-model revision.
- Automatic rule application without human confirmation.
- Bank connections/aggregators.

## Assumptions and Defaults
- Categories are flat in v1, not nested.
- The listed categories are the fixed initial expense taxonomy.
- Non-expense flows such as salary, transfers, credit-card payments, and investment movements are represented by transaction type rather than spending category.
- The first release prioritizes transactions, review workflow, cash flow, exports, and backups before deeper investment analytics.
- Single OS user on the machine; OS-level account separation is out of scope.
- Mobile access remains outside the initial build and is added after the desktop workflow is trusted.
