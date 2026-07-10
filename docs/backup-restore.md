# Backup and Restore

The current implementation supports:

- consistent snapshots of the live database using SQLite's online backup API (safe while the app is running)
- backups saved inside the app's `data/backups/` folder (paths outside it are rejected)
- listing existing backups with `GET /api/backups`
- validated restores: the file must be a real SQLite database from the backups folder
- an automatic `pre-restore-<timestamp>.sqlite3` safety copy written before every restore
- audit entries for backup and restore events

Next hardening steps:

- replace raw snapshot files with encrypted archive backups
- add backup retention and a restore verification workflow
- require recent re-authentication before restores and full data exports
