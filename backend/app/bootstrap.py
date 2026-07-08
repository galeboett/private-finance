from sqlalchemy import text

from .db import Base, engine, session_scope
from .seed import seed_categories


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
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

