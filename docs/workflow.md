# User Workflow

## Goal

The app builds a full personal finance picture by turning account exports into a single reviewed ledger. The ledger then powers cash flow, spending, net worth, and export views.

## Current Workflow

1. Add an account.
   - Create one account for each real-world checking account, savings account, credit card, brokerage account, or retirement account.
   - The account is the container that tells the app where an uploaded file belongs.

2. Add downloaded CSVs to the Import Inbox.
   - Copy files into the local folder shown under Settings → Smart import → Import Inbox.
   - Select **Scan inbox**. The app fingerprints each file, detects its format, and matches it to an existing account.
   - Files without a confident account match are left untouched and listed for manual Smart import.

3. Preview the normalized rows.
   - The app detects the file family from known headers.
   - It shows normalized rows before anything is committed.
   - This step protects the ledger from bad mappings or wrong-account uploads.

4. Confirm the staged import.
   - Confirm or discard each pending batch from the Import Inbox.
   - The app adds new rows to the database.
   - Exact duplicates are skipped.
   - Ambiguous rows stay reviewable instead of being silently changed.
   - Source files are never moved or deleted, and confirmed imports are recorded in the mutation journal.
   - Download suffixes such as `(1)` do not determine duplicates. The app compares exact bytes and normalized parsed rows, so renamed/reformatted copies are skipped while genuinely changed files are staged.

5. Review and categorize.
   - The app can suggest transaction types and categories from rules.
   - The user confirms or corrects those suggestions.
   - Corrections can become future rules.
   - Add private notes when the bank description is vague but you know what the purchase was.

6. Reports update from the ledger.
   - Cash-flow summaries use checking, savings, income, spending, transfers, and card payments.
   - Spending summaries use expense transactions and fixed categories.
   - Net-worth views use account balances and investment snapshots.

## Net Worth History

- Open the overview and select **Net Worth** in the report tabs.
- Choose **1M**, **6M**, **1Y**, or **Max**. The selected period stays in the page URL so it can be bookmarked.
- Hover over the chart to inspect a day's total.
- Drag across a date range to see the change, percent change, high, and low for that range.
- Select **View transactions** to open the transaction ledger with the chosen dates already applied.
- Select **Clear** or press Escape to remove the range selection.
- Imported running balances and brokerage positions create durable snapshots. Between known balances, the app reconstructs checking and savings history from ledger movements and forward-fills investment values.

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
