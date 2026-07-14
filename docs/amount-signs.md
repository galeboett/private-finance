# Amount sign conventions

## Canonical ledger contract

The ledger stores money moving out as a negative amount and money moving in as a positive amount. Reporting, budgets, cash flow, and net-worth calculations rely on that single rule for every account type.

| Edge | Source convention | Ledger normalization |
|---|---|---|
| Bank and card CSV presets | Institution-specific | Preset parser converts to negative charges/withdrawals and positive refunds/deposits |
| Saved import sign profile | Detected signs or reversed detected signs | The user’s saved account-and-preset choice is applied before staging |
| Categorized history | `charges_positive` or `canonical` | Spend-account history is converted to the canonical ledger convention at commit |
| Legacy categorized history | Pre-normalization ledger rows | The preview-first maintenance action updates transactions, splits, and allocations in one undoable operation |
| Manual transaction form | User chooses Money out or Money in and enters a positive amount | Money out is stored negative; money in is stored positive |

## Import sign profiles

Each profile belongs to an account and CSV preset. On preview, the app uses an explicit user profile ahead of any detected profile and shows that it is using the saved choice. Creating or changing a profile is journaled and can be undone from Activity.

When no profile exists, plausibility checks inspect the parsed rows:

- For a credit card, at least 85% of non-payment rows should be negative after normalization.
- For checking and savings, payroll-like deposits should be positive.

Heuristics never flip signs or save a profile. They only prompt when the file strongly contradicts the detected convention. The prompt shows example rows under detected and reversed interpretations; only the user’s answer is saved.

Every later import is checked again. If a bank changes its export format and the new sign distribution conflicts with the saved profile, the batch stays in review with an anomaly warning rather than being committed automatically.

## Cleanup guidance

For previously imported categorized history, run the sign cleanup preview in Settings. Review its cutoff and overlap warnings, then spot-check a known purchase, refund, and monthly category total for each spend account. The cleanup is one undoable operation.

If a category total is inverted after cleanup, investigate the edge normalization—the selected CSV preset or source profile—rather than changing reporting math. Spending totals already net positive refunds against negative expenses.

Refund links explain which original expense a positive refund offsets; they do not add or subtract a second reporting amount. Confirming a refund link changes the money-in row to type `refund` and copies the original expense category onto it, so the existing signed amounts net within the same category. One expense can have several partial refunds, while each refund can link to only one expense. If linked refunds exceed the original expense, the app warns and requires an explicit confirmation because price-adjustment credits can occasionally be larger than the charge.

## Manual entries

The shared manual transaction form accepts an unsigned dollar amount plus a clear **Money out / Money in** choice. It writes the canonical sign, confirms the deliberate entry, and journals creation so Activity can undo it. Money out on ordinary accounts requires a category; brokerage and retirement entries are typed as investment flows and remain categoryless.

Holding acquisition date and cost basis are not ledger cash-flow signs. They are stored separately as tax lots, while holding snapshots continue to represent market value on a date.
