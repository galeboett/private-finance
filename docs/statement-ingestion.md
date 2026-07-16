# Local statement ingestion

Private Finance can read three kinds of local files from the Import Inbox:

- **CSV** for transactions or positions using the existing presets and saved mappings.
- **OFX/QFX** for transactions, bank-provided `FITID` references, statement balances, and supported investment positions.
- **PDF** for statement date and ending balance only. PDF transaction tables are intentionally not imported.

All parsing happens locally. No statement content is sent to a bank, connector, or cloud service.

## Recommended workflow

1. Download the file from the financial institution.
2. Put it in the Import Inbox shown under **Settings → Import & Accounts**. Account subfolders or the account's last four digits in the filename improve matching.
3. Click **Scan inbox**.
4. Review the matched account and preview.
5. Confirm the import. OFX/QFX writes transactions and available anchors as one undoable Activity operation. PDF confirmation writes only the selected date and balance.

If a PDF contains several labeled balances, the app will not guess. Select the ending or new balance that represents the account at the statement date. Credit-card statement balances are stored as negative liabilities even when the statement prints the amount due as a positive number.

## Where to look for OFX/QFX downloads

Bank portal wording changes, but these exports are normally beside CSV under **Download**, **Export transactions**, or **Download account activity**. Look for **Quicken**, **Web Connect**, **QFX**, or **OFX**.

| Institution | Typical place to look | If OFX/QFX is unavailable |
|---|---|---|
| Bank of America | Account activity → Download → Quicken/Web Connect | Download CSV for transactions and use the statement PDF for the balance anchor. |
| Chase / J.P. Morgan | Account activity → Download account activity → Quicken Web Connect | Use CSV for activity; use a PDF statement or manual balance for the anchor. |
| Citi | Account activity → Export/Download → Quicken or QFX | Use Citi CSV plus the statement PDF balance preview. |
| American Express | Statements & Activity → Download transactions; check available file formats | Amex availability varies; CSV plus PDF balance is fully supported. |
| Fidelity | Account or portfolio download menus; look for OFX/QFX for the selected account | Continue using positions CSVs for holdings and PDF/manual balances where offered. |
| Venmo | Transaction statement download | Venmo CSV remains the supported source; it supplies stable transaction IDs. |

## What is saved

For OFX/QFX, the app saves normalized financial rows, import lineage, and the original file fingerprint. The source file stays where the user put it.

For PDF statements, the app saves only:

- account;
- statement date;
- confirmed balance;
- the selected balance label for that institution, so the next statement can prefer the same label;
- import fingerprint and audit history.

The app does not copy a manually uploaded PDF into its managed staging folder. An inbox PDF remains the user's file and is read only during scanning.

## Failure behavior

- Scanned-image PDFs with no extractable text are rejected with a prompt to use manual statement balance entry.
- Missing dates or multiple balance candidates remain editable previews; nothing is committed automatically.
- An OFX transaction without a date, amount, or `FITID` is skipped with a warning.
- Re-importing the same OFX transaction skips it by `FITID`. Reusing a `FITID` with different facts creates a duplicate-review warning instead of silently overwriting the ledger.
