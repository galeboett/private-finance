# Backup and restore

Private Finance has two different recovery formats.
They are not interchangeable.

## SQLite database backups

The current implementation supports:

- consistent snapshots of the live database using SQLite's online backup API
- backups saved inside the app's `data/backups/` folder, with paths outside it rejected
- listing existing backups with `GET /api/backups`
- validated restores from the configured backups folder
- an automatic pre-restore safety copy before every restore
- optional `.pfbak` archives encrypted with AES-256-GCM and an Argon2id-derived key
- encrypted pre-restore safety copies when the restored source is encrypted
- audit entries for backup and restore events

These operations are available through authenticated backend endpoints:

- `GET /api/backups` lists database backups and their local folder.
- `POST /api/backups` accepts a JSON body with `destination` and an optional `passphrase`.
- A passphrase of at least 12 characters creates a `.pfbak` encrypted archive; without one, the destination must end in `.sqlite3`.
- `POST /api/backups/restore` accepts a JSON body with `source` and the passphrase required by an encrypted archive.
- Restore requires password re-authentication within the previous five minutes and returns a clear error for an incorrect archive passphrase.

The Settings screen lists both SQLite and encrypted backups and exposes create and restore actions.
Do not rename a JSON or `.pfenc` export to `.sqlite3` or attempt to restore it through the database endpoint.

## Portable app-data export

**Settings → App data export** downloads a JSON representation that the app can import through the adjacent **Import backup** action.
Supplying an archive passphrase creates an AES-256-GCM encrypted `.pfenc` export instead.
Importing either format replaces app-domain data through the application import workflow; it is not a byte-for-byte SQLite backup.
Export and import require password re-authentication within the previous five minutes.

Before a high-risk data rebuild, prefer a verified database backup.
A portable export is useful as an additional copy, not a substitute for the full-fidelity database safety snapshot.

## Live database protection

SQLCipher is not packaged reliably in the supported Windows runtime, so the live SQLite file remains plaintext and the application does not claim otherwise.
Enable Windows device encryption or BitLocker for the volume containing `backend/data/private_finance.sqlite3`.
Encrypted backups and exports protect portable copies, but they do not replace full-disk encryption for the live database.
