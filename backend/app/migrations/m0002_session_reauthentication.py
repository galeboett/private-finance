from sqlalchemy import Connection, inspect, text


def upgrade(connection: Connection) -> None:
    columns = {column["name"] for column in inspect(connection).get_columns("session_tokens")}
    if "reauthenticated_at" not in columns:
        connection.execute(text("ALTER TABLE session_tokens ADD COLUMN reauthenticated_at DATETIME"))
