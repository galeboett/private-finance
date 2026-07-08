# Import Preset Notes

Current preset families implemented:

- `card_reference`
- `card_activity`
- `checking_running_balance`
- `brokerage_positions`

Each preset should eventually carry:

- header signature
- explicit column mappings
- row classification rules
- date parsing rules
- amount/sign parsing
- optional running balance handling

The current implementation auto-detects these sample families from shared headers and normalizes them into staging rows before commit.

