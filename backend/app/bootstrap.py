from sqlalchemy import inspect, text

from .config import settings
from .db import Base, engine, session_scope
from .seed import seed_categories
from .services.snapshots import backfill_net_worth_snapshots
from .services.trash import purge_expired_trash


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        inspector = inspect(connection)
        transaction_columns = {column["name"] for column in inspector.get_columns("transactions")}
        if "user_note" not in transaction_columns:
            connection.execute(text("ALTER TABLE transactions ADD COLUMN user_note TEXT"))
        if "deleted_at" not in transaction_columns:
            connection.execute(text("ALTER TABLE transactions ADD COLUMN deleted_at DATETIME"))
        if "labels" not in transaction_columns:
            connection.execute(text("ALTER TABLE transactions ADD COLUMN labels TEXT"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_transactions_deleted_at ON transactions (deleted_at)"))
        import_batch_columns = {column["name"] for column in inspector.get_columns("import_batches")}
        if "source_path" not in import_batch_columns:
            connection.execute(text("ALTER TABLE import_batches ADD COLUMN source_path TEXT"))
        if "match_confidence" not in import_batch_columns:
            connection.execute(text("ALTER TABLE import_batches ADD COLUMN match_confidence INTEGER NOT NULL DEFAULT 0"))
        if "match_reason" not in import_batch_columns:
            connection.execute(text("ALTER TABLE import_batches ADD COLUMN match_reason TEXT"))
        if "proposed_account_json" not in import_batch_columns:
            connection.execute(text("ALTER TABLE import_batches ADD COLUMN proposed_account_json TEXT NOT NULL DEFAULT '{}'"))
        if "detected_preset" not in import_batch_columns:
            connection.execute(text("ALTER TABLE import_batches ADD COLUMN detected_preset VARCHAR(40)"))
        if "semantic_hash" not in import_batch_columns:
            connection.execute(text("ALTER TABLE import_batches ADD COLUMN semantic_hash VARCHAR(128)"))
        if "sign_convention" not in import_batch_columns:
            connection.execute(text("ALTER TABLE import_batches ADD COLUMN sign_convention VARCHAR(30)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_import_batches_semantic_hash ON import_batches (semantic_hash)"))
        operation_change_columns = {column["name"] for column in inspector.get_columns("operation_changes")}
        if "entity_type" not in operation_change_columns:
            connection.execute(text("ALTER TABLE operation_changes ADD COLUMN entity_type VARCHAR(40)"))
            connection.execute(text("UPDATE operation_changes SET entity_type = (SELECT entity_type FROM operations WHERE operations.id = operation_changes.operation_id) WHERE entity_type IS NULL"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_operation_changes_entity_type ON operation_changes (entity_type)"))
        connection.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS audit_events_no_update
                BEFORE UPDATE ON audit_events
                BEGIN
                  SELECT RAISE(FAIL, 'audit_events is append-only');
                END;
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
                BEFORE DELETE ON audit_events
                BEGIN
                  SELECT RAISE(FAIL, 'audit_events is append-only');
                END;
                """
            )
        )
    with session_scope() as db:
        seed_categories(db)
        backfill_net_worth_snapshots(db)
        purge_expired_trash(db, retention_days=settings.trash_retention_days)
    settings.import_inbox_dir.expanduser().mkdir(parents=True, exist_ok=True)
