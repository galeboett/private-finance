# Private-Finance — State-of-the-Project Critique & Game Plan
**Date:** July 13, 2026 · **Inputs:** `personal-finance-1.zip` (repo snapshot), `feature_requests_PF_7_13_26.docx`

---

# Part 1 — Where the Project Actually Stands

## What shipped since the last plan (credit where due)

The B/C/D/E-Tier-1 architecture landed substantially as designed, and in some places better:

- **Problem B (undo/journal):** `operations` + `operation_changes` tables, conflict-aware undo/redo, mixed-entity operations, Trash with retention purge, 10-second undo toasts. Imports, bulk edits, transfers, splits — all journaled. This is the strongest subsystem in the app.
- **Problem C (drill-down):** canonical filter contract shared by backend query builder and frontend URL codec (`transaction_filters.py` ↔ `lib/filters.ts`), aggregation endpoints sharing the same predicate, peek drawers, filter chips.
- **Problem D (dashboards):** per-account daily `net_worth_snapshots` with backfill and forward/backward reconstruction, range-stats API, drag-to-compare chart, asset-change drawer, sparklines.
- **Problem E Tier 1:** Import Inbox with SHA-256 exact + semantic dedupe, subfolder routing for generic filenames, staged review, one journal operation per confirmed import, and (a good judgment call) user-initiated scans instead of background polling.
- The review pass caught real defects (backup connection leaks, the Venmo test monkeypatch) and the sign-normalization cleanup tool for legacy history is preview-first and undoable — exactly the right shape.

## Critique — the three things I'd stop the line for

### 1. The frontend monolith got *worse*, and the plan said it wouldn't
`App.tsx` is now **5,638 lines** — up from 3,568 when the decomposition was declared a prerequisite ("Phase 3 target," §0.2 of the architecture plan). Every B/C/D/E feature was instead bolted into the monolith. The cost of the split grows with every merge, and the new feature list (dedupe review UI, refund matching, settings reorg, custom date pickers) is heavily frontend — building it in this file digs the hole faster than any future refactor can fill it. `main.py` has the same disease at 2,009 lines, though the backend at least has clean service extraction underneath it.

**Ruling:** no more net-additive PRs to `App.tsx`. Every feature below names the component files it must be built in, and the strangler rule is: *any screen a phase touches gets extracted in that phase.* No big-bang rewrite — but the line count must go down every sprint.

### 2. `pnpm build` has now been skipped across two review cycles
The changelog again says the Vite build "still needs to be run outside the desktop filesystem sandbox." This was the standing merge requirement last cycle too. TypeScript checking passing is not a build. A broken production bundle in a two-person self-hosted app means the other collaborator pulls and gets nothing.

**Ruling:** Phase 0 blocker. Run the build on a machine where esbuild works (or fix the sandbox path issue), and add a pre-merge checklist to `docs/workflow.md`: `pytest` green + `pnpm build` green, no exceptions. Note: this sandbox has no network access, so I could not run either suite here — this remains on you before merging anything.

### 3. Real financial data is inside the repo tree (privacy-first app, remember)
`backend/data/import-inbox/` in the zip contains **actual bank statement CSVs** (BoA, Citi, Venmo), account last-fours in folder names, screenshots of a brokerage transaction history, SQLite backups, and `server.out.log`/`server.err.log`. If `data/` isn't fully gitignored, this is one `git push` away from leaking; it also just leaked into a zip that left the machine. For an app whose entire reason to exist is privacy, repo hygiene is a product feature.

**Ruling:** Phase 0: confirm `.gitignore` covers `backend/data/`, `*.log`, `*.sqlite3`, `.pytest-tmp/`; run `git log --stat` to verify no statement files were ever committed; move the inbox default location *outside* the repo tree (it's configurable — change the default and document it).

## Secondary critiques

- **Sign conventions live in three uncoordinated code paths** — importer presets with a per-batch `reverse` escape hatch, the categorized-history `charges_positive`/`canonical` parameter, and the one-time history cleanup normalizer. Nothing *persists* a source's convention, which is exactly why the feature doc's section (a.1/a.3) reads confused: the system has an answer but no single contract, no memory, and no documentation. This is the root cause to fix, not another one-off toggle.
- **The dedupe backend outran its UI.** `duplicate_of_transaction_id` is populated and exposed by the API, but the frontend shows a status pill with no matched-original context and no Keep-both / Remove-duplicate verbs. Cheap, high-value gap.
- **`review_status` is doing too many jobs** (`needs_review`, `suggested`, `possible_duplicate`). Refund matching would make it worse. The `TransferLink` table is the right pattern — relationships as link tables, not statuses — and refunds should copy it.
- **Zero frontend tests.** 5,638 lines of behavior with no safety net makes the decomposition riskier than it needs to be. Even a handful of Vitest tests on `filters.ts` round-tripping and money formatting would help.

---

# Part 2 — Answers to the Direct Questions in the Feature Doc

## "How is the data interpreted now by the app?" (a.1.2)

There is one **canonical ledger convention**: *charges/outflows are negative; refunds, deposits, and income are positive* — for every account type. Everything at the edge normalizes into it:

1. **Raw CSV imports:** each institution preset (BoA, Citi, Venmo, generic) maps its native format into canonical signs at parse time. If a bank's file has the opposite convention, the review screen's "reverse detected signs" option flips it *for that batch only* (`ImportBatch.sign_convention = 'reverse'`).
2. **Categorized history import:** accepts your legacy Excel convention (`charges_positive`: positive = charge, negative = refund) and converts to canonical for spend accounts (credit cards, Venmo) at commit; checking/savings deposits type as income (the BUG-04 fix).
3. **Legacy data already in the ledger:** the "Normalize previously imported categorized history" maintenance action repairs pre-fix imports — preview-first, one undoable operation, covering soft-deleted rows, splits, and allocations.

So aggregation, budgets, and dashboards can trust one rule: negative sums are money out. If a category total looks inverted today, it's edge-normalization that misfired (wrong preset detection, or a file whose convention differed from its preset), not the reporting layer.

## "How should I navigate this nuance? What's the optimal way to clean the data?" (a.1.4)

**Cleanup (one-time):** run the existing normalize-history preview, review its cutoff/overlap warnings, commit, and spot-check three things per credit-card account: (1) a known purchase is negative, (2) a known refund is positive, (3) the category monthly totals match your Excel-era expectations. It's one undoable operation, so the risk is low. Where the preview flags repeated bank references, run those through the new Duplicate Review UI (Phase 2 below) rather than hand-editing.

**Going forward (structural):** stop making sign choice a per-batch memory test. Persist it per source — that's Phase 1's Import Sign Profile. The app should *detect, ask once, remember, and warn on anomaly* — never silently guess.

---

# Part 3 — The Game Plan

Phases are ordered by risk: data correctness → data relationships → UX. Each phase lists the frontend components it must extract from `App.tsx` (the strangler rule). Requirement IDs reference the feature doc.

## Phase 0 — Gates & Hygiene (do before anything merges) — ~1 day

1. Run `pnpm build` outside the sandbox; fix whatever breaks. Add the pytest + build checklist to `docs/workflow.md` and to the `post-merge` hook's documentation.
2. Verify `.gitignore` covers `backend/data/`, `*.sqlite3`, `*.log`, `.pytest-tmp/`, `.pnpm-store/`; audit git history for committed statements; relocate the default Import Inbox path outside the repo (e.g., `~/PrivateFinance/import-inbox`), keeping `PF_IMPORT_INBOX` override.
3. Scaffold the frontend decomposition shell only: `app/router.tsx` already effectively exists via URL views — add `features/` and `components/` directories, an `api/client.ts`, and a Vitest setup with tests for `filters.ts` round-tripping. Every later phase drops components into this shell.

## Phase 1 — Sign-Convention Architecture (a.1, a.3) — ~3–4 days

**Goal:** one contract, persisted per source, with detection and anomaly warnings.

**Schema:**
```sql
CREATE TABLE import_sign_profiles (
    id              INTEGER PRIMARY KEY,
    account_id      INTEGER NOT NULL REFERENCES accounts(id),
    preset_type     TEXT,                  -- NULL = applies to all presets for this account
    sign_convention TEXT NOT NULL,         -- 'canonical_as_detected' | 'reverse_detected'
    decided_by      TEXT NOT NULL,         -- 'user' | 'auto_detected'
    sample_note     TEXT,                  -- e.g. "Confirmed from Jul 2026 statement"
    updated_at      TEXT NOT NULL,
    UNIQUE (account_id, preset_type)
);
```

**Logic flow (import preview):**
1. Parse with preset → canonical candidate signs.
2. Look up profile for (account, preset). If found and `decided_by='user'`, apply silently; show a subtle "Using your saved sign convention" note with a change link.
3. If no profile: run **plausibility heuristics** — for a credit-card account, ≥85% of non-payment rows should be negative (charges) after normalization; for checking, payroll-like descriptions should be positive. If heuristics disagree with the preset's output, show a first-class prompt in the review screen: *"This file looks like charges are positive. Which is right?"* with two labeled example rows rendered under each choice.
4. User's answer writes the profile (`decided_by='user'`). Future imports from that source apply it automatically.
5. **Anomaly guard on every subsequent import:** if a batch's sign distribution contradicts its saved profile (e.g., a credit-card file suddenly 90% positive), don't auto-commit — flag the batch in review with the same two-example prompt. Banks do change export formats.
6. Journal profile creation/changes as operations (undoable, visible in Activity).

**Docs:** new `docs/amount-signs.md` — the canonical contract, per-edge normalization table, and the answers from Part 2. This ends the recurring confusion permanently.

**Frontend extraction:** `features/imports/SignConventionPrompt.tsx`, `features/imports/ImportReview.tsx` (move the existing review screen out of App.tsx).

**Tests:** heuristic thresholds, profile precedence (user > detected), anomaly-flag path, profile survival across account merges.

## Phase 2 — Duplicate Review UI (a.5) — ~2–3 days

Backend is ready; this is UI plus three verbs.

**API additions:**
```
GET  /api/duplicates/pending      → pairs: {candidate, original, diff_fields[]}
POST /api/duplicates/{txn_id}/resolve   { action: 'remove_new' | 'keep_both' | 'replace_old' }
```
`replace_old` = copy the new row's bank-sourced fields (date, amount, description, reference) onto the old row, preserve user-authored fields (category, notes, labels, splits), soft-delete the new row. Each resolution = one journaled operation (undoable), per the doc's requirement.

**UX:** a "Duplicates" section inside Review (badge count in nav). Each pair renders **side-by-side cards** — account, reference, date, amount, category, notes, import source — with differing fields highlighted. Three buttons, with "Remove new copy" visually recommended when all compared fields match exactly. Bulk affordance: "Resolve all exact matches" (one operation, one undo).

**Frontend extraction:** `features/review/DuplicateReview.tsx`, `features/review/TransactionCompareCard.tsx` (the compare card gets reused by refund matching in Phase 4).

## Phase 3 — Transfers & Account Balancing (a.6) — ~4–5 days

The matcher already handles any equal-and-opposite pair across accounts (checking→CC payment, savings→checking, brokerage→checking all work today). The real gaps are *verification* and *reconciliation*.

**3a. Transfer coverage hardening:** widen candidate generation to include settled (`confirmed`) transactions within the window, not only review-status rows — real transfers often import days apart and one side may already be confirmed. Add per-account-type windows (brokerage ACH: 7 days). Test each scenario from the doc explicitly (checking↔CC, savings↔checking, brokerage/retirement↔checking).

**3b. Reconciliation checkpoints (the "are my accounts balanced" feature):**
```sql
CREATE TABLE statement_checkpoints (
    id                      INTEGER PRIMARY KEY,
    account_id              INTEGER NOT NULL REFERENCES accounts(id),
    statement_date          TEXT NOT NULL,
    statement_balance_cents INTEGER NOT NULL,
    source                  TEXT NOT NULL,     -- 'import' | 'manual'
    UNIQUE (account_id, statement_date)
);
```
Populated automatically when a CSV carries a running balance (the running-balance logic already exists for sidebar balances) and manually via a small "Add statement balance" form on the account page. **Logic:** computed ledger balance as of `statement_date` vs `statement_balance_cents` → delta. Delta = 0 renders a "Reconciled ✓ through Jul 1" badge on the account page; nonzero renders "Off by $84.12 — investigate" which drill-downs (existing filter model) to transactions since the last reconciled checkpoint.

**3c. Payment verification view:** for each credit-card account, a "Payments" panel pairing CC payment credits with their checking-side debits via confirmed `TransferLink`s; unmatched payments older than the window surface as warnings. This directly answers "payments received match credit card balances."

**Frontend extraction:** `features/accounts/AccountPage.tsx`, `features/accounts/ReconciliationBadge.tsx`, `features/transfers/PaymentVerification.tsx`.

## Phase 4 — Expense ↔ Refund Matching (c) — ~4–5 days

Copy the transfer pattern: a link table + suggestion engine + review verbs. Do **not** overload `review_status`.

**Schema:**
```sql
CREATE TABLE refund_links (
    id                     INTEGER PRIMARY KEY,
    expense_transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    refund_transaction_id  INTEGER NOT NULL REFERENCES transactions(id),
    match_confidence       INTEGER NOT NULL,
    confirmed              INTEGER NOT NULL DEFAULT 0,
    created_at             TEXT NOT NULL,
    UNIQUE (refund_transaction_id)          -- a refund ties to one expense…
);                                           -- …but an expense may have many refunds (partials)
```
Validation: `sum(linked refunds) ≤ expense amount` (warn, don't block — price-adjustment credits can exceed in odd cases; require an explicit confirm).

**Suggestion engine** (`services/refunds.py`, mirrors `transfers.py`): candidates = refund-typed or positive rows on spend accounts; score on (same account strongly preferred, amount ≤ expense, merchant/description token overlap — Venmo counterpart name and note per the doc, date within 90 days after expense, exact-amount bonus). Suggestions journaled; confirm/dismiss verbs; every decision one undoable operation.

**UX:**
- **Review workflow (doc c.1):** refund rows in Review get a "Possible refund of: [expense card]" inline suggestion with Confirm / Not a match — reusing Phase 2's `TransactionCompareCard`.
- **Transaction detail:** a "Refunds" section on any expense listing linked refunds with dates/amounts and remaining net; a "Link a refund…" picker (searches candidate rows, filterable) for the manual path (doc c.3).
- **Ledger badges:** expenses with confirmed refunds show a small `↩ refunded $X` chip; filterable via a new `has_refund` facet in the canonical `TxnFilter` (extends URL codec + backend predicate together, per the shared-contract rule).
- **Reporting semantics decision (make it explicit):** spending totals continue to net refunds by sign — that's already true under the canonical convention. Refund links change *presentation* (which expense is offset), not totals. Document this in `docs/amount-signs.md` to preempt the next confusion.

**Frontend extraction:** `features/refunds/RefundSuggestions.tsx`, `features/refunds/RefundLinkPicker.tsx`.

## Phase 5 — Net Worth Data Management (a.4) — ~3 days

**5a. Acquisition date & cost basis.** Keep `holding_snapshots` as the market-value time series it is; add a separate lots table for basis (tax-lot semantics don't belong in daily snapshots):
```sql
CREATE TABLE holding_lots (
    id                INTEGER PRIMARY KEY,
    account_id        INTEGER NOT NULL REFERENCES accounts(id),
    symbol            TEXT NOT NULL,
    acquisition_date  TEXT NOT NULL,
    quantity_bp       INTEGER NOT NULL,
    cost_basis_cents  INTEGER NOT NULL,
    note              TEXT
);
```
Where brokerage exports include basis/acquisition columns (Fidelity's do), importers populate lots; otherwise manual entry. Holdings views gain unrealized gain/loss = market value − Σ basis, and lot age.

**5b. Manual transaction entry** (doc a.4.2): a single `ManualTransactionForm` component (date, account, amount with sign helper — "money out" / "money in" toggle writing canonical signs, category, description, labels) surfaced in **both** required places: an "Add transaction" button on account pages and on the Net Worth tab (there pre-filtered to asset accounts, alongside the existing manual balance entry). Backend: ensure the create endpoint journals as an operation (create path exists; verify coverage in `test_mutation_log.py`).

**Frontend extraction:** `features/transactions/ManualTransactionForm.tsx`, `features/networth/HoldingsPanel.tsx`.

## Phase 6 — UX Overhaul (b.1–b.3, a.2) — ~5–6 days

**6a. Settings information architecture (b.1).** The screenshot shows why it overwhelms: import workflows, one-time maintenance, categories, and backups share one scroll. Reorganize into a left-tabbed settings layout:
1. **Imports** — Inbox path + scan, manual upload, saved CSV mappings, sign profiles (from Phase 1)
2. **Accounts & Institutions** — manual accounts, merges, taxonomy
3. **Categories & Rules**
4. **Data** — backup/export/restore, Trash retention, and a collapsed **Maintenance** accordion holding the one-time tools (history normalization, cleanup previews) with "you rarely need these" framing
5. **Security** — password, sessions

Progressive disclosure rule: anything destructive or one-time starts collapsed. The categorized-history import block moves under Imports → "Legacy history" and collapses once a history import exists.

**6b. Left-nav single-account flattening (a.2).** Rendering rule in the sidebar taxonomy: if an institution group contains exactly one active account, render **one row** — `Bank ▸ Account (1016)  $8,504.56` — no expander, institution name inline, row links straight to the account. Multi-account institutions keep collapse behavior. Also suppress the redundant `$0.00`-under-`$0.00` double rows visible in the screenshot (show the balance once per row).

**6c. Summary header (b.2.1).** A sticky `FilterSummaryBar` at the top of the transactions/account views, computed from the existing aggregation endpoints with the live `TxnFilter` (guaranteeing it matches the table below): **Total in · Total out · Net · N transactions · Avg monthly spend** (avg = outflow ÷ distinct months in range). Clicking any stat opens the existing peek drawer.

**6d. Custom date ranges (b.2.2).** Presets become shortcuts that fill `dateFrom/dateTo` in the URL filter model; add a **Custom…** pill opening a dual-month range calendar (build it — no heavy dependency; ~150 lines) plus quick relative options ("Last 90 days", "Q2 2026"). Because everything writes through the canonical filter, drill-downs, chips, and bookmarks work unchanged.

**6e. Overview tab reorder (b.3).** `reportTabs` becomes **Overview · Net Worth · Spending · Cash Flow**. The Income tab is removed; its income-vs-expense content folds into Cash Flow (which already computes income series). Add a redirect so any bookmarked `?tab=Income` lands on Cash Flow.

**Frontend extraction:** this phase is the decomposition's main event — `features/settings/*` (5 tab components), `features/sidebar/AccountNav.tsx`, `components/FilterSummaryBar.tsx`, `components/DateRangePicker.tsx`, `features/overview/OverviewTabs.tsx`. Exit criterion: **App.tsx under 2,000 lines** by end of phase.

## Phase 7 — Split by Percentage (a.7, lowest priority) — ~1 day

Add a %/$ toggle to the split editor; percentages compute cents at save time (largest-remainder rounding so parts always sum exactly; store cents, never percentages, to keep the ledger integral). Answering the doc's question (a.7.2): **yes, expose it in the review page's split control too** — it's the same component after extraction, so it costs nothing; the common "split this Venmo charge 50/50" case happens during review, not after.

---

# Part 4 — Sequencing, Effort, and Risks

| Order | Phase | Est. effort | Depends on | Feature-doc IDs |
|---|---|---|---|---|
| 0 | Gates & hygiene | 1 day | — | (process) |
| 1 | Sign-convention architecture | 3–4 days | 0 | a.1, a.3 |
| 2 | Duplicate review UI | 2–3 days | 0 | a.5 |
| 3 | Transfers & balancing | 4–5 days | 1 (trustworthy signs) | a.6 |
| 4 | Refund matching | 4–5 days | 2 (compare card), 1 | c.1–c.3 |
| 5 | Net worth data mgmt | 3 days | 0 | a.4 |
| 6 | UX overhaul | 5–6 days | benefits from 1–5 landing behind it | b.1–b.3, a.2 |
| 7 | Percentage splits | 1 day | 6 (extracted split editor) | a.7 |

Phases 2 and 5 are independent and can interleave if you want visible wins early; Phase 6 is deliberately late so the settings reorg includes the new sign-profile and maintenance surfaces rather than being reorganized twice.

**Risks to watch:**
- *Sign-profile false confidence:* heuristics must never silently flip a batch — they only prompt or warn. The user's explicit answer is the only thing that writes a profile.
- *Reconciliation noise:* pending transactions and CC statement-vs-current balance semantics can make deltas look scary. V1 compares only against imported running balances at the statement date; label deltas as "since last reconciled" rather than "error."
- *Refund link ↔ transfer link collisions:* a Venmo payback could plausibly match both engines. Rule: confirmed transfer links exclude those rows from refund candidacy (transfers win), and vice versa.
- *Decomposition regressions:* extraction PRs must be behavior-neutral and reviewed as pure moves; the Vitest suite from Phase 0 plus the 112 backend tests are the net.

**Standing merge gate, restated:** `pytest` green, `pnpm build` green, CHANGELOG + evaluation-plan status columns updated, App.tsx line count not increased. Neither test suite could be executed in this analysis environment (no network for dependencies), so both remain on you before any of this merges.
