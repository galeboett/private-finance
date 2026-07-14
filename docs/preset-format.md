# Import Preset Notes

Current preset families implemented:

- `card_reference`
- `card_activity`
- `checking_running_balance`
- `brokerage_positions`
- `brokerage_positions_compact` (metadata lines followed by Symbol, Qty, Price, and Market Value)
- `jpm_brokerage_positions`
- `citi_checking`
- `citi_card_activity`
- `amex_activity`
- `venmo_activity`
- `generic_mapped`

Each preset should eventually carry:

- header signature
- explicit column mappings
- row classification rules
- date parsing rules
- amount/sign parsing
- optional running balance handling

The current implementation auto-detects these sample families from shared headers and normalizes them into staging rows before commit.
