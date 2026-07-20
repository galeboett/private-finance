# Private-Finance — Codebase Evaluation & Implementation Plan, Iteration 4
**Date:** July 19, 2026 · **Inputs:** latest codebase zip, `PF-feature-requests-7.19.26.md`
**Continues:** `pf-implementation-plan-iteration-3-7-14-26.md` (Phases 6–12 verified complete; percentage-split controls present in the split editors)

---

# Part 1 — Codebase Evaluation

## What the codebase does well (verified, not assumed)

- **The decomposition finally happened.** `App.tsx` is 7 lines. Features live under `features/` in 40+ focused components, shared primitives under `components/`, tested hooks under `lib/`. Settings has the five-tab IA; `PrimaryNav`, `DateRangePicker`, `FilterSummaryBar` all extracted with tests.
- **Test discipline is real:** 34 backend test files (231 tests passing at last checkpoint) + 27 frontend tests, and — for the first time — the changelog reports **the production build passing** at every phase checkpoint. The merge gate is finally being honored.
- **The architectural spine held.** One canonical filter contract, one mutation journal with undo across every subsystem, one sign contract with per-source profiles, link tables (transfer/refund/duplicate decisions) instead of status-flag overloading. New features consistently reuse these rather than inventing parallel mechanisms — the strongest possible signal for long-term maintainability.
- **Dependency footprint is admirably small** for a privacy-sensitive app: four runtime frontend deps (React, ReactDOM, TanStack Query, lucide icons — charts are hand-rolled SVG), and a lean backend (FastAPI, SQLAlchemy, argon2, pdfplumber). Small surface = small supply-chain risk. Keep it this way.
- **Honest threat model** (`docs/threat-model.md`) that already names its own gaps — including the two biggest ones below. This evaluation operationalizes them.

## Findings — Quality & Maintainability

**Q-1 · The monolith moved; it didn't die.** `useFinanceController.tsx` is **2,987 lines with 103 `useState` calls**, and `FinanceWorkspaceView.tsx` is 2,469 lines. The <2,000-line App.tsx gate was met in letter — the feature JSX extraction is genuine and valuable — but the *state* monolith relocated into a single god-hook whose every state change re-renders the entire workspace. `api/hooks.ts` is only 54 lines, so TanStack Query adoption is thin: most data flow still runs imperatively through the controller. This is now the app's #1 maintainability and performance liability, and it will tax the mobile work (Feature 3) on every screen if not addressed first.

**Q-2 · Backend router monolith.** `main.py` is **2,801 lines** and growing (2,009 → 2,349 → 2,801 across three snapshots). The `api/aggregation.py` router extraction proved the pattern; the remaining ~90 endpoints still live in one file. Services underneath are clean, so this is a mechanical split, but every merge in a 2,800-line file is a conflict magnet for a two-person team.

**Q-3 · Unpaginated ledger with full-table side loads.** `list_transactions` (`main.py:1268`) returns the entire filtered ledger and — worse — loads **every row of `expense_allocations` and `transaction_splits` table-wide** on every call, regardless of filter. With 10–20 accounts and years of history this degrades linearly forever, and it's fatal on mobile radios. Needs keyset pagination and filter-scoped side loads.

**Q-4 · The migration ladder has no versioning and no retirement path.** `bootstrap.py` is an ever-growing `if column missing: ALTER TABLE` ladder plus in-place table rebuilds, and one-time repairs (`history_cleanup.py` 271 lines, `history_rebuild.py` 189 lines, the Fidelity snapshot repair, `migrate_keep_both_decisions`) run at every startup forever. It works, but it's write-only code: nothing ever gets deleted, and ordering is implicit. This is also the crux of Feature Request 2 — see Part 2.

**Q-5 · Personal data hardcoded in product code — again.** `duplicates.py:21` hardcodes `AUTHORITATIVE_HISTORY_FILENAME = "transaction history for private finance 7.14.26v2.csv"` and `history_rebuild.py:28` hardcodes the workbook filename. This is the same defect class as BUG-07 (the hardcoded Venmo name): user-specific artifacts baked into shared code, breaking the two-person model and embedding one user's data trail in the repo. These should be settings, parameters, or data-driven lookups.

**Q-6 · Docs drift:** `threat-model.md` links to `docs/privacy-risks.md`, which doesn't exist in the tree. Minor, but broken links in security docs erode trust in the docs generally.

## Findings — Privacy & Security (measured against the stated Signal-level bar)

Current posture is solid *for a localhost-only app*: Argon2id with transparent rehash, HttpOnly/SameSite=Strict session cookie, CSRF header on mutations, host/origin allowlist middleware, login rate limiting, idle + absolute session lifetimes, formula-safe CSV export, backups constrained to a directory, no telemetry, no third-party calls anywhere. That's genuinely good. The gaps, in order of severity against a Signal-grade standard:

**P-1 · Plaintext SQLite at rest.** Signal's defining local property is an encrypted database; here, anyone with disk access reads the full ledger. The threat model already lists device loss in scope. Fix: SQLCipher-compatible encryption (Phase 17) with the key derived from the login password — meaning the existing password becomes the actual data key, not just a gate.

**P-2 · Unencrypted backups and JSON export.** The plaintext problem, portable. Backups are byte-copies of the plaintext DB; the app-data JSON export is cleartext. Both should support passphrase encryption (AES-256-GCM, Argon2id KDF), and export should require recent re-auth (already a named threat-model gap).

**P-3 · Cookie `secure=False`, no security-headers middleware.** Correct today (localhost HTTP), but it must become configuration-driven *before* any network exposure — which Feature 3 (mobile) introduces. Add CSP, `X-Content-Type-Options`, `Referrer-Policy: no-referrer`, and frame-denial headers now; they cost nothing on localhost and are mandatory later.

**P-4 · Log hygiene.** `server.out.log`/`server.err.log` accumulate uvicorn access lines including query strings — and the canonical filter model deliberately puts search text in query strings. Financial search terms in plaintext logs contradicts the bar. Fix: disable access logging by default or redact query strings; document log location and rotation.

---

# Part 2 — The Three Feature Requests

## FR-1 · Teach-the-Extractor: a visual PDF region trainer

**Current state:** `statement_pdf.py` extracts by global regex (`BALANCE_PATTERN`, four date patterns), remembers only a *preferred label* per institution, and correctly refuses to guess among ambiguous candidates. That's safe but ceiling-limited: any statement whose layout doesn't say "Ending balance …" on one line falls back to manual entry, forever.

**Approach: positional templates taught by highlighting, applied by anchor.** The user draws boxes on a rendered statement page once; the app saves *where* the balance and date live (relative to a stable text anchor), and every future statement from that institution extracts automatically.

### Data schema

```sql
CREATE TABLE pdf_extraction_templates (
    id               INTEGER PRIMARY KEY,
    institution      TEXT NOT NULL,            -- matched via existing institution detection / user pick
    account_id       INTEGER REFERENCES accounts(id),   -- NULL = all accounts at institution
    field            TEXT NOT NULL,            -- 'balance' | 'statement_date' | 'account_last4'
    page_number      INTEGER NOT NULL,         -- 1-based; negative = from end (-1 = last page)
    anchor_text      TEXT,                     -- nearest stable label, e.g. "New Balance"
    anchor_dx        REAL, anchor_dy: REAL,    -- normalized vector: anchor bbox → target bbox
    region_x0        REAL, region_y0 REAL,     -- normalized absolute region (fallback when anchor missing)
    region_x1        REAL, region_y1 REAL,
    value_pattern    TEXT NOT NULL,            -- validation regex: currency for balance, date for dates
    confirmations    INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE (institution, account_id, field)
);
```

Normalized (0–1) coordinates make templates resilient to DPI/page-size differences. **No financial values are ever stored in a template** — only geometry, a label string, and a validation pattern.

### File structure

```
backend/app/services/statement_pdf.py        # extended: template application path
backend/app/services/pdf_teaching.py         # NEW: word-box inspection, template CRUD, anchor derivation
backend/app/api/pdf_templates.py             # NEW router: inspect/teach/list/delete endpoints
frontend/src/features/imports/PdfRegionTeacher.tsx     # NEW: page image + word-box overlay + drag-select
frontend/src/features/imports/StatementBalanceReview.tsx  # gains "Teach the extractor" entry point
frontend/src/features/settings/PdfTemplatesPanel.tsx   # extends existing PDF-patterns panel: list/edit/delete
```

### API

```
POST /api/imports/pdf/inspect       { staged_batch_id, page }  →
     { page_count, page_image (PNG, in-memory render), words: [{text, x0, y0, x1, y1}] }
POST /api/pdf-templates             create/replace template (journaled operation)
GET  /api/pdf-templates             list (feeds the Settings panel)
DELETE /api/pdf-templates/{id}      (journaled)
```

Rendering uses pdfplumber's page rasterization (verify the `pypdfium2`/imaging dependency it requires in your environment before committing to it; if it drags in a heavy system dependency, the fallback design is a pure word-box canvas — the frontend draws the word rectangles and text itself, no raster image needed, which is uglier but dependency-free). Page images are generated per-request in memory and **never persisted** — consistent with the existing rule that uploaded PDFs aren't copied into managed storage.

### Teaching flow (logic)

1. From a PDF preview that failed or was ambiguous, user clicks **"Teach the extractor."**
2. `PdfRegionTeacher` opens: page navigator, rendered page, word boxes overlaid on hover.
3. User drag-selects the balance value → assigns it to **Balance**. Live feedback shows the captured text and whether it parses as currency (`value_pattern` check). Repeat for **Statement date** (and optionally account last-4 for routing).
4. The service derives the anchor automatically: the nearest word cluster left/above the selection whose text is stable-looking (letters, not digits) — e.g., "New Balance as of". The anchor and offset vector are stored; the absolute region is stored as fallback. User can override the anchor by clicking a different label word.
5. Save = one journaled operation (visible in Activity, undoable), template appears in Settings → Imports → PDF extraction patterns.

### Application flow (logic)

On every PDF staging for that institution/account:
1. Load templates; for each field: locate `anchor_text` on the template's page (case-folded, whitespace-normalized, fuzzy ≥0.9); project the offset vector; collect words intersecting the projected region.
2. Anchor missing → try absolute region. Both missing → fall back to the existing regex extractor.
3. Captured text must match `value_pattern`; a balance that fails validation is *never* silently accepted — the preview shows the failure and offers re-teaching.
4. **Trust ladder:** template-extracted values pre-fill the existing preview card. After **two consecutive confirmed extractions with zero edits** (`confirmations` counter), subsequent statements auto-commit their anchor as a journaled operation with an Activity entry and undo — "works cleanly and reliably" without ever having auto-committed an unproven template. Any user edit resets the counter.
5. Layout drift (anchor found, validation fails, or value jumps implausibly vs the prior checkpoint) demotes the template back to preview mode with a "statement layout may have changed — re-teach?" prompt.

**Tests:** anchor relocation across shifted layouts (synthetic fixtures), fallback ordering, validation-failure demotion, trust-ladder promotion/reset, template CRUD journaling, no-image-persistence assertion.

**Effort:** ~5–6 days (the teacher UI is most of it).

## FR-2 · The Reddit "ignore backward compatibility" advice — is it right for this project, and has bloat already happened?

**Short answers: the advice is half-right for you; yes, the bloat has started (measurably, though it's hundreds of lines, not 20,000); and the fix is a policy split between *interface* compatibility (drop it) and *data* compatibility (keep it, but give it a retirement path).**

**Where the advice fits this project.** This app has exactly one deployment, two users, and a frontend and backend that ship together from one repo. There are **no external API consumers, no plugin ecosystem, no old clients**. Therefore *interface-level* backward compatibility is pure waste here: API aliases, renamed-setting shims, redirect routes, and "keep the old spelling working" code defend against a consumer that cannot exist. On this half, the Reddit poster is right, and the instruction is worth adopting — in adapted form.

**Where the advice is wrong for you.** This is not a greenfield project: there is one production SQLite database holding years of financial history that cannot be regenerated. "Ignore legacy" applied naively would mean schema changes that orphan real data. **Database migration is the one sanctioned compatibility layer** — Signal itself carries decades of schema migrations for exactly this reason. The refinement that keeps migrations from becoming the bloat: *one-time repairs must be retirable*, not immortal.

**The audit — bloat already present (~900 lines and growing):**

| Item | Lines | Class | Verdict |
|---|---|---|---|
| `history_cleanup.py` (legacy sign normalization) | 271 | one-time repair, runs its check forever | retire: executed 7/13; keep the tests' fixtures, delete the service after a final verified backup |
| `history_rebuild.py` (workbook rebuild, hardcoded filename) | 189 | one-time repair + personal data in code | retire + the filename must go regardless |
| `bootstrap.py` ALTER ladder + `category_rules_v2` rebuild + `migrate_keep_both_decisions` | ~109 | unversioned migrations | convert to versioned migrations (below), then prune executed ones |
| `AUTHORITATIVE_HISTORY_FILENAME` special-casing in `duplicates.py` | ~30 | personal data + one-flow hack | replace with a user-selectable "authoritative source" picker (any batch), delete the constant |
| `PF_IMPORT_INBOX_DIR` alias | ~5 | interface shim | delete; you both know the new name |
| `/reports` → Overview and Income-tab → Cash Flow redirects | ~15 | interface shim for your own bookmarks | delete after a grace week |
| Fidelity one-time snapshot repair | ~60 | one-time repair | retire once verified |

**The structural fix — versioned migrations with a retirement policy** (this becomes Phase 14):

```
backend/app/migrations/
├── __init__.py          # runner: reads schema_version, applies in order, records
├── m0001_baseline.py    # snapshot of today's schema (CREATE-if-empty)
├── m0002_....py         # each future change = one small file
```
```sql
CREATE TABLE schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL,
    description TEXT NOT NULL
);
```
Rules: migrations run once and are recorded, never re-checked at startup; **data-repair migrations carry a retirement note** ("delete this file after both databases pass vN") and get deleted in the next cleanup PR; `bootstrap.py` shrinks to "run pending migrations + seed."

**The adapted instruction to adopt** (for `docs/collaboration.md` and any agent instruction file — replacing the Reddit one-liner, which is too blunt for a post-greenfield app):

> *No interface compatibility: this app has one deployment and its frontend/backend update in lockstep. Never add API aliases, renamed-setting shims, redirect routes, or deprecated-path support — rename and delete cleanly in the same change. The database is the sole exception: schema and data changes go through numbered migrations, and one-time data repairs must state their retirement condition and be deleted once both collaborators' databases have passed them. Never hardcode user-specific filenames, names, paths, or account details in product code — those are settings or data.*

**Has the 20,000-line disaster happened? No** — the discipline of journaled one-time operations actually kept this far tamer than the Reddit scenario. But the growth pattern (three one-time repairs in six days, each immortal at startup) is exactly how it compounds. Catch it now while it's ~900 lines.

## FR-3 · Mobile access

**Decision framework — the options, against the Signal bar:**

| Option | Privacy | Effort | Verdict |
|---|---|---|---|
| **Responsive web + PWA, reached over a private mesh VPN (Tailscale/WireGuard)** | Excellent: zero public exposure, E2E-encrypted transport, no app store, no cloud, works away from home | Medium | **Recommended** |
| Responsive web on LAN only (HTTPS via mkcert) | Excellent but home-only; cert distribution is fiddly | Low-medium | Acceptable fallback / first step |
| Public reverse proxy (Caddy/nginx + domain) | Puts a financial app on the public internet; whole classes of new threats for zero benefit over a mesh VPN | Medium | **Rejected** |
| Native app (React Native / wrapper) | No privacy gain over PWA; large new codebase, store accounts, update pipeline | Very high | **Rejected** |

A PWA over Tailscale gives you an installable home-screen app with TLS (Tailscale can provision valid certs), reachable from anywhere, visible to no one outside your two-device tailnet — the closest architectural analog to Signal's "private by construction" posture available to a self-hosted app.

**Plan (three phases, in Part 3 as Phases 18–19):**

**A. Responsive foundation** (largest chunk — and the reason Q-1 must land first):
- Breakpoint strategy: one primary breakpoint (~760px, already used in 15 media queries) with layout swaps, not just squeezes: sidebar → bottom tab bar (`PrimaryNav` adaptive: Overview / Accounts / Review / Activity / Settings); account list becomes its own screen rather than a persistent rail.
- Transactions: the wide table becomes a **card list** on small screens (date, description, category chip, signed amount; tap = detail sheet with the existing editors). The bulk-selection bar and undo toasts anchor bottom-fixed above the tab bar.
- Charts: the hand-rolled SVG charts need width-aware viewBoxes and touch handlers (drag-select on the net-worth chart → touch drag with the same range-stats strip).
- Touch targets ≥44px, `DateRangePicker` full-screen sheet on mobile, tables → `useSort` unchanged (header taps).
- Keep one codebase, one route model — the canonical URL filter contract means mobile and desktop share every deep link.

**B. PWA layer:**
- `manifest.webmanifest` + icons + `vite-plugin-pwa`.
- **Service-worker policy is a privacy decision:** cache-first for static assets only; **`/api/*` is network-only, never cached** — no financial data at rest in the SW cache. No offline ledger in v1 (offline reads would mean an unencrypted IndexedDB mirror; revisit only after P-1 encryption ships, if ever).

**C. Secure exposure (config, not code-heavy):**
- Settings additions: `PF_ALLOWED_HOSTS`/`PF_ALLOWED_ORIGINS` extendable; `PF_COOKIE_SECURE` (auto-true when the request scheme is https); bind address stays `127.0.0.1` by default with `tailscale serve` proxying to it — the app itself never listens on a network interface.
- Security headers middleware from P-3 becomes load-bearing here; CSRF and session models already work unchanged (SameSite=Strict is fine since app and API share an origin).
- `docs/mobile-access.md`: the Tailscale recipe (install on server + phone, `tailscale serve https / http://127.0.0.1:8000`, install PWA), plus the LAN/mkcert fallback.
- Optional D (nice-to-have, later): WebAuthn/passkey login — faster than passwords on phones and genuinely stronger; the session table already supports multiple credentials cleanly.

---

# Part 3 — The Phased Plan (Phases 14–19)

Ordering: hygiene and the two monolith splits first (they cheapen everything after, and Q-1 directly gates mobile); encryption before exposure; PDF teaching is independent and can interleave.

## Phase 14 — Lifecycle Hygiene & De-Personalization — ~2–3 days
1. Versioned migration runner + `schema_version` + `m0001_baseline`; port the bootstrap ladder; `bootstrap.py` becomes runner + seed.
2. Retire executed one-time repairs (`history_cleanup`, `history_rebuild`, Fidelity repair, keep-both migration) after both databases verify at baseline; delete with their entry points and settings-page maintenance cards.
3. Remove `AUTHORITATIVE_HISTORY_FILENAME` — replace with a batch-picker parameter on the authoritative-source flow. Remove `HISTORICAL_WORKBOOK_FILENAME` with its module.
4. Delete interface shims: `PF_IMPORT_INBOX_DIR` alias, `/reports` and Income-tab redirects.
5. Adopt the adapted no-compat instruction in `docs/collaboration.md`; fix the `privacy-risks.md` broken link (write the stub or drop the reference).

## Phase 15 — Backend Router Split — ~2 days
Mechanical, behavior-neutral: `main.py` → `api/` routers (`auth.py`, `transactions.py`, `imports.py`, `review.py`, `operations.py`, `networth.py`, `accounts.py`, `rules.py`, `settings.py`), shared dependencies already in `api/dependencies.py`. `main.py` becomes app factory + middleware + router registration (<150 lines). Add **keyset pagination** to `list_transactions` (cursor = `(transaction_date, id)`, page size 200) and scope the allocation/split/refund side loads to the returned page's transaction IDs (Q-3). Frontend: infinite-scroll/`Load more` in the ledger via a paged query hook.

## Phase 16 — Frontend Controller Decomposition — ~4–5 days
Break `useFinanceController` (103 useStates) into domain hooks consuming TanStack Query properly: `useLedger`, `useReviewQueue`, `useImports`, `useNetWorth`, `useAccountsNav`, `useActivity` — each owning its queries, mutations (with targeted invalidation), and view state; `FinanceWorkspaceView` becomes route-level composition delegating to feature components. Exit criteria: no file over 800 lines in `app/`; `api/hooks.ts` is the only fetch path; React DevTools shows ledger edits re-rendering only ledger surfaces. This is the mobile prerequisite: Phase 18's card-list/table swap must be a view-layer change, not a controller surgery.

## Phase 17 — Encryption at Rest & Encrypted Exports — ~4 days
1. **Database:** SQLCipher-compatible encryption via `sqlcipher3` (or `apsw` with SQLCipher), key derived from the login password via Argon2id (separate salt from the auth hash; changing password re-keys with `PRAGMA rekey`). Migration: one-time encrypted copy with automatic pre-migration backup, verify, swap — a numbered migration per Phase 14. Fallback if the SQLCipher dependency proves painful on Windows: application-level encrypted backups/exports (step 2) plus documented OS full-disk encryption; do not ship a half-measure that *claims* DB encryption.
2. **Backups/exports:** passphrase-encrypted archive option (AES-256-GCM, Argon2id KDF, `cryptography` lib) for both SQLite backups and JSON export; restore path decrypts with clear wrong-passphrase errors.
3. **Re-auth for export/restore/password-change:** require password within the last 5 minutes (threat-model gap closed).
4. **Log hygiene (P-4):** default uvicorn access log off (or query-string redaction); document in threat model.
5. Security-headers middleware (P-3): CSP (self-only), `X-Content-Type-Options`, `Referrer-Policy: no-referrer`, `frame-ancestors 'none'`; `secure` cookie flag config-driven.

## Phase 18 — PDF Extraction Teaching UI (FR-1) — ~5–6 days
As specified in Part 2/FR-1: teaching schema + inspect endpoint + `PdfRegionTeacher` + anchored application with the trust ladder + Settings templates panel.

## Phase 19 — Mobile (FR-3) — ~6–8 days
A (responsive foundation) → B (PWA with network-only API policy) → C (Tailscale exposure recipe + config flags). Optional WebAuthn afterward.

## Sequencing

| Order | Phase | Effort | Depends on |
|---|---|---|---|
| 14 | Lifecycle hygiene & de-personalization | 2–3 d | — |
| 15 | Backend split + pagination | 2 d | 14 (migrations) |
| 16 | Controller decomposition | 4–5 d | 15 (paged endpoints) |
| 17 | Encryption at rest & exports | 4 d | 14 (migration runner) |
| 18 | PDF teaching UI (FR-1) | 5–6 d | independent (after 15 ideally) |
| 19 | Mobile (FR-3) | 6–8 d | 16 hard; 17 strongly advised before exposure |

**Risks:** SQLCipher-on-Windows packaging is the flakiest item — timebox a spike day and take the documented fallback rather than stalling the phase. The controller decomposition is the regression-riskiest — lean on the 27 frontend tests, add hook-level tests per extraction, and keep each domain-hook PR behavior-neutral. Retiring one-time repairs requires both collaborators' databases verified at baseline first — coordinate before deleting.

**Standing merge gate (unchanged):** `pytest` green, `pnpm build` green, CHANGELOG updated; line-count reporting now applies to `useFinanceController.tsx` and `main.py` the way it did to `App.tsx`. Neither suite could be run in this analysis environment; both remain on you.
