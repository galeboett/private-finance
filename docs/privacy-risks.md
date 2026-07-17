# Privacy Risks and Data-Handling Assessment

**Assessment date:** 2026-07-15  
**Scope:** Local imports, statement PDF extraction, application storage, backups, exports, browser access, repository hygiene, and the current Windows filesystem permissions.

**Status note (2026-07-16):** Phase 11 asset editing and the first Phase 12 navigation/query-cache checkpoint do not change the storage or network boundaries assessed here. TanStack Query caches API responses only in browser memory; the application still has no runtime statement-upload or analytics integration. Reassess after any remote-access, connector, encrypted-storage, retention, or backup-format change.

This is a point-in-time review of the implemented code and local deployment, not a penetration test. Reassess it whenever storage, import, authentication, or deployment behavior changes.

## Executive summary

Private Finance is genuinely local-first. The backend binds to `127.0.0.1`, import parsing runs in the local Python process, and the application code contains no analytics, telemetry, advertising, or third-party statement-upload endpoint. The PDF statement extractor is local text extraction, not cloud OCR.

The primary privacy risk is therefore not intentional Internet transmission. It is plaintext data at rest and the number of local copies retained in the Import Inbox, SQLite database, staging records, undo history, backups, and downloaded exports.

The current implementation is appropriate for a trusted, single-user development computer. It should not yet be described as vault-grade storage for PII because database encryption, strict retention cleanup, owner-only permissions, and hostile-PDF isolation are not implemented.

| Boundary | Current assessment |
|---|---|
| Intentional cloud transmission by the app | Low risk |
| Access from another computer on the network | Low risk under the standard startup script |
| Local malware, administrators, shared Windows users, or a stolen unencrypted disk | Material risk |
| Leftover Inbox files, staging data, backups, and exports | Material risk |
| Malformed or hostile PDF parsing | Moderate risk |

## Import and PDF data flow

### PDF extraction is local and is not OCR

The statement service opens PDF bytes with `pdfplumber` and calls `page.extract_text()` inside the backend process. It searches the extracted text for a statement date and labeled ending balance. It does not send the PDF or extracted text to OpenAI, a bank, an OCR provider, or another external service.

Consequences of this design:

- Digitally generated PDFs with selectable text can be read.
- Image-only or scanned PDFs are rejected and require manual balance entry.
- PDF transaction tables are not imported; the feature extracts only the statement date and balance candidates.
- A malformed PDF is parsed with the permissions of the main backend process because the parser is not isolated in a restricted subprocess.

### Inbox PDF

An Inbox PDF is read directly from the configured local Import Inbox. The app does not make another managed copy of the PDF, but the original remains in the Inbox until the user moves or deletes it. The import batch retains its filename, hashes, and, for Inbox imports, its source path.

### Browser PDF upload

A manually uploaded PDF is not copied into the app's `.staged` directory. Starlette uses a 1 MB spooling threshold for multipart uploads: smaller uploads stay in memory, while larger uploads can temporarily spill to an operating-system temporary file. The temporary upload is closed at the end of the request.

### What is retained after PDF confirmation

The full PDF and full extracted text are not stored in the database after a successful PDF confirmation. The app retains:

- the account;
- statement date and confirmed balance;
- filename and file fingerprints;
- import and audit metadata;
- the selected balance/date labels used to improve later statements;
- the resulting statement checkpoint and net-worth snapshot.

The temporary PDF staging row is deleted upon successful confirmation. A discarded preview currently changes status without deleting its staging row, so extracted preview data can remain in the database.

### CSV and OFX/QFX retention differs

CSV and OFX/QFX imports retain considerably more source-derived information than PDF confirmations:

- raw and normalized imported rows are stored in `staging_rows`;
- committed transactions and holdings retain normalized financial data and lineage;
- Activity/undo records can retain full before-and-after versions of affected entities;
- manual non-PDF uploads are copied into `.staged` and are not currently removed automatically after confirmation or discard;
- Inbox source files remain wherever the user placed them.

## Protections currently implemented

### Local network boundary

- The standard startup script launches Uvicorn on `127.0.0.1`, not all network interfaces.
- Allowed hosts are limited to `127.0.0.1` and `localhost`.
- Browser origins are restricted to the local production and development origins.
- Host and Origin middleware helps prevent malicious websites and DNS-rebinding-style access.

### Application authentication

- Initial passwords must contain at least 12 characters.
- Passwords are hashed with Argon2 rather than stored directly.
- Session tokens expire after 30 minutes of inactivity and have a 12-hour absolute lifetime.
- Session cookies are `HttpOnly` and `SameSite=Strict`.
- Mutating API requests require a session-specific CSRF token.
- Login attempts are rate-limited.

The cookie is not marked `Secure` because the app uses local HTTP. This is acceptable only while the server remains loopback-only; it is not appropriate for network deployment.

### Repository hygiene

- `backend/data/`, database extensions, logs, test temp folders, and environment files are ignored by Git.
- No CSV, PDF, Excel, OFX/QFX, or SQLite data file was found in the tracked files or Git history during this assessment.

This does not prevent manually written documentation or test fixtures from exposing financial metadata. Tracked files currently contain some real-looking filenames, account suffixes, descriptions, and amounts. Anyone with repository access can see that metadata even though the underlying statements are not committed.

### Export safety

- Transaction CSV output escapes spreadsheet-formula prefixes.
- Sensitive export and backup endpoints require an authenticated session.
- Transaction CSV is assembled in memory rather than first written to a backend plaintext file.

The resulting browser downloads are still ordinary unencrypted files.

## Material privacy and security risks

### 1. Plaintext database and backups

The live SQLite database and app-created backups are not encrypted. An application password protects API access but does not protect the files themselves. A user or process with filesystem access can open SQLite directly and bypass the application password.

At assessment time, the live database was approximately 25 MB and several plaintext backups existed under `backend/data`. Backups improve recoverability but multiply the number of complete sensitive copies.

### 2. Extensive database retention

At assessment time, the database contained:

- 11,693 staging rows;
- 50,960 Activity/undo change records;
- 5,610 audit events.

This means the database contains materially more history than the currently visible ledger. Raw import rows, source descriptions, prior entity states, filenames, and paths may appear in several places.

### 3. Incomplete staging cleanup

Discarding a pending import currently marks its batch as discarded but does not delete associated staging rows. Manual non-PDF uploads copied into `.staged` also are not automatically removed after confirmation or discard. This creates unnecessary retention and makes a user-facing “discard” weaker than permanent removal.

### 4. Deleted-data remanence

SQLite `secure_delete` is disabled. When rows are deleted, their old bytes are not deliberately overwritten and may remain until the storage is reused or the database is compacted. Enabling secure deletion later would not by itself erase all historical remnants; a controlled cleanup and `VACUUM` would be needed after retention changes and backup review.

### 5. Filesystem permissions are not owner-exclusive

During this assessment:

- the Import Inbox was readable by the local `CodexSandboxUsers` group;
- `backend/data` was modifiable by that group;
- two unresolved local Windows security identifiers retained modify entries on `backend/data`;
- the current Windows user, administrators, and `SYSTEM` had their expected access.

These are local permissions, not Internet exposure. They do mean the data is not isolated exclusively to the owner's Windows identity. Removing the Codex group without planning would interfere with the current Codex development workflow; production data should eventually be separated from development-tool access.

### 6. Small pre-login metadata exposure

`/api/bootstrap` does not require authentication and returns unanchored account display names as part of the net-worth notice. It does not return balances or transactions, but account names can themselves contain PII. The endpoint should return only setup state before login, with account-specific data moved behind authentication.

### 7. Plaintext exports and source copies

The following are ordinary unencrypted files:

- source statements in the Import Inbox;
- `.staged` non-PDF upload copies;
- SQLite backups;
- app-data JSON exports;
- transaction CSV exports;
- manually copied database backups.

These files can remain in Downloads, Windows backups, antivirus indexes, search indexes, or cloud-synchronized folders. `PF_IMPORT_INBOX` can point anywhere, and the app does not detect or warn when that location is cloud-synced.

### 8. Hostile PDF and dependency risk

The 10 MB import limit reduces simple resource exhaustion, but PDF parsing has no page-count, parsing-time, or document-complexity limit. The parser runs in the main backend process rather than an isolated worker. In addition, Python dependencies are specified as compatible version ranges without an exact lock file, so rebuilding the environment can install different dependency versions.

### 9. Browser and local-process boundary

Authenticated financial data is rendered in the browser and returned through local HTTP APIs. A malicious browser extension with suitable access, malware running as the user, an administrator, or another process able to read the app's files can access the data. Loopback networking protects against other computers; it does not protect against compromise of the local account.

No Content Security Policy or explicit `Cache-Control: no-store` policy is currently applied to sensitive responses.

## How unintended disclosure could occur

The most plausible accidental disclosure paths are:

1. A database, backup, export, or original statement is copied into email, cloud storage, or an unencrypted backup.
2. A real filename, account suffix, transaction description, or amount is added to tracked documentation or tests and pushed to the Git remote.
3. A shared Windows account, malware, local administrator, development tool, or browser extension reads local files or page content.
4. A user points `PF_IMPORT_INBOX` at OneDrive, Dropbox, Google Drive, a network share, or another automatically synchronized location.
5. Old data remains in staging rows, Activity history, discarded batches, `.staged`, SQLite free space, or redundant backups after the visible transaction is removed.
6. A hostile PDF exploits or exhausts an in-process parser dependency.

## Recommended remediation

### Priority 0: complete before calling the app secure PII storage

1. **Define and enforce retention.** Delete staging rows and managed `.staged` files after confirmation or discard unless a documented feature requires them. Provide a separate, explicit “retain raw import history” option if needed.
2. **Protect data at rest.** Use BitLocker/device encryption immediately. Evaluate SQLCipher or another supported database-encryption design for the live database and encrypted archives for backups.
3. **Protect bootstrap metadata.** Require authentication before returning account names or other account-specific bootstrap data.
4. **Separate production data from development access.** Move production data into an owner-only location and deliberately grant only the identities required to run the app.

### Priority 1: defense in depth

5. Enable SQLite secure deletion for future deletes and design a one-time, backup-aware cleanup and compaction procedure for historical remnants.
6. Delete managed source copies on confirmation/discard and add an optional, clearly explained action for removing confirmed Inbox source files.
7. Add encrypted export/backup options and recent-password confirmation before full-data export or database restore.
8. Parse PDFs in a restricted subprocess with file-size, page-count, complexity, memory, and execution-time limits.
9. Lock Python dependency versions and add routine dependency-vulnerability review.
10. Add `Cache-Control: no-store`, a restrictive Content Security Policy, and other standard browser security headers.
11. Replace real financial metadata in tracked tests and documentation with synthetic examples. If sensitive metadata has already been published, evaluate coordinated Git-history rewriting separately rather than deleting local files and assuming the history is clean.
12. Warn when the database, backup folder, Inbox, or export destination appears to be cloud-synchronized or broadly accessible.

## Recommended user practices until hardening is complete

- Use a strong Windows password and enable BitLocker/device encryption.
- Do not use a shared Windows login for this app.
- Keep `PrivateFinance`, `backend/data`, backups, and exports outside OneDrive, Dropbox, Google Drive, and network shares unless encrypted syncing is intentional.
- Delete or archive source statements and browser exports securely when they are no longer needed.
- Maintain only the number of backups required for recovery and protect every copy as if it were the live database.
- Use a dedicated browser profile without untrusted extensions for highly sensitive data.
- Use synthetic or redacted statements when asking development assistants to diagnose import behavior.

## Separate privacy boundary: development assistants

The application's local import guarantees do not automatically extend to Codex or another assistant. Importing a file through the app's local UI stays within the local application. Attaching a statement to a task, asking an assistant to open its local path, or pasting extracted contents into a conversation is a separate data-processing action. Users who require strict local-only handling should provide synthetic or redacted reproductions for development work.

## Related documentation

- [Threat model](threat-model.md)
- [Local statement ingestion](statement-ingestion.md)
- [Backup and restore](backup-restore.md)
- [Running and local configuration](../README.md#running-locally)
