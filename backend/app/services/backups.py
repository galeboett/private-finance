from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from ..config import settings

SQLITE_MAGIC = b"SQLite format 3\x00"


class BackupError(ValueError):
    """Raised when a backup or restore request is invalid."""


def _backup_root() -> Path:
    root = Path(settings.backup_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_backup_destination(destination: str | None) -> Path:
    """Resolve a user-supplied destination to a path inside the backups directory.

    Accepts a bare filename or a relative path; rejects anything that escapes
    the configured backup directory. Defaults to a timestamped filename.
    """
    root = _backup_root()
    if not destination or not destination.strip():
        name = f"private-finance-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3"
        return root / name
    candidate = Path(destination.strip())
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise BackupError("Backups must be saved inside the app's backups folder (data/backups)")
    if resolved.is_dir():
        raise BackupError("Backup destination must be a file name, not a folder")
    return resolved


def resolve_restore_source(source: str) -> Path:
    root = _backup_root()
    if not source or not source.strip():
        raise BackupError("Choose a backup file to restore")
    candidate = Path(source.strip())
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise BackupError("Restores are only allowed from the app's backups folder (data/backups)")
    if not resolved.is_file():
        raise BackupError("That backup file does not exist")
    return resolved


def _validate_sqlite_file(path: Path) -> None:
    with path.open("rb") as handle:
        magic = handle.read(len(SQLITE_MAGIC))
    if magic != SQLITE_MAGIC:
        raise BackupError("That file is not a SQLite database backup")


def list_backups() -> list[dict]:
    root = _backup_root()
    entries = []
    for path in sorted(root.glob("*.sqlite3"), key=lambda item: item.stat().st_mtime, reverse=True):
        stat = path.stat()
        entries.append(
            {
                "name": path.name,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            }
        )
    return entries


def create_backup(destination: Path) -> Path:
    """Create a consistent backup of the live database using SQLite's backup API.

    Unlike a raw file copy, this is safe while the database is in use.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_path = Path(settings.db_path)
    if not source_path.exists():
        raise BackupError("No database file exists yet")
    # `with sqlite3.connect(...)` only scopes transactions; closing() releases the file handles.
    with closing(sqlite3.connect(source_path)) as source, closing(sqlite3.connect(destination)) as target:
        source.backup(target)
    return destination


def restore_backup(source: Path) -> Path:
    """Restore the database from a validated backup.

    Writes an automatic pre-restore safety copy, disposes SQLAlchemy's engine so no
    open connections hold the old file, then swaps the database in place.
    Returns the path of the pre-restore safety copy.
    """
    _validate_sqlite_file(source)

    root = _backup_root()
    safety_copy = root / f"pre-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3"
    db_path = Path(settings.db_path)
    if db_path.exists():
        with closing(sqlite3.connect(db_path)) as live, closing(sqlite3.connect(safety_copy)) as target:
            live.backup(target)

    # Close every pooled connection before replacing the file underneath the engine.
    from ..db import engine

    engine.dispose()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, db_path)
    return safety_copy
