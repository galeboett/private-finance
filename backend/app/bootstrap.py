from .config import settings
from .db import engine, session_scope
from .migrations import run_migrations
from .seed import seed_categories
from .services.reconciliation import backfill_statement_checkpoints
from .services.snapshots import backfill_net_worth_snapshots
from .services.trash import purge_expired_trash
from .services.account_identifiers import backfill_account_identifiers


def initialize_database() -> None:
    with engine.begin() as connection:
        run_migrations(connection)
    with session_scope() as db:
        seed_categories(db)
        backfill_net_worth_snapshots(db)
        backfill_statement_checkpoints(db)
        backfill_account_identifiers(db)
        purge_expired_trash(db, retention_days=settings.trash_retention_days)
    settings.import_inbox_dir.expanduser().mkdir(parents=True, exist_ok=True)
