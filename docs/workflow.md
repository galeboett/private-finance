# User Workflow

## Pre-merge checks

Before merging any change:

1. Run the backend suite from `backend/`: `pytest`.
2. Run the production frontend build from `frontend/`: `pnpm build`.
3. Confirm both commands finish successfully. Type-checking alone does not replace the production build.
4. Update `CHANGELOG.md` and the relevant evaluation-plan status when behavior or plan status changes.
5. Confirm `frontend/src/App.tsx` did not grow. New or touched screens belong in `features/` or `components/`.

The optional `post-merge` hook rebuilds and restarts the local app after a pull. It is a convenience after merge, not a substitute for these checks before merge.

## Goal

The app builds a full personal finance picture by turning account exports into a single reviewed ledger. The ledger then powers cash flow, spending, net worth, and export views.

## Current Workflow

1. Add an account.
   - Create one account for each real-world checking account, savings account, credit card, brokerage account, or retirement account.
   - The account is the container that tells the app where an uploaded file belongs.

2. Add downloaded CSV, OFX/QFX, or statement PDF files to the Import Inbox.
   - Copy files into the local folder shown under Settings → Smart import → Import Inbox.
   - When two accounts produce generic names such as `stmt.csv`, create one subfolder per account and include the last four digits: `boa-checking-1016/stmt.csv` and `boa-checking-6768/stmt.csv`. The scanner searches subfolders and uses the full relative path for account matching.
   - The default folder is `~/PrivateFinance/import-inbox`, outside the source repository. Set `PF_IMPORT_INBOX` to choose another location.
   - The app does not monitor this folder automatically. Select **Scan inbox** when you want it to search for files and stage new matches.
   - A file selected directly in Smart import is staged in this same inbox and review flow; it is no longer committed through a separate path.
   - Files without a confident account match are left untouched and listed for manual Smart import.
   - For an unfamiliar CSV layout, choose its date, description, and amount columns once. This browser remembers the mapping for later files with the same headers.
   - The import preview shows how each amount will be interpreted. Normally, charges/withdrawals are negative and refunds/deposits are positive. If a raw file uses the opposite convention, choose **Reverse detected signs**, preview again, and stage only after the interpretation is correct.
   - OFX/QFX transactions use the institution's `FITID` as a reliable dedupe reference. Statement balances and supported investment positions in the same file become net-worth anchors when confirmed.
   - PDF import is balance-only. Choose the statement date and ending balance from the preview; ambiguous candidates are never selected automatically. See `docs/statement-ingestion.md` for institution guidance and privacy details.

3. Preview the normalized rows.
   - The app detects the file family from known headers.
   - It shows normalized rows before anything is committed.
   - This step protects the ledger from bad mappings or wrong-account uploads.

4. Confirm the staged import.
   - Confirm or discard each pending batch from the Import Inbox.
   - The app adds new rows to the database.
   - Exact duplicates are skipped. For Bank of America reference-number exports and Venmo activity, the issuer's stable reference is checked first: the same account, reference, date, and amount is one transaction even if the bank later changes its description.
   - If an issuer reuses a reference with a different date or amount, the row is imported as **Possible duplicate** and linked to the existing transaction for review instead of being silently discarded.
   - Other raw CSV formats use an account-independent normalized transaction fingerprint, with compatibility checks for older fingerprints. Account cleanup reconciles ordinary CSV fingerprints when it merges account records, so a temporary internal account ID cannot defeat a later re-import check.
   - Categorized-history importing remains a separate one-time workflow and is not included in this raw-CSV reference-matching behavior.
   - Inbox source files are never moved or deleted, and confirmed imports are recorded in the mutation journal. A manually selected PDF is parsed in memory and is not copied into managed staging; only its confirmed date and balance are saved.
   - Download suffixes such as `(1)` do not determine duplicates. The app compares exact bytes, normalized parsed rows, and reliable issuer references, so renamed/reformatted copies are skipped while genuinely changed files are staged.

5. Review and categorize.
   - Open **Review → Duplicates** for transactions linked to an existing ledger row. Differing fields are highlighted side by side.
   - **Remove new copy** moves the newly imported row to Trash. **Keep both** clears the duplicate link and returns the new row to ordinary category review. **Replace old bank details** updates the existing row's bank-sourced date, amount, description, and reference while preserving its category, notes, labels, and splits.
   - Exact matches can be resolved together as one Activity operation and one Undo.
   - The app can suggest transaction types and categories from rules.
   - The user confirms or corrects those suggestions.
   - Corrections can become future rules.
   - Add private notes when the bank description is vague but you know what the purchase was.

6. Overview analysis updates from the ledger.
   - Cash-flow summaries use checking, savings, income, spending, transfers, and card payments.
   - Spending summaries use expense transactions and fixed categories.
   - Net-worth views use account balances and investment snapshots.
   - Use the Overview tabs in this order: **Overview, Net Worth, Spending, Cash Flow**. Income-versus-expense analysis is part of Cash Flow; old `?tab=Income` bookmarks redirect there.
   - The customizable finance cockpit appears only on Overview. Its account map, cash-flow trend, and top-spending cards provide a high-level summary; dedicated analysis tabs avoid repeating those same cards.

7. Investigate filtered activity.
   - All Accounts and individual account ledgers show total in, total out, net, transaction count, and average monthly outflow for the current filters. Select a value to preview its matching transactions.
   - Use **Custom…** for a bookmarkable two-month date-range calendar. **Last 90 days** and **This quarter** fill the same canonical `dateFrom`/`dateTo` URL filters used by drill-downs and removable chips.
   - Institutions with one account appear as one direct sidebar row. Institutions with several accounts remain collapsible groups.

## Net Worth History

- Open the overview and select **Net Worth** in the report tabs.
- Choose **1M**, **6M**, **1Y**, or **Max**. The selected period stays in the page URL so it can be bookmarked.
- Hover over the chart to inspect a day's total.
- Drag across a date range to see the change, percent change, high, and low for that range.
- Select **View transactions** to open the transaction ledger with the chosen dates already applied.
- Select **Clear** or press Escape to remove the range selection.
- Imported running balances and brokerage positions create durable snapshots. Between known balances, the app reconstructs checking and savings history from ledger movements and forward-fills investment values.
- An account in **Automatic** net-worth mode is included only after it has a real balance anchor: a statement balance, imported/manual balance, or holdings snapshot. Unanchored accounts show `—` in the sidebar and appear in the Net Worth warning banner instead of treating lifetime activity as today's balance.
- On an account page, use the **Net worth** selector to keep automatic anchoring, explicitly include an unanchored history, or exclude the account. Untracked accounts are always excluded.
- On **Net Worth**, use **Manual balances** for accounts without an imported value, such as a home or vehicle. Choose the account and date, enter the balance, and save. Direct manual balances can be edited or deleted later; every change supports Undo and appears in Activity. Imported and statement-backed balances remain protected from this editor.
- Use **Add transaction** on an account page to enter money out or money in manually. Enter a positive dollar amount and choose the direction; the form writes the canonical negative/positive ledger sign, confirms the deliberate entry, and records it in Activity with Undo.
- On **Net Worth**, **Add transaction** is limited to brokerage and retirement accounts and records the row as investment activity. Use **Add tax lot** under Holding details when an export does not provide acquisition date and total basis.
- Tax lots are separate from daily holding snapshots. Holding details show institution, account, value, total basis, unrealized gain/loss (latest value minus basis), and the age/count of saved lots. Columns are sortable and the pinned total row sums value, basis, and gain/loss. Compatible Fidelity position exports populate lots when they contain acquisition and cost-basis columns; later imports refresh imported lots without deleting manual lots.
- Open **Lots** to edit acquisition date, quantity, total basis, or note, or to delete a lot. Imported lots can be corrected but may be replaced by a later positions import; all lot edits and deletes support Undo.
- After selecting a net-worth chart range, drag either circular edge handle to refine it. Account rows show six-month balance trends and open account-filtered transaction previews.

## Reconciling an Account

- Open an account and enter the ending balance and date from its bank or card statement under **Statement balance**.
- Saving the first statement balance also anchors that account for net-worth calculations.
- The account badge shows **Reconciled** when the ledger reaches the same balance. If it is off, **Investigate difference** filters the ledger to activity since the preceding checkpoint.
- Imports containing running balances create checkpoints automatically. Existing running-balance history is backfilled when the app starts.
- Statement checkpoints appear in Activity and support Undo. Manual checkpoints take precedence over imported balances for the same account and date.
- Credit-card account pages also verify confirmed payment links. A payment credit with no matching bank-side debit after five days appears as a warning with an investigation shortcut. Detection requires card-payment context such as `PAYMENT FROM`, `ONLINE PAYMENT`, or `AUTOPAY`; fee, interest, return, benefit, reward, and protection descriptions are excluded.
- If a warning is not a payment, choose **Not a payment**. The dismissal appears in Activity and supports Undo. Reclassifying the row as an expense, refund, or another non-payment type dismisses the warning in the same operation.

## Fixing Mistakes and Reviewing Changes

- After an ordinary finance change—including transaction edits, bulk edits, imports, account/category/rule changes, splits, allocations, transfers, or holding updates—the success message includes **Undo** for 10 seconds.
- Open **Activity** in the sidebar to review recent operations. Expand an item to see each changed field's before and after values.
- Select **Undo** on an Activity item to reverse it. Undo actions are also recorded, so selecting **Redo** restores the change.
- If a row was edited again after the selected operation, the app protects the newer work. It offers to undo only rows that have no later conflicts.
- One user action remains one Activity item even when it changes several kinds of records. For example, undoing a category merge restores the category as well as affected transactions, rules, splits, and allocations together.
- Deleted transactions move to **All Accounts → Trash**. From there, restore one or several transactions, or permanently delete them after typing `DELETE`.
- Permanent deletion cannot be undone. Password/session changes and database backup/restore also use their own safety controls rather than Activity undo. Ordinary finance changes remain recoverable through Activity and the undo message.
- In a selected Net Worth range, choose **See asset changes** to open an account-level explanation of the change. It shows each checking, savings, brokerage, or other account's starting value, ending value, and gain/loss. Choose an account to inspect that account's ledger activity for the same dates.
- Financial summary tiles, spending categories, income comparisons, and cash-flow rows use a separate transaction deep-dive drawer. **Open full view** carries the exact account/category/date/type filter into the ledger and displays it as removable chips.
- Spending categories are ranked from largest to smallest. Each bar shows its share of categorized spending and its size relative to the largest category; the spending drawer lists the largest matching transactions first.
- The Spending monthly chart stacks the largest categories in the app's blue palette. Toggle categories in the legend or drag across months to compare a period and open its matching transactions.
- Selecting a parent category includes transactions in its direct child categories, so broad filters such as Food can include Groceries and Restaurants.
- Transaction filters support labels. Bulk edit can change dates or replace labels, and **Select all matching** selects every row matching the current server-side filter, not only the visible page.
- Trash keeps deleted transactions for `PF_TRASH_RETENTION_DAYS` (90 days by default), then removes expired items automatically when the app starts. Restore important mistakes before that window ends.

## Categorized History Sign Cleanup

- The older cleaned spreadsheet can use **charges positive; refunds negative** for credit cards and Venmo. Choose that convention before importing; the app converts it to the ledger standard of negative charges and positive refunds.
- Checking and savings history keeps the normal bank convention: positive deposits and negative withdrawals.
- For history imported before sign normalization was added, open **Settings → Smart import → Normalize previously imported categorized history** and select **Preview cleanup**.
- Review each account's historical date range and any later direct-CSV range before applying. Direct CSV rows are identified by their import source and are never changed by this cleanup. A warning appears if direct rows overlap the historical range, repeat the same bank reference, or if two account records contain mostly the same historical transactions.
- Type `NORMALIZE` and apply. The app first creates a timestamped safety backup, then adjusts active and deleted historical transaction amounts/types, dependent splits and monthly allocations, and corrects Venmo to a cash account. Including deleted history ensures a later restore does not reintroduce the old sign convention. The cleanup appears as one Activity operation and can be undone.

## Replacing a Categorized History Workbook

- A clean replacement must remove the old import lineage rather than move its transactions to Trash. Trashed rows still reserve their source fingerprints and would make the replacement file appear already recorded.
- The constrained maintenance service matches import batches by the exact workbook filename, previews every transaction and dependent record, requires a current preview token plus `PURGE HISTORY`, and records an audit event. It removes matching transactions, staging rows, refund/transfer links, duplicate decisions, dismissals, splits, allocations, holding lots, and import batches while preserving accounts, institutions, categories, rules, snapshots, checkpoints, other batches, and other transactions.
- Create and verify an online SQLite backup immediately before applying the purge. Afterward, restart the app and upload the edited workbook once under **Import → Smart import → Categorized history import**. Choose **Charges are positive; refunds are negative** for the legacy cleaned-history convention, or **Charges are already negative; refunds are positive** only if the workbook itself was converted to canonical signs.
- After import, record the inserted/skipped totals, confirm no unexpected accounts or categories were created, then scan for duplicates and regenerate refund suggestions.

## Automated vs Manual

Automated:

- CSV format detection for supported headers
- row cleanup and normalization
- duplicate detection
- transaction type guesses such as expense, income, refund, or card payment

### Match refunds to expenses

In **Review → Refunds**, choose **Find refunds** to compare positive money-in rows with recent expenses. Confirm a match or choose **Not a match**; either decision appears in Activity and can be undone. The matcher favors the same account, similar merchant text, compatible amounts, and refunds received within 90 days. Obvious card payments, transfers, payroll, and unrelated money-in rows are excluded. To keep Review responsive on large ledgers, each scan replaces stale open suggestions and retains only the 25 highest-confidence matches.

For a manual match, open an expense for editing in the ledger and choose **Link a refund…**. Linked expenses show a `↩ refunded $X` badge and can be found with the **Has refund** filter. Linking only explains the relationship; spending continues to use the ledger's signed amounts, so the refund is not counted twice.
- dashboard and report aggregation

Manual:

- first-time account creation
- account edits when an institution, name, or last-four needs cleanup
- custom category creation or renaming
- choosing which account a CSV belongs to
- confirming categories
- resolving possible duplicates, transfers, and unusual cases
- deciding whether a new category rule should be saved

## How Save Rule Works

Save rule turns one reviewed transaction into a future suggestion.

- It takes the first few cleaned words from the transaction description.
- It stores a "description contains this text" rule with the category and type you selected.
- Future imports that contain the same text are prefilled with that category and transaction type, and stay in review until you confirm them.
- Rules do not rewrite older transactions retroactively.
- After saving a rule, **Apply & confirm this row** handles only the transaction in front of you without a batch preview. You can still optionally apply it to all unreviewed transactions or all previous matching transactions.
- Account-ledger category editing uses the same save-rule control as Review, including an editable description pattern.
- Existing saved rules are also listed in the Review Inbox with the same apply options.
- Applying a rule to existing transactions sets the category and type and marks those transactions confirmed, since you chose to run the rule deliberately.
- Saved rules can be edited or deleted later through the rules API, so a mistaken rule is never permanent.
- If multiple rules match, lower priority numbers run first. The default priority is 100.
- Card payment and Transfer rules intentionally have no category. They classify and confirm matching rows while clearing any stale category, so moving money between your own accounts is not counted as spending.
- Clicking an account in the left navigation opens a fresh account ledger and clears search/date/category/type chips. Investigation and drill-down links keep the filters they intentionally construct.

## Brokerage Files With Multiple Accounts

Some brokerage exports contain positions for multiple accounts, such as taxable brokerage, IRA, Roth IRA, HSA, or 401k windows.

Recommended setup:

- Create one app account for each real-world investment account.
- Use the same institution name for accounts that come from the same brokerage.
- Add last-four digits when available.
- Upload the multi-account brokerage CSV through one account at that institution.

During import, brokerage rows are routed to sibling accounts at the same institution when the CSV account number matches an account last-four or the CSV account name matches an account display name. If the app cannot confidently match a row, it assigns it to the selected upload account and includes an import warning.

Fidelity `Portfolio_Positions` exports use three logical destinations in this app: Individual rows go to Individual Brokerage, Health Savings Account rows go to HSA, and both Amazon 401(k) Plan and BrokerageLink rows go to 401K. The Amazon 401(k) row whose description is exactly `BROKERAGELINK` is an aggregate of the detailed BrokerageLink positions and is ignored. Symbol-bearing `HELD IN` rows such as `FDRXX**` money market and `FCASH**` cash are real holdings and use Current value. Header capitalization is not significant.

## Why Account Creation Is Manual First

Bank CSV files are inconsistent. Some include account numbers, some include only partial identifiers, and some include no reliable account identity at all. For privacy and accuracy, v1 requires the user to create or choose the account before importing.

Later, the app can safely add account suggestions:

- recognize repeated filenames
- match known headers to saved presets
- infer last-four digits when a file contains them
- suggest a likely account but still ask for confirmation

The safest future behavior is suggested account matching, not silent account creation.

## Ledger-Wide Duplicate Scan

- In **Review**, choose **Scan ledger for duplicates** to check existing history, including rows that were not flagged when originally imported.
- Results are grouped as cross-source history/CSV overlap, exact duplicates, probable duplicates, or mirrored-sign artifacts. Queue-wide removal remains restricted to safe exact/cross-source reimports. For other exact and probable results, select reviewed pairs on the current page and apply one bulk **Keep both** decision; selected exact pairs may also be removed after a confirmation preview, while probable pairs cannot be bulk-deleted.
- The queue is loaded 25 pairs at a time and can be filtered by result type. The bulk actions are intentionally narrower than “all exact”: they act only when the source reference also matches or when the pair is an exact categorized-history/bank overlap.
- **Keep existing** leaves the established ledger facts in place and moves the redundant imported rows to Trash. **Use new imports** applies the newest imported bank facts and import-source label to the established records before retiring the redundant rows; keeping the established record identity preserves categories, notes, labels, splits, allocations, and links.
- Both bulk directions open a confirmation preview showing the complete queue-wide pair count, affected accounts, selected and retired sources, and the signed ledger-balance adjustment. Confirmation uses a preview token and is rejected if the queue changes before submission. The resulting operation is undoable from Activity.
- An opposite-sign pair is not automatically wrong. It may be a duplicated sign-normalization result, or it may be a real refund/reversal. **Remove positive copy** keeps the negative expense and moves the positive row to Trash; use it only after verifying that no money was actually returned.
- When opposite-sign rows match the strict intentional-history pattern—same account/date/description, equal opposite amounts, expense plus refund, matching category, and the same categorized-history batch—**Link historical refunds** previews the complete scope and total refund value. Confirmation creates explicit refund links and badges without deleting rows or changing spending, cash flow, balances, or net worth; the whole action is one Activity operation with Undo.
- **Keep both** is remembered for that normalized pair, so later scans do not ask about it again. Confirmed transfers and refunds are not proposed as duplicates.
- After resolving duplicates on a credit-card account, use the offered transfer-matching rerun so the surviving payment can clear payment verification.

## Payments From Untracked Accounts

- For a stale card-payment warning whose checking-side history is unavailable, choose **Paid from untracked account**.
- Pick an existing untracked account or create one inline. The app creates an equal-and-opposite synthetic transfer row and a confirmed transfer link; it does not add the payment to spending, cash flow, imports, or net worth.
- The action appears in Activity and can be undone. The untracked account can remain as the counterparty for future historical card payments.
