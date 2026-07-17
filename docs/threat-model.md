# Threat Model

For the detailed, point-in-time privacy and data-retention audit, see [Privacy Risks and Data-Handling Assessment](privacy-risks.md).

## In Scope

- malicious websites attempting to reach the localhost app
- malformed or hostile import files
- casual disk access or lost device
- accidental data loss

## Controls in This Implementation

- localhost `Host` and `Origin` allowlists
- CSRF token checks on mutating routes
- `HttpOnly` `SameSite=Strict` session cookie
- login rate limiting
- append-only audit events
- backup and restore paths constrained to the configured local backup directory
- formula-safe CSV export

## Gaps To Harden Next

- database encryption (for example SQLCipher) instead of the current plaintext SQLite database
- encrypted backup archive rather than file copy
- recent re-auth for exports and settings changes
- zip-bomb and XLSX parser hardening beyond CSV-first support
