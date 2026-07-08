# Threat Model

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
- backup and restore path
- formula-safe CSV export

## Gaps To Harden Next

- SQLCipher integration instead of plain SQLite fallback
- encrypted backup archive rather than file copy
- recent re-auth for exports and settings changes
- zip-bomb and XLSX parser hardening beyond CSV-first support

