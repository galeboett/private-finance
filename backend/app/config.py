from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "private-finance"
    host: str = "127.0.0.1"
    port: int = 8000
    allowed_hosts: list[str] = ["127.0.0.1", "localhost"]
    allowed_origins: list[str] = ["http://127.0.0.1:8000", "http://localhost:8000", "http://127.0.0.1:5173", "http://localhost:5173"]
    db_path: Path = Path("data/private_finance.sqlite3")
    session_cookie_name: str = "pf_session"
    cookie_secure: bool = False
    csrf_header_name: str = "x-csrf-token"
    idle_timeout_minutes: int = 30
    absolute_session_hours: int = 12
    login_attempt_limit: int = 5
    login_backoff_seconds: int = 300
    import_file_size_limit_mb: int = 10
    # Keep imported financial statements outside the repository by default.
    # PF_IMPORT_INBOX can point at any user-selected location.
    import_inbox_dir: Path = Field(
        default=Path.home() / "PrivateFinance" / "import-inbox",
        validation_alias="PF_IMPORT_INBOX",
    )
    trash_retention_days: int = 90
    backup_dir: Path = Path("data/backups")
    reauthentication_minutes: int = 5
    # Display name that identifies the owner in Venmo exports ("From"/"To" columns).
    # Used only to phrase the imported description; direction still falls back to the amount sign.
    venmo_self_name: str | None = None

    model_config = SettingsConfigDict(env_prefix="PF_", env_file=".env", extra="ignore")


settings = Settings()

