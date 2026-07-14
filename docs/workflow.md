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

2. Add downloaded CSVs to the Import Inbox.
   - Copy files into the local folder shown under Settings → Smart import → Import Inbox.
   - When two accounts produce generic names such as `stmt.csv`, create one subfolder per account and include the last four digits: `boa-checking-1016/stmt.csv` and `boa-checking-6768/stmt.csv`. The scanner searches subfolders and uses the full relative path for account matching.
   - The default folder is `~/PrivateFinance/import-inbox`, outside the source repository. Set `PF_IMPORT_INBOX` to choose another location.
   - The app does not monitor this folder automatically. Select **Scan inbox** when you want it to search for files and stage new matches.
   - A file selected directly in Smart import is staged in this same inbox and review flow; it is no longer committed through a separate path.
   - Files without a confident account match are left untouched and listed for manual Smart import.
   - For an unfamiliar CSV layout, choose its date, description, and amount columns once. This browser remembers the mapping for later files with the same headers.
   - The import preview shows how each amount will be interpreted. Normally, charges/withdrawals are negative and refunds/deposits are positive. If a raw file uses the opposite convention, choose **Reverse detected signs**, preview again, and stage only after the interpretation is correct.

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
   - Source files are never moved or deleted, and confirmed imports are recorded in the mutation journal.
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
   - Use the Overview tabs for Cash Flow, Spending, Income, and Net Worth. The tabs, date range, refresh, and import controls remain visible while the page scrolls.
   - The customizable finance cockpit appears only on Overview. Its account map, cash-flow trend, and top-spending cards provide a high-level summary; dedicated analysis tabs avoid repeating those same cards.

## Net Worth History

- Open the overview and select **Net Worth** in the report tabs.
- Choose **1M**, **6M**, **1Y**, or **Max**. The selected period stays in the page URL so it can be bookmarked.
- Hover over the chart to inspect a day's total.
- Drag across a date range to see the change, percent change, high, and low for that range.
- Select **View transactions** to open the transaction ledger with the chosen dates already applied.
- Select **Clear** or press Escape to remove the range selection.
- Imported running balances and brokerage positions create durable snapshots. Between known balances, the app reconstructs checking and savings history from ledger movements and forward-fills investment values.
- On **Net Worth**, use **Add a manual balance** for accounts without an imported value, such as a home or vehicle. Choose the account and date, enter the balance, and save; the change supports Undo and appears in Activity.
- After selecting a net-worth chart range, drag either circular edge handle to refine it. Account rows show six-month balance trends and open account-filtered transaction previews.

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

## Automated vs Manual

Automated:

- CSV format detection for supported headers
- row cleanup and normalization
- duplicate detection
- transaction type guesses such as expense, income, refund, or card payment
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
- After saving a rule, you can optionally apply it to unreviewed transactions or all previous matching transactions.
- Existing saved rules are also listed in the Review Inbox with the same apply options.
- Applying a rule to existing transactions sets the category and type and marks those transactions confirmed, since you chose to run the rule deliberately.
- Saved rules can be edited or deleted later through the rules API, so a mistaken rule is never permanent.
- If multiple rules match, lower priority numbers run first. The default priority is 100.

## Brokerage Files With Multiple Accounts

Some brokerage exports contain positions for multiple accounts, such as taxable brokerage, IRA, Roth IRA, HSA, or 401k windows.

Recommended setup:

- Create one app account for each real-world investment account.
- Use the same institution name for accounts that come from the same brokerage.
- Add last-four digits when available.
- Upload the multi-account brokerage CSV through one account at that institution.

During import, brokerage rows are routed to sibling accounts at the same institution when the CSV account number matches an account last-four or the CSV account name matches an account display name. If the app cannot confidently match a row, it assigns it to the selected upload account and includes an import warning.

## Why Account Creation Is Manual First

Bank CSV files are inconsistent. Some include account numbers, some include only partial identifiers, and some include no reliable account identity at all. For privacy and accuracy, v1 requires the user to create or choose the account before importing.

Later, the app can safely add account suggestions:

- recognize repeated filenames
- match known headers to saved presets
- infer last-four digits when a file contains them
- suggest a likely account but still ask for confirmation

The safest future behavior is suggested account matching, not silent account creation.
