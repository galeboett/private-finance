from pathlib import Path
import sqlite3

import pytest

from app.config import settings
from app.services.backups import (
    BackupError,
    create_backup,
    list_backups,
    resolve_backup_destination,
    resolve_restore_source,
    restore_backup,
)


@pytest.fixture()
def backup_dir(tmp_path, monkeypatch):
    root = tmp_path / "backups"
    monkeypatch.setattr(settings, "backup_dir", root)
    return root


def test_resolve_backup_destination_defaults_to_timestamped_file(backup_dir):
    resolved = resolve_backup_destination(None)
    assert resolved.parent == backup_dir.resolve()
    assert resolved.suffix == ".sqlite3"


def test_resolve_backup_destination_accepts_bare_filename(backup_dir):
    resolved = resolve_backup_destination("weekly.sqlite3")
    assert resolved == backup_dir.resolve() / "weekly.sqlite3"


def test_resolve_backup_destination_rejects_path_escape(backup_dir):
    with pytest.raises(BackupError):
        resolve_backup_destination("../outside.sqlite3")
    with pytest.raises(BackupError):
        resolve_backup_destination("/etc/passwd")


def test_resolve_restore_source_requires_existing_file_inside_backups(backup_dir):
    with pytest.raises(BackupError):
        resolve_restore_source("missing.sqlite3")
    with pytest.raises(BackupError):
        resolve_restore_source("../elsewhere.sqlite3")


def test_restore_rejects_non_sqlite_files(backup_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", tmp_path / "db.sqlite3")
    backup_dir.mkdir(parents=True, exist_ok=True)
    bogus = backup_dir / "not-a-db.sqlite3"
    bogus.write_bytes(b"definitely not sqlite")
    with pytest.raises(BackupError):
        restore_backup(bogus)


def test_list_backups_orders_newest_first(backup_dir):
    backup_dir.mkdir(parents=True, exist_ok=True)
    older = backup_dir / "older.sqlite3"
    newer = backup_dir / "newer.sqlite3"
    older.write_bytes(b"SQLite format 3\x00")
    newer.write_bytes(b"SQLite format 3\x00")
    import os
    import time

    now = time.time()
    os.utime(older, (now - 100, now - 100))
    os.utime(newer, (now, now))

    names = [entry["name"] for entry in list_backups()]
    assert names == ["newer.sqlite3", "older.sqlite3"]


def test_encrypted_backup_round_trip_and_wrong_passphrase(backup_dir, tmp_path, monkeypatch):
    live = tmp_path / "live.sqlite3"
    with sqlite3.connect(live) as connection:
        connection.execute("CREATE TABLE secret_rows (value TEXT NOT NULL)")
        connection.execute("INSERT INTO secret_rows VALUES ('private ledger value')")
    monkeypatch.setattr(settings, "db_path", live)
    encrypted = resolve_backup_destination("weekly.pfbak", encrypted=True)

    create_backup(encrypted, "correct horse battery staple")

    assert encrypted.read_bytes()[:16] != b"SQLite format 3\x00"
    assert b"private ledger value" not in encrypted.read_bytes()
    with pytest.raises(BackupError, match="incorrect|damaged"):
        restore_backup(encrypted, "wrong passphrase value")

    with sqlite3.connect(live) as connection:
        connection.execute("DELETE FROM secret_rows")
    restore_backup(encrypted, "correct horse battery staple")
    with sqlite3.connect(live) as connection:
        assert connection.execute("SELECT value FROM secret_rows").fetchone()[0] == "private ledger value"
