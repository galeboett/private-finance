from sqlalchemy import create_engine, inspect, text

from app.migrations import run_migrations


def test_fresh_database_applies_baseline_once():
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        assert run_migrations(connection) == [1, 2, 3]
        assert run_migrations(connection) == []
        versions = connection.execute(
            text("SELECT version, description FROM schema_version")
        ).all()

    assert [version.version for version in versions] == [1, 2, 3]
    assert "Baseline" in versions[0].description
    assert "transactions" in inspect(engine).get_table_names()


def test_baseline_upgrades_legacy_category_rules_without_losing_rows():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE categories (id INTEGER NOT NULL PRIMARY KEY)"))
        connection.execute(
            text(
                """
                CREATE TABLE category_rules (
                  id INTEGER NOT NULL PRIMARY KEY,
                  category_id INTEGER NOT NULL REFERENCES categories(id),
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
        connection.execute(text("INSERT INTO categories (id) VALUES (1)"))
        connection.execute(
            text(
                """
                INSERT INTO category_rules
                VALUES (1, 1, 100, 'raw_description', 'COFFEE', 'expense',
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
        )

        assert run_migrations(connection) == [1, 2, 3]
        category_column = next(
            column
            for column in inspect(connection).get_columns("category_rules")
            if column["name"] == "category_id"
        )
        row_count = connection.execute(text("SELECT COUNT(*) FROM category_rules")).scalar_one()

    assert category_column["nullable"] is True
    assert row_count == 1


def test_baseline_ports_every_legacy_schema_upgrade():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE transactions (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE accounts (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE holding_snapshots (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE import_batches (id INTEGER PRIMARY KEY)"))
        connection.execute(
            text("CREATE TABLE operations (id TEXT PRIMARY KEY, entity_type VARCHAR(40) NOT NULL)")
        )
        connection.execute(
            text("CREATE TABLE operation_changes (id INTEGER PRIMARY KEY, operation_id TEXT NOT NULL)")
        )
        connection.execute(text("CREATE TABLE categories (id INTEGER PRIMARY KEY)"))
        connection.execute(
            text(
                """
                CREATE TABLE category_rules (
                  id INTEGER PRIMARY KEY,
                  category_id INTEGER,
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
        connection.execute(text("CREATE TABLE audit_events (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO operations VALUES ('op-1', 'transaction')"))
        connection.execute(text("INSERT INTO operation_changes VALUES (1, 'op-1')"))

        assert run_migrations(connection) == [1, 2, 3]
        inspector = inspect(connection)

        assert {"user_note", "deleted_at", "labels"}.issubset(
            {column["name"] for column in inspector.get_columns("transactions")}
        )
        assert "net_worth_inclusion" in {
            column["name"] for column in inspector.get_columns("accounts")
        }
        assert "cost_basis_cents" in {
            column["name"] for column in inspector.get_columns("holding_snapshots")
        }
        assert {
            "source_path",
            "match_confidence",
            "match_reason",
            "proposed_account_json",
            "detected_preset",
            "semantic_hash",
            "sign_convention",
        }.issubset({column["name"] for column in inspector.get_columns("import_batches")})
        assert connection.execute(
            text("SELECT entity_type FROM operation_changes WHERE id = 1")
        ).scalar_one() == "transaction"
        trigger_names = {
            row.name
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
            )
        }

    assert {"audit_events_no_update", "audit_events_no_delete"}.issubset(trigger_names)


def test_runner_rejects_a_database_from_a_newer_application():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE schema_version (
                  version INTEGER NOT NULL PRIMARY KEY,
                  applied_at TEXT NOT NULL,
                  description TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text("INSERT INTO schema_version VALUES (999, CURRENT_TIMESTAMP, 'future')")
        )

        try:
            run_migrations(connection)
        except RuntimeError as error:
            assert "newer than this application" in str(error)
        else:
            raise AssertionError("A newer database schema must not be opened by an older app")
