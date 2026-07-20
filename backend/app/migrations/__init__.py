from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Connection, text

from . import m0001_baseline, m0002_session_reauthentication, m0003_pdf_extraction_templates


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    upgrade: Callable[[Connection], None]


MIGRATIONS = (
    Migration(1, "Baseline the current schema and legacy schema upgrades", m0001_baseline.upgrade),
    Migration(2, "Track recent password re-authentication on sessions", m0002_session_reauthentication.upgrade),
    Migration(3, "Add positional PDF extraction templates", m0003_pdf_extraction_templates.upgrade),
)

# Keep this at the highest version ever shipped, including migrations whose
# implementation has been retired after every collaborator database passed it.
CURRENT_SCHEMA_VERSION = 3


def run_migrations(connection: Connection) -> list[int]:
    """Apply every pending migration once and return the applied versions."""

    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
              version INTEGER NOT NULL PRIMARY KEY,
              applied_at TEXT NOT NULL,
              description TEXT NOT NULL
            )
            """
        )
    )
    applied_versions = set(connection.execute(text("SELECT version FROM schema_version")).scalars())
    newer_versions = {version for version in applied_versions if version > CURRENT_SCHEMA_VERSION}
    if newer_versions:
        versions = ", ".join(str(version) for version in sorted(newer_versions))
        raise RuntimeError(f"Database schema version is newer than this application: {versions}")

    newly_applied: list[int] = []
    for migration in MIGRATIONS:
        if migration.version in applied_versions:
            continue
        migration.upgrade(connection)
        connection.execute(
            text(
                """
                INSERT INTO schema_version (version, applied_at, description)
                VALUES (:version, :applied_at, :description)
                """
            ),
            {
                "version": migration.version,
                "applied_at": datetime.now(UTC).isoformat(),
                "description": migration.description,
            },
        )
        newly_applied.append(migration.version)
    return newly_applied
