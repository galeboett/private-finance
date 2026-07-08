from __future__ import annotations

import shutil
from pathlib import Path

from ..config import settings


def create_backup(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(settings.db_path, destination)
    return destination


def restore_backup(source: Path) -> None:
    shutil.copy2(source, settings.db_path)

