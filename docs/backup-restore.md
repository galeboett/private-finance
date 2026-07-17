# Backup and restore

Private Finance has two different recovery formats. They are not interchangeable.

## SQLite database backups

The current implementation supports:

- consistent snapshots of the live database using SQLite's online backup API (safe while the app is running)
- backups saved inside the app's `data/backups/` folder (paths outside it are rejected)
- listing existing backups with `GET /api/backups`
- validated restores: the file must be a real SQLite database from the backups folder
- an automatic `pre-restore-<timestamp>.sqlite3` safety copy written before every restore
- audit entries for backup and restore events

These operations are available through authenticated backend endpoints:

- `GET /api/backups` lists database backups and their local folder.
- `POST /api/backups?destination=<filename>` creates an online SQLite backup. A bare filename such as `pre-history-rebuild-2026-07-14.sqlite3` is resolved inside the configured backup folder.
- `POST /api/backups/restore?source=<filename>` validates and restores a listed SQLite backup after creating a pre-restore safety copy.

The current Settings screen does not expose this SQLite backup list or restore action. It exposes the separate JSON app-data format described below. Do not rename a JSON export to `.sqlite3` or attempt to restore it through the database endpoint.

## JSON app-data export

**Settings → App data export** downloads a JSON representation that the app can import through the adjacent **Import backup** action. Importing this file replaces app-domain data through the application import workflow; it is not a byte-for-byte SQLite backup.

Before a high-risk data rebuild, prefer a verified SQLite database backup. A JSON export is useful as an additional portable copy, not a substitute for the database safety snapshot.

## Remaining hardening

- replace raw snapshot files with encrypted archive backups
- add backup retention and a restore verification workflow
- require recent re-authentication before restores and full data exports
