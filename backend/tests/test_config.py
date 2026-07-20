from pathlib import Path

from app.config import Settings


def test_import_inbox_defaults_outside_the_repository():
    default = Settings.model_fields["import_inbox_dir"].default
    assert default == Path.home() / "PrivateFinance" / "import-inbox"
    assert "personal-finance" not in str(default).casefold()


def test_import_inbox_accepts_only_current_environment_name(tmp_path, monkeypatch):
    current = tmp_path / "current"
    legacy = tmp_path / "legacy"
    monkeypatch.setenv("PF_IMPORT_INBOX", str(current))
    monkeypatch.setenv("PF_IMPORT_INBOX_DIR", str(legacy))
    assert Settings(_env_file=None).import_inbox_dir == current

    monkeypatch.delenv("PF_IMPORT_INBOX")
    assert Settings(_env_file=None).import_inbox_dir == Path.home() / "PrivateFinance" / "import-inbox"
