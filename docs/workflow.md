# User Workflow

## Goal

The app builds a full personal finance picture by turning account exports into a single reviewed ledger. The ledger then powers cash flow, spending, net worth, and export views.

## Current Workflow

1. Add an account.
   - Create one account for each real-world checking account, savings account, credit card, brokerage account, or retirement account.
   - The account is the container that tells the app where an uploaded file belongs.

2. Upload a CSV for that account.
   - Choose the account first.
   - Select the CSV file from the bank, card issuer, or brokerage.
   - Click Preview.

3. Preview the normalized rows.
   - The app detects the file family from known headers.
   - It shows normalized rows before anything is committed.
   - This step protects the ledger from bad mappings or wrong-account uploads.

4. Commit the import.
   - The app adds new rows to the database.
   - Exact duplicates are skipped.
   - Ambiguous rows stay reviewable instead of being silently changed.

5. Review and categorize.
   - The app can suggest transaction types and categories from rules.
   - The user confirms or corrects those suggestions.
   - Corrections can become future rules.
   - Add private notes when the bank description is vague but you know what the purchase was.

6. Reports update from the ledger.
   - Cash-flow summaries use checking, savings, income, spending, transfers, and card payments.
   - Spending summaries use expense transactions and fixed categories.
   - Net-worth views use account balances and investment snapshots.

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
- Future imports that contain the same text are prefilled with that category and type.
- Matching transactions still stay in review until you confirm them.
- Rules do not rewrite older transactions retroactively.
- If multiple rules match, lower priority numbers run first. The default priority is 100.

## Why Account Creation Is Manual First

Bank CSV files are inconsistent. Some include account numbers, some include only partial identifiers, and some include no reliable account identity at all. For privacy and accuracy, v1 requires the user to create or choose the account before importing.

Later, the app can safely add account suggestions:

- recognize repeated filenames
- match known headers to saved presets
- infer last-four digits when a file contains them
- suggest a likely account but still ask for confirmation

The safest future behavior is suggested account matching, not silent account creation.
