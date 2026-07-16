# Private-Finance — Implementation Plan, Iteration 3
**Date:** July 14, 2026 · **Inputs:** `personal-finance-2.zip`, `PF_feature_requests_7_14_26.md` + 5 screenshots
**Supersedes:** continues `pf-critique-and-gameplan-7-13-26.md` (Phases 0–5 verified complete; old Phases 6–7 remain open and are renumbered here)

---

# Part 1 — Verification of the Delivered Work

Confirmed present and matching the prior plan: `sign_profiles.py` + prompt/anomaly flow, `duplicates.py` + side-by-side review with three verbs, `reconciliation.py` with auto/manual statement checkpoints and payment verification, `refunds.py` with partial refunds, exclusivity vs transfers, and performance hardening, `holding_lots` with Fidelity basis ingestion, the shared manual transaction form, `docs/amount-signs.md`, Vitest coverage, the inbox relocated outside the repo, and a proper `.gitignore`. Test files grew from 19 → 24. Good discipline: the changelog now tracks `App.tsx` line count per phase.

**Still open from the last plan:**
- **Old Phase 6 (UX overhaul)** — settings IA, left-nav flattening, summary header, custom date ranges, tab reorder. Not started; `App.tsx` is **5,378 lines** (down only 260 from 5,638). The <2,000-line exit criterion stands, and — as predicted — the monolith is now *causing* user-visible bugs (see the cross-view staleness item below).
- **Old Phase 7 (percentage splits).**
- The two SQLite backups and `server.err.log`/`server.out.log` still ride along in the zip. They're gitignored (so the repo is safe), but they contain real data and keep leaving the machine inside archives. Consider excluding `backend/data/` and `*.log` when you build a share zip.
- Neither `pytest` nor `pnpm build` could be executed in this analysis environment (no network; the bundled venv is Windows-only). The standing merge gate remains on you.

---

# Part 2 — Answers to the Direct Questions

## "How are refunds interpreted and translated to other categories?" (Data flow)

Under the canonical sign contract, a refund is simply a **positive row on a spend account**. Today the data flow is:
1. When a refund is **confirmed against an expense** (Phase 4 links), it inherits that expense's `category_id` (`refunds.py:304`) — so it nets against that category's spend in any aggregation that sums signed amounts per category.
2. When a refund is **unlinked**, it has no category (`No category`), so category dashboards on the Overview page *never see it* — the refund reduces account balances and net cash flow but not the category it logically offsets. That's the gap you're observing.

Phase 10 below closes it: unlinked refunds become directly categorizable (ledger, review, and rules), refund suggestions are surfaced at categorization time, and an "Uncategorized refunds" nudge keeps them from silently leaking out of spending analytics. Reporting semantics stay signed-sum netting — no shadow math.

## "How can the user conveniently get statement balances in without connectors?" (Privacy & convenience)

Ranked by convenience-per-privacy, all fully local:

1. **OFX/QFX downloads (recommended first).** Most US banks — including Citi checking and many brokerages — offer OFX/QFX ("Quicken") export alongside CSV. The format carries `<LEDGERBAL>` (ending balance + as-of date) *and* transactions with bank-assigned `FITID`s, which are better dedupe references than anything we synthesize from CSVs. Same threat model as CSV: you download a file, the app parses it locally. This solves Citi checking/brokerage in one stroke and improves dedupe as a side effect.
2. **Statement PDF balance extraction.** You already have the PDFs. A local parser (pdfplumber, no network) extracts the ending balance and statement date via per-institution patterns, previews it, and writes a checkpoint on confirm. V1 scope is deliberately *balances only* — extracting full transaction tables from PDFs is brittle and unnecessary while CSVs cover transactions.
3. **Manual quick-entry** (already shipped in Phase 3) remains the fallback — one date + one number per statement is a 10-second task.

Connectors (SimpleFIN etc.) stay where the original architecture put them: opt-in per account, never required.

## "Old accounts, like Chase checking, I don't have data for — what about payments made from there?" (Data integrity)

Phase 8 introduces **external accounts**: a lightweight account type representing money sources you don't track. They're excluded from net worth and all spending analytics, but they can be a transfer counterparty. A card payment with no importable source gets a one-click "Paid from untracked account →" action that creates a journaled, clearly-labeled mirror row in the external account and a confirmed `TransferLink` — so payment verification is satisfied through the same machinery as everything else, with zero fake data in your real accounts. When the payment source is *permanently* unknowable, the same action works with a generic "External" account.

---

# Part 3 — Root-Cause Analysis of the Reported Bugs

**RC-1 · Payment verification false positives** (`LATE FEE FOR PAYMENT DUE` $29; `RETURN PROTECTION BENEFIT PAYMENT` $49.27). `_looks_like_card_payment` (`transfers.py:293`) returns true for *any* positive card row whose description contains the substring `PAYMENT` or `AUTOPAY`, OR-ed with the transaction type. Consequences: (a) fee/benefit descriptions containing "PAYMENT" match; (b) because it's an OR, the user's explicit reclassification to `expense`/`refund` cannot dismiss the warning — exactly the reported behavior; (c) there is no dismissal persistence, so even a correct-but-unmatchable warning nags forever.

**RC-2 · The $1,036.24 duplicate pair is also what breaks verification for that card.** Two identical `PAYMENT FROM CHK 6768` rows exist (see RC-3); the transfer matcher pairs 1:1, the checking side has only one −$1,036.24, so at most one card row can ever link — and until the duplicate is resolved, both surface as unmatched-payment warnings. Fixing dedupe fixes half the verification noise.

**RC-3 · Duplicates not surfacing in Duplicate Review.** Two independent causes:
- *Same-file duplicates are fingerprint-distinct by design.* `_source_hash` includes an `ordinal` (`importers.py:676`) so two identical rows in one CSV hash differently — correct for genuinely repeated purchases (the two $6.65 Amazon rows *might* be real), but it means exact same-file dupes import clean with no flag.
- *Duplicate Review only shows import-time flags.* `pending_duplicate_pairs` filters on `review_status == 'possible_duplicate'` (`duplicates.py:23`). Duplicates that arise **across sources** (categorized history vs raw CSV use different hash namespaces: `categorized_history…` vs `transaction-v2…`) or that predate the dedupe hardening are invisible. The 05/21 mirrored Amazon rows (`-$5.93` twice, `-$6.41` twice, one of each still "needs a category") have the signature of a history/CSV overlap. There is no retroactive scan. Phase 7 adds one.

**RC-4 · Lifetime spending shown as current debt.** `_account_value_at` (`snapshots.py:188`): for a non-brokerage account with *zero* snapshots, `base = 0` and the value becomes the sum of all transactions to date — i.e., an unanchored credit card renders its entire imported history as today's balance. The feature request's framing ("exclude unanchored histories rather than treating lifetime spending as current debt") is exactly right; the fix is an anchoring model, not a smarter guess.

**RC-5 · Category change in the account page doesn't reflect in Review.** Both views live inside `App.tsx` with separately-fetched, separately-held state arrays; a mutation in one doesn't invalidate the other. This is a monolith symptom, not an isolated bug — a targeted refetch fixes it now; adopting a shared server-state cache (old Phase 6) fixes the *class*.

**RC-6 · Filters persist across left-nav account switches.** The nav click swaps only the account facet of the URL filter; search and date chips survive (screenshot: `PAYMENT FROM CHK 6768…` + `5/21/26` chips intact on the new account). Missing rule: *navigation intent* (left nav = fresh view) vs *investigation intent* (drill-down = constructed filter, keep it).

**RC-7 · Rule apply requires extra validation for the row you're on.** The Saved Rules verbs are batch-scoped (`unreviewed` / `previous`) and route through preview/validation; there is no per-transaction fast path that classifies *and confirms* the row the user is looking at (and the just-saved-rule toast doesn't offer one either).

**RC-8 · No "save as rule" from the account ledger.** The rule-creation affordance only exists in Review's editor; the ledger's category control offers splits/spread only.

---

# Part 4 — The Plan (Phases 6–13)

Renumbering: new correctness/feature work takes Phases 6–11; the outstanding UX overhaul (old Phase 6) becomes **Phase 12** — deliberately after, so the settings/navigation reorg incorporates the new surfaces (duplicate scan, anchoring, statement ingestion) exactly once. Percentage splits (old Phase 7) becomes **Phase 13**. The strangler rule continues: every phase names its extracted components and must not increase `App.tsx`.

## Phase 6 — Verification & Classification Correctness — ~3 days
*Fixes RC-1, RC-5, RC-6, RC-7, RC-8. All small; ship as one trust-restoring batch.*

**6a. Payment detection v2** (`transfers.py`):
- **Type is authoritative.** If `transaction_type` is user- or rule-set to anything other than `credit_card_payment` (expense, refund, fee), the row is *excluded* from payment warnings. The OR becomes: `type == 'credit_card_payment'`, else keyword heuristics **only** for rows still in `needs_review`/`suggested`.
- **Keyword guard:** require a payment-context token (`PAYMENT RECEIVED`, `ONLINE PAYMENT`, `PAYMENT FROM`, `AUTOPAY`, `ACH PMT`) and reject on negative tokens (`LATE FEE`, `FEE`, `INTEREST`, `RETURN`, `BENEFIT`, `REWARD`, `PROTECTION`). Table-driven so additions are one-liners; unit-test both screenshots' strings.
- **Dismissal persistence:**
```sql
CREATE TABLE payment_verification_dismissals (
    id             INTEGER PRIMARY KEY,
    transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id),
    reason         TEXT NOT NULL,          -- 'not_a_payment' | 'external_source' | 'other'
    created_at     TEXT NOT NULL
);
```
An × / "Not a payment" action on each warning writes a journaled dismissal; dismissed IDs are filtered out of `list_payment_verification`. Reclassifying a transaction's type to expense/refund auto-dismisses (same code path, one operation).

**6b. One-click rule fast-track (RC-7).** New endpoint `POST /api/rules/{id}/apply-to/{transaction_id}`: applies the rule's type/category to that row, sets `review_status='confirmed'`, one journaled operation, returns the undo toast payload. UI: each Saved Rules card gains **"Apply & confirm this row"** when invoked from a transaction context, and the "Rule saved" toast's primary action becomes exactly that for the transaction the rule was born from. The batch verbs (`Apply unreviewed` / `Apply previous`) keep their preview step — batch caution is correct; single-row friction was not.

**6c. Save-as-rule from the ledger (RC-8).** Extract Review's rule-builder row into `features/rules/SaveRuleControl.tsx` and mount it in the account-page category editor: after a category change, an inline affordance — *"Always categorize 'AMAZON MKTPL*' this way → Save rule"* — pre-filled from the row's description with the same match-pattern editor Review uses. Same endpoint, same journaling.

**6d. Cross-view freshness hotfix (RC-5).** Minimal now, proper later: a module-scope `transactionsVersion` bump on every transaction mutation; both the ledger and Review effects depend on it and refetch when stale (visibility-change triggered). One shared helper in `api/client.ts`; the real fix (query cache) lands in Phase 12.

**6e. Navigation filter reset (RC-6).** Rule: **left-nav account clicks construct a fresh filter** — `{accounts:[id], view:'transactions'}` only, dropping search/date/category chips; drill-down links continue to carry their full constructed filter. Implement at the single nav-click handler; add a filters.test case asserting chip state after simulated nav vs drill-down.

**Tests:** detection-v2 truth table (both screenshot strings), dismissal round-trip + auto-dismiss on retype, apply-to-row journaling, nav-reset codec behavior.

## Phase 7 — Ledger-Wide Duplicate Scan — ~3 days
*Fixes RC-3, unblocks RC-2.*

**Schema:**
```sql
CREATE TABLE duplicate_pair_decisions (
    id                INTEGER PRIMARY KEY,
    transaction_a_id  INTEGER NOT NULL REFERENCES transactions(id),   -- a < b normalized
    transaction_b_id  INTEGER NOT NULL REFERENCES transactions(id),
    decision          TEXT NOT NULL,        -- 'keep_both'
    created_at        TEXT NOT NULL,
    UNIQUE (transaction_a_id, transaction_b_id)
);
```
(Existing import-time "keep both" resolutions migrate into this table so re-scans respect them.)

**Logic flow** (`services/duplicate_scan.py`):
1. **Candidate grouping:** live rows grouped by `(account_id, transaction_date, amount_cents, normalized_description)` with count > 1 — the normalization reusing `dedupe.normalize_transaction_description`.
2. **Exclusions:** pairs with a `keep_both` decision; rows on either side of a *confirmed* transfer or refund link (a real payment and its real retry can be same-day/same-amount); rows already flagged `possible_duplicate` (they're in the existing queue).
3. **Confidence tiers:** exact 4-tuple match = "exact"; same tuple but differing `source_reference` where one side is history-namespaced (`categorized-history-row-…`) and the other bank-referenced = "cross-source" (the highest-value tier — it's the history/CSV overlap class); same date/amount, description similarity ≥ 0.85 = "probable".
4. **Mirrored-pair detector** (the `+$29 / −$29 LATE FEE` pair in screenshot 1): same account/date/description with *opposite signs* where one row is refund-typed — the signature of a sign-normalization artifact. Reported as its own tier with a tailored resolution ("Remove sign artifact" deletes the positive twin) since neither row is a "copy" in the normal sense.
5. Results feed the **existing** Duplicate Review UI (Phase 2's `TransactionCompareCard`, three verbs, journaled operations). "Keep both" writes a pair decision. Scan is user-initiated ("Scan ledger for duplicates" button in Review, consistent with the inbox-scan philosophy) and returns a summarized report (N exact / N cross-source / N probable / N mirrored).
6. **Post-resolution hook:** after resolutions in a scan session touch any card account, prompt "Re-run transfer matching?" — resolving the $1,036.24 twin is what lets the surviving row link to the checking debit and clear the verification warning (RC-2).

**API:** `POST /api/duplicates/scan`, `GET /api/duplicates/scan/results`, resolutions reuse `POST /api/duplicates/{id}/resolve` with the new `remove_sign_artifact` action.
**Frontend:** `features/review/LedgerDuplicateScan.tsx` (results grouped by tier, bulk "resolve all exact").
**Tests:** each tier, keep-both memory across re-scans, transfer/refund-link exclusion, mirrored-pair detection against the screenshot's data shape.

**Implemented follow-up:** exact and probable pairs can be selected page-by-page for previewed bulk actions. In addition to Keep both and exact-only removal, Manual-entry rows paired with `transaction history for private finance 7.14.26v2.csv` can prefer that file as authoritative. The established row identity and its annotations/links survive while source facts, lineage, category, and type come from the history row; the redundant row moves to Trash in one undoable operation.

## Phase 8 — Balance Anchoring & External Accounts — ~4 days
*Fixes RC-4; answers the Chase-checking question.*

**Anchoring model.** An account is **anchored** iff it has ≥1 balance anchor: a `net_worth_snapshot` (import/manual) or a `statement_checkpoint`. Brokerage/retirement anchor via holdings snapshots (unchanged).

**Schema:**
```sql
ALTER TABLE accounts ADD COLUMN net_worth_inclusion TEXT NOT NULL DEFAULT 'auto';
-- 'auto'  = include iff anchored (new default behavior)
-- 'always' = include even unanchored (explicit user override, current behavior)
-- 'never' = exclude regardless (e.g., a card you track for spending only)
```

**Logic changes** (`snapshots.py`):
- `_account_value_at` returns `None` for unanchored accounts under `auto`; series/stats/contributors sum only non-None accounts and return `unanchored_accounts: [{id, name}]` alongside so the UI can disclose what's excluded.
- Anchored accounts keep the existing snapshot-plus-movement math, including the *backward* reconstruction before the first snapshot — anchors make that math meaningful; the absence of any anchor is what made it fiction.
- One-time journaled migration: recompute nothing, but surface a startup notice listing accounts whose displayed value will change ("BoA Cash was showing −$41,203 of lifetime history; it is now unanchored").

**UX:** Net Worth page shows an `UnanchoredBanner` — *"2 accounts excluded from net worth: add a statement balance to anchor them"* — each linking to the account page's existing manual statement-balance form (the anchor entry point already exists from Phase 3; this phase makes it load-bearing). Account pages show an "Unanchored" chip next to the reconciliation badge. Sidebar balances for unanchored accounts render "—" with a tooltip instead of the fictional running total.

**External accounts:**
- `account_type = 'external'`; creatable from Settings → Accounts and inline from the payment-verification flow. Excluded from net worth (any inclusion mode), spending, cash flow; hidden from import matching.
- **"Paid from untracked account →"** action on an unmatched card payment: pick/create the external account → the app creates a journaled mirror transaction (−amount, description `External: <original description>`, type `transfer`) in the external account and a *confirmed* `TransferLink`. One operation, undoable. Verification counts it as matched with an "external" tag rather than a warning.

**Frontend:** `features/networth/UnanchoredBanner.tsx`, `features/accounts/ExternalPaymentAction.tsx`, inclusion-mode select on the account page.
**Tests:** value-at for unanchored/auto/always/never, series exclusion payloads, external mirror creation + undo, verification counting external links.

### Implementation audit update — July 15, 2026

Phases 6–8 are substantially aligned with this plan: payment-warning classification and dismissal persistence, one-row rule application, ledger rule saving, cross-view invalidation, navigation reset, ledger-wide duplicate scanning, Keep-both memory, balance anchoring, inclusion overrides, untracked accounts, and external-payment settlement are implemented with the named extracted components and regression coverage.

The audit identified these follow-ups:

- **Probable authoritative-history exception:** generic probable matches still cannot be bulk-removed. The selected **Prefer authoritative history** action is a deliberately narrow exception: every selected pair must resolve to Manual entry on the established side and `transaction history for private finance 7.14.26v2.csv` on the imported side; it requires a stale-safe preview, preserves the established identity and annotations/links, soft-deletes only the redundant candidate, and is one Activity-undoable operation. This exception must not be generalized to ordinary probable matches.
- **Anchoring migration auditability:** the functional startup disclosure exists, but it is remembered in browser `localStorage`, not as the one-time journaled migration originally specified above. Either add durable migration/audit state or revise that requirement before Phase 8 is considered completely closed.
- **Orphaned import lineage:** historical cleanup left some transactions pointing at import-batch IDs whose batch rows no longer exist. The UI and authoritative-history validator now consistently resolve those rows as Manual entry, but a maintenance pass should inventory and repair or null remaining orphaned references.
- **Consistent size measurement:** use `(Get-Content frontend\\src\\App.tsx).Count` for physical lines. The previously reported 5,144 figure counted only nonblank lines. After extracting the shared selection hook for ledger and duplicate range selection, `App.tsx` is **5,339 physical lines** (5,119 nonblank), down 39 from the 5,378-line iteration baseline. It satisfies the per-phase no-growth rule but remains far above Phase 12's <2,000-line exit criterion.
- **Backend composition debt:** service boundaries remain sound, but `backend/app/main.py` is 2,541 physical lines and grew by a net 192 lines during the current uncommitted implementation. Phase 12 should extract API routers/orchestration as well as frontend JSX.
- **High-volume Duplicate Review UX:** duplicate checkboxes now share the account-ledger Shift+click range-selection behavior, and the bulk action bar remains sticky beneath the application header while the user scrolls the 25-row page.

## Phase 9 — Local Statement Ingestion: OFX/QFX + PDF Balances — ~5 days
*Answers the privacy-and-convenience question; feeds Phase 8 anchors for Citi checking/brokerage.*

**9a. OFX/QFX importer** (`services/importers_ofx.py`):
- Parse OFX 1.x SGML and 2.x XML (small hand-rolled tokenizer; no new heavy dependency). Extract: `STMTTRN` rows → transactions with `FITID` as `source_reference` (registered as a reliable-reference preset, upgrading dedupe quality); `LEDGERBAL`/`AVAILBAL` → statement checkpoint + net-worth snapshot (an anchor, per Phase 8); `INVSTMTMSGSRSV1` positions where present → holdings snapshot rows.
- Inbox integration: `.ofx`/`.qfx` files route through the same staging/review pipeline, same sign-profile checks (OFX signs are canonical by spec, but the anomaly guard still runs), same one-operation journaling.
- Docs: `docs/statement-ingestion.md` — per-institution table of "where to find the OFX/QFX download" for your banks.

**9b. PDF statement balance extraction** (`services/statement_pdf.py`, new dep: `pdfplumber`):
- **Scope: balances and dates only.** Pattern registry per institution (regexes over extracted text for `New balance`, `Ending balance`, `Closing balance`, plus statement-period dates), with a generic fallback that finds labeled currency amounts and asks the user to pick.
- Flow: PDF lands in the inbox (or manual upload) → institution matched by folder/filename/text header → extraction → **preview card**: *"Citi Checking (4160) — statement 06/30/26 — ending balance $12,431.07 — [Confirm anchor] [Edit] [Discard]"* → confirm writes a `manual`-source checkpoint + snapshot, journaled. The PDF itself is never stored by the app; only the two numbers are.
- Failure honesty: if extraction confidence is low (multiple candidate balances), show candidates rather than guessing — consistent with the sign-profile philosophy: *detect, ask once, remember* (the chosen pattern is saved per institution so next month's PDF auto-extracts).

**Frontend:** `features/imports/StatementBalanceReview.tsx`; inbox file-type badges (CSV/OFX/PDF).
**Tests:** OFX SGML + XML fixtures (checking, card, investment), FITID dedupe, ledgerbal→checkpoint, PDF pattern registry against synthetic fixtures for BoA/Citi layouts, low-confidence multi-candidate path.

### Phase 9 implementation update — July 15, 2026

Implemented. The inbox and account-selected staging flow accept `.ofx`, `.qfx`, and `.pdf` in addition to CSV. The new hand-rolled OFX reader supports 1.x SGML leaf tags and 2.x XML containers, normalizes `STMTTRN` activity, treats `FITID` as a reliable source reference, writes ledger-balance checkpoints/net-worth snapshots, and records supported investment positions. OFX signs remain canonical-as-provided; the existing plausibility analyzer still adds a visible warning when their distribution contradicts the selected account.

PDF handling remains deliberately balance-only. Local `pdfplumber` extraction produces an editable preview, selects only a single unambiguous labeled balance, presents all candidates when confidence is low, normalizes printed card amounts into negative liabilities, and saves the confirmed balance label per institution. Manually selected PDFs are parsed without being copied into managed staging; inbox PDFs remain user-owned source files. Confirmation writes the checkpoint, net-worth anchor, and learned pattern in one Activity-undoable operation.

`StatementBalanceReview.tsx` owns the new preview UI and file-type badges distinguish CSV/OFX/QFX/PDF. Report-period predicates moved out of the shell during this phase, so `App.tsx` decreased from 5,339 to **5,322 physical lines**. Focused coverage includes SGML checking, XML card/investment fixtures, FITID re-import dedupe, ledger-balance and holding anchors, BoA/Citi synthetic statement layouts, low-confidence multi-candidate behavior, credit-card liability signs, saved institution patterns, and inbox QFX routing. Institution download guidance and data-retention behavior are documented in `docs/statement-ingestion.md`.

## Phase 10 — Refund Data Flow & Categorization — ~2 days
*Closes the dashboard gap from Part 2's first answer.*

1. **Direct categorization of refunds** everywhere expenses can be categorized (ledger, review, bulk bar, rules). A rule may now target `refund` type + category (schema already tolerates it after the categoryless-types work; add tests).
2. **Categorize-time suggestion:** when a user categorizes a refund manually, if an open refund-link suggestion exists for it, the editor shows *"Looks like a refund of [expense] — link it?"* so linking (which inherits the category anyway) stays the primary path and manual categorization the fallback.
3. **Overview correctness check:** add aggregation tests asserting a categorized refund reduces its category's period total and appears in category drill-downs (the signed-sum predicate should already do this once `category_id` is set — the test pins it).
4. **"Uncategorized refunds" nudge:** Review sidebar count + filter chip (`types=refund, category=none`), so leakage is visible instead of silent.

**Frontend:** extend existing category editors; no new components beyond the nudge chip.

### Phase 10 implementation update — July 16, 2026

Implemented. Refunds now share direct category assignment and saved-rule behavior with expenses in Review, bulk review, and the account ledger. Single and bulk confirmation enforce a category for both expense and refund rows at the API boundary, preventing an uncategorized refund from disappearing merely because it was confirmed. Confirmed refunds without categories remain in the Review queue; the primary navigation shows the complete queue count and an **Uncategorized refunds** chip isolates the affected rows.

Open refund suggestions are surfaced beside the refund in both Review and the ledger editor with **Link refund** and **Not this expense** actions. Confirming the link continues to make the original expense category authoritative. Signed category aggregation is pinned by a regression test proving that a $20 refund nets a $120 expense to $100 and that the category drill-down contains both rows. Review-queue and transaction-type behavior have focused Vitest coverage.

`PrimaryNav` and the review-queue policy moved out of the shell. `App.tsx` decreased from the Phase 9 baseline of 5,322 to **5,320 physical lines**. Phase verification: **215 backend tests passed**, **17 Vitest tests passed**, TypeScript/production Vite build succeeded.

## Phase 11 — Brokerage & Net-Worth UX — ~3 days
*Assets-first pages, holdings table upgrades, asset editing parity.*

1. **Brokerage/retirement account page layout:** `HoldingsPanel` renders **above** transactions (assets first, per request), with the transactions section collapsed by default for these account types.
2. **Holdings details table** (Net Worth tab and account pages, one shared component):
   - New **Institution/Bank** column (joins account → institution).
   - **Total row** (Σ market value, Σ basis, Σ unrealized G/L) pinned at the bottom.
   - **Sortable columns**, ascending/descending, on every column (symbol, bank, quantity, price, value, basis, G/L, lot age) — a small `useSort` hook + header chevrons; sort state in the URL like every other view state.
3. **Asset editing parity (the "editing" request):** holding lots and manual balance snapshots get the same inline-edit affordances as ledger rows — edit-in-place for date/quantity/basis/note, delete with the shared `DeleteConfirmInline`, every change journaled with the standard undo toast. Backend: `PATCH /api/holdings/lots/{id}`, `DELETE …`, `PATCH /api/networth/snapshots/{id}` (manual-source only), all journaling through `mutation_log`.

**Frontend:** `features/networth/HoldingsTable.tsx` (extracted, sortable, totaling), `features/networth/LotEditor.tsx`.
**Tests:** sort stability, total-row math, lot edit/undo, manual-snapshot edit guard (import-source snapshots immutable).

## Phase 12 — UX Overhaul + Decomposition Completion (old Phase 6) — ~6–7 days

Everything from the previous plan's Phase 6 stands: settings information architecture (now including sign profiles, saved PDF patterns, external accounts under sensible tabs), left-nav single-account flattening, the `FilterSummaryBar` (totals / count / avg-monthly under current filters), custom date-range picker feeding the canonical filter, and Overview tab reorder to **Overview · Net Worth · Spending · Cash Flow** with Income folded into Cash Flow.

Two additions earned by this iteration:
- **Adopt TanStack Query during the extraction** — RC-5 proved the ad-hoc state model now produces user-visible staleness bugs; the Phase 6d hotfix is a stopgap. Query-key-per-filter with invalidation on mutation retires that bug class.
- **Exit criteria (hard):** `App.tsx` < 2,000 lines; zero feature JSX left in it beyond shell/layout; every mutation flows through shared hooks.

## Phase 13 — Percentage Splits (old Phase 7) — ~1 day
Unchanged: %/$ toggle, largest-remainder rounding, cents stored; exposed in both ledger and Review split editors (same extracted component after Phase 12).

---

# Part 5 — Sequencing & Risk

| Order | Phase | Effort | Depends on | Requests addressed |
|---|---|---|---|---|
| 6 | Verification & classification correctness | 3 d | — | Card payment tagging, editing (rules), categorization (save-rule, staleness), navigation (filter reset) |
| 7 | Ledger duplicate scan | 3 d | 6a (clean warnings first) | Dedup |
| 8 | Balance anchoring & external accounts | 4 d | — | Privacy/convenience (anchor model), data integrity (Chase checking), data flow (balances) |
| 9 | OFX/QFX + PDF statement ingestion | 5 d | 8 (anchors defined) | Privacy/convenience, statement balance data, data flow |
| 10 | Refund data flow | 2 d | — | Data flow (refund categories) |
| 11 | Brokerage & net-worth UX | 3 d | 8 helpful | Brokerages, net worth page, navigation (sorting), editing (assets) |
| 12 | UX overhaul + decomposition | 6–7 d | benefits from 6–11 | (prior plan b.1–b.3, a.2) + staleness class fix |
| 13 | Percentage splits | 1 d | 12 | (prior plan a.7) |

Phases 6→7 are strictly ordered (duplicate resolution should happen against a detector that no longer cries wolf). 8→9 are strictly ordered (ingestion writes into the anchoring model). 10 and 11 can interleave anywhere after 6.

**Risks:**
- *Anchoring migration shock:* net worth totals will change the moment unanchored accounts are excluded. Mitigate with the startup notice, the banner listing exclusions, and the `always` escape hatch per account. Do not soften the default — the current number is wrong, and "wrong but familiar" is the trap.
- *PDF pattern brittleness:* treat every extraction as a preview, never auto-commit; saved per-institution patterns turn month two into one click without ever trusting month one blindly.
- *Duplicate scan over-flagging:* legitimate same-day same-amount purchases exist (the two $6.65 Amazon rows may be real). Tiering plus keep-both memory plus per-pair review remain the default: never bulk auto-delete an ordinary pair below the "exact" tier, and even exact bulk resolution stays one journaled, undoable operation. The only probable-tier exception is the constrained, previewed authoritative-history merge documented in the audit above; it preserves the established identity and must not become a generic probable-delete path.
- *Detector changes regress transfers:* payment-detection v2 tightens keywords; re-run the transfer matcher tests plus a fixture from the real `PAYMENT FROM CHK … CONF#…` shape to prove true positives still match.

**Standing merge gate (unchanged, restated):** `pytest` green, `pnpm build` green, CHANGELOG + App.tsx physical line count updated per phase. Current July 16 Phase 10 verification: **215 backend tests passed**, TypeScript is green, **17 Vitest tests passed**, and the production Vite build succeeds. Repeat this gate before each merge.
