from sqlalchemy import inspect, text

from .config import settings
from .db import Base, engine, session_scope
from .seed import seed_categories
from .services.reconciliation import backfill_statement_checkpoints
from .services.fidelity import repair_fidelity_holding_history
from .services.duplicate_scan import migrate_keep_both_decisions
from .services.snapshots import backfill_net_worth_snapshots
from .services.trash import purge_expired_trash


def migrate_category_rules_for_optional_category(connection) -> None:
    category_rule_columns = {column["name"]: column for column in inspect(connection).get_columns("category_rules")}
    if not category_rule_columns.get("category_id") or category_rule_columns["category_id"]["nullable"]:
        return
    connection.execute(
        text(
            """
            CREATE TABLE category_rules_v2 (
              id INTEGER NOT NULL PRIMARY KEY,
              category_id INTEGER REFERENCES categories (id),
              priority INTEGER NOT NULL,
              field_name VARCHAR(40) NOT NULL,
              match_text VARCHAR(255) NOT NULL,
              suggested_transaction_type VARCHAR(40) NOT NULL,
              created_at DATETIME NOT NULL,
              updated_at DATETIME NOT NULL
            )
            """
        )
    )
    connection.execute(text("INSERT INTO category_rules_v2 SELECT id, category_id, priority, field_name, match_text, suggested_transaction_type, created_at, updated_at FROM category_rules"))
    connection.execute(text("DROP TABLE category_rules"))
    connection.execute(text("ALTER TABLE category_rules_v2 RENAME TO category_rules"))


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
        account_columns = {column["name"] for column in inspector.get_columns("accounts")}
        if "net_worth_inclusion" not in account_columns:
            connection.execute(text("ALTER TABLE accounts ADD COLUMN net_worth_inclusion VARCHAR(20) NOT NULL DEFAULT 'auto'"))
        holding_snapshot_columns = {column["name"] for column in inspector.get_columns("holding_snapshots")}
        if "cost_basis_cents" not in holding_snapshot_columns:
            connection.execute(text("ALTER TABLE holding_snapshots ADD COLUMN cost_basis_cents INTEGER"))
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
        migrate_category_rules_for_optional_category(connection)
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
        backfill_statement_checkpoints(db)
        repair_fidelity_holding_history(db)
        migrate_keep_both_decisions(db)
        purge_expired_trash(db, retention_days=settings.trash_retention_days)
    settings.import_inbox_dir.expanduser().mkdir(parents=True, exist_ok=True)
