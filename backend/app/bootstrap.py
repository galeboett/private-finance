from sqlalchemy import inspect, text

from .config import settings
from .db import Base, engine, session_scope
from .seed import seed_categories


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        inspector = inspect(connection)
        transaction_columns = {column["name"] for column in inspector.get_columns("transactions")}
        if "user_note" not in transaction_columns:
            connection.execute(text("ALTER TABLE transactions ADD COLUMN user_note TEXT"))
        if "deleted_at" not in transaction_columns:
            connection.execute(text("ALTER TABLE transactions ADD COLUMN deleted_at DATETIME"))
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
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_import_batches_semantic_hash ON import_batches (semantic_hash)"))
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
    settings.import_inbox_dir.mkdir(parents=True, exist_ok=True)
