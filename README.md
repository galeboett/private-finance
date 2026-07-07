# private-finance

# Secure Local-First Personal Finance System

## Summary
Build a **single-user, Windows-first, local web app** that replaces the Excel workflow with deterministic imports, staging, deduplication, rule-based cleanup, and a **human-confirmed review queue**. The system stores all financial data locally, supports clean CSV/XLSX import and export, unifies bank and credit card transactions first, and adds investment snapshots plus net-worth views next. Mobile access remains a later self-hosted option, not part of the critical first release.

## Key Changes

### Architecture
- Backend: `FastAPI` with local `SQLite` in WAL mode.
- Frontend: local-first React web UI with a calm, dashboard-first finance design.
- Storage: no external aggregators, no telemetry, no cloud data storage.

### Canonical Data Model
- Core tables: `institutions`, `accounts`, `import_presets`, `import_batches`, `staging_rows`, `transactions`, `categories`, `category_rules`, `transaction_splits`, `holding_snapshots`, `audit_events`.
- `transactions` include `account_id`, `date`, `posted_date`, `amount`, `raw_description`, `normalized_payee`, `transaction_type`, `category_id`, `review_status`, `source_hash`, `running_balance`, `import_batch_id`.
- `holding_snapshots` store dated positions and balances for brokerage and retirement accounts.
- `running_balance` is optional and used when provided by bank exports.

### Import Preset System
- Presets are attached to accounts, not institutions.
- Each preset defines header detection, skipped rows, footer filters, column mappings, date parsing, amount parsing, sign conventions, optional running-balance parsing, and row classification.
- Preview-before-commit is required for new formats.
- Support the sample families already shared:
  - card export with `Posted Date/Reference Number/Payee`
  - card export with `Transaction Date/Post Date/Description`
  - checking export with summary rows plus running balance
  - brokerage position exports with totals/footer text and multi-account rows

### Review and Categorization Workflow
- Normalize first, determine transaction type second, assign category third.
- Default transaction types: `expense`, `income`, `transfer`, `credit_card_payment`, `refund`, `investment_flow`, `balance_marker`, `adjustment`.
- New or ambiguous rows go to `needs_review`.
- Manual corrections can be saved as merchant or description rules for future suggestions.
- Transfers and card payments are excluded from spending totals.

### Fixed Spending Categories
Seed the app with these flat expense categories:
- `groceries`
- `rent`
- `household`
- `restaurants`
- `auto_transport`
- `travel`
- `entertainment`
- `gift`
- `moving`
- `shopping`
- `utilities`
- `health_fitness`
- `work`

These are expense-only categories. Income, transfers, refunds, and investment flows are typed separately rather than forced into spending buckets.

### Product Surfaces
- Home dashboard: review inbox, month-to-date spend, cash-flow summary, unusual-spend alerts, recurring/subscription candidates, net-worth summary.
- Credit cards: transaction review, category trends, recurring charge detection, unusual spending flags.
- Bank accounts: consolidated cash-flow, transfer-aware views, account balance verification.
- Investments: imported holdings snapshots, allocation by asset class/account, performance-over-time from imported values.
- Export: clean transaction ledger CSV and spreadsheet-friendly summary exports.

### Security Baseline
- Local SQLite on encrypted disk.
- Local authentication with strong password hashing.
- No bank credentials stored; imports are manual.
- Immutable audit trail for imports and manual edits.
- Later remote access only through private self-hosted networking with authentication.

## Public Interfaces / Types

### Import Endpoints
- `POST /imports/preview`
- `POST /imports/commit`
- `GET /imports/:id/report`
- `POST /import-presets`

### Ledger Endpoints
- `GET /transactions`
- `PATCH /transactions/:id`
- `POST /transactions/bulk-review`
- `POST /rules`
- `CRUD /accounts`

### Analytics / Export Endpoints
- `GET /dashboard/summary`
- `GET /cash-flow`
- `GET /net-worth/timeseries`
- `GET /investments/allocation`
- `GET /exports/transactions.csv`
- `GET /exports/summary.xlsx`

## Test Plan

### Import Parsing
- Checking CSV with summary header plus ledger rows parses only real ledger rows into transactions.
- Beginning/ending balance and totals rows are captured as metadata or ignored, not counted as spending.
- Each shared card/brokerage format normalizes correctly into the canonical schema.
- Multi-account brokerage exports split holdings into the correct accounts.

### Dedupe and Reconciliation
- Re-importing the same file does not duplicate rows.
- Overlapping statement periods dedupe correctly via canonical hash.
- Running balances are retained for audit and can flag parse errors.

### Review and Categorization
- Unknown merchants land in review.
- Confirmed manual corrections can become reusable rules.
- Payments and transfers are excluded from expense summaries.
- Refunds do not inflate income.
- Transactions can be assigned to the fixed spending categories listed above.

### Reporting
- Cash-flow aggregates across multiple bank accounts with different file formats.
- Category summaries match only expense-type transactions.
- Net-worth totals combine cash, liabilities, and investment snapshots consistently.
- Exports are clean and round-trip well into spreadsheets.

### Security
- Auth is required before viewing ledger data.
- No outbound telemetry or external sync is present.
- Audit logs capture imports and manual edits.

## Assumptions and Defaults
- Categories are flat in v1, not nested.
- The listed categories are the fixed initial expense taxonomy.
- Non-expense flows such as salary, transfers, credit-card payments, and investment movements are represented by transaction type rather than spending category.
- The first release prioritizes transactions, review workflow, cash flow, and exports before deeper investment analytics.
- Mobile access remains outside the initial build and is added after the desktop workflow is trusted.
