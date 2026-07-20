# Threat Model

For the detailed, point-in-time privacy and data-retention audit, see [Privacy Risks and Data-Handling Assessment](privacy-risks.md).

## In Scope

- malicious websites attempting to reach the localhost app
- malformed or hostile import files
- casual disk access or a lost device
- accidental data loss

## Controls in This Implementation

- localhost `Host` and `Origin` allowlists
- CSRF token checks on mutating routes
- an `HttpOnly`, `SameSite=Strict` session cookie
- config-driven secure cookies through `PF_COOKIE_SECURE`, with automatic secure cookies for HTTPS requests
- login rate limiting
- password re-authentication within five minutes for exports, restores, app-data replacement, and password changes
- a self-only Content Security Policy, clickjacking denial, MIME sniffing denial, referrer suppression, and restrictive browser permissions
- append-only audit events
- backup and restore paths constrained to the configured local backup directory
- optional AES-256-GCM encrypted database backups and portable exports with Argon2id-derived keys
- formula-safe CSV export
- uvicorn access logging disabled by the supported startup script so URLs and query strings are not written to routine logs

## Encryption-at-rest decision

The Windows environment does not have a viable packaged `sqlcipher3` or SQLCipher-enabled APSW runtime, so the application does not claim that its live SQLite file is encrypted.
The implemented fallback encrypts backups and portable exports with AES-256-GCM and an Argon2id-derived key.
Protect the live database with Windows device encryption or BitLocker, keep the Windows account password-protected, and do not place the `data/` folder in an unencrypted sync service.
If SQLCipher packaging becomes reliable, migrate by making an automatic pre-migration backup, copying into an encrypted database, verifying it, and only then swapping files.

## Remaining Gaps

- live database encryption remains dependent on operating-system full-disk encryption
- zip-bomb and XLSX parser hardening beyond CSV-first support
