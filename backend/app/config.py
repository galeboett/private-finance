from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "private-finance"
    host: str = "127.0.0.1"
    port: int = 8000
    allowed_hosts: list[str] = ["127.0.0.1", "localhost"]
    allowed_origins: list[str] = ["http://127.0.0.1:8000", "http://localhost:8000", "http://127.0.0.1:5173", "http://localhost:5173"]
    db_path: Path = Path("data/private_finance.sqlite3")
    session_cookie_name: str = "pf_session"
    csrf_header_name: str = "x-csrf-token"
    idle_timeout_minutes: int = 30
    absolute_session_hours: int = 12
    login_attempt_limit: int = 5
    login_backoff_seconds: int = 300
    import_file_size_limit_mb: int = 10
    # Keep imported financial statements outside the repository by default.
    # PF_IMPORT_INBOX can still point at any user-selected location. The older
    # PF_IMPORT_INBOX_DIR spelling remains accepted for compatibility.
    import_inbox_dir: Path = Field(
        default=Path.home() / "PrivateFinance" / "import-inbox",
        validation_alias=AliasChoices("PF_IMPORT_INBOX", "PF_IMPORT_INBOX_DIR"),
    )
    trash_retention_days: int = 90
    backup_dir: Path = Path("data/backups")
    # Display name that identifies the owner in Venmo exports ("From"/"To" columns).
    # Used only to phrase the imported description; direction still falls back to the amount sign.
    venmo_self_name: str | None = None

    model_config = SettingsConfigDict(env_prefix="PF_", env_file=".env", extra="ignore")


settings = Settings()

