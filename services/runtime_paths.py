from __future__ import annotations

import os
from pathlib import Path


ENV_DATA_DIR = "GOLD9999_DATA_DIR"
ENV_DB_PATH = "GOLD9999_DB_PATH"


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def data_directory() -> Path:
    configured = str(
        os.environ.get(
            ENV_DATA_DIR,
            "",
        )
    ).strip()

    if configured:
        return Path(
            configured
        ).expanduser().resolve()

    return project_root()


def database_path() -> Path:
    configured = str(
        os.environ.get(
            ENV_DB_PATH,
            "",
        )
    ).strip()

    if configured:
        return Path(
            configured
        ).expanduser().resolve()

    return data_directory() / "data.db"


def backup_directory() -> Path:
    return data_directory() / "backups"


def ensure_runtime_directories() -> None:
    data_directory().mkdir(
        parents=True,
        exist_ok=True,
    )

    backup_directory().mkdir(
        parents=True,
        exist_ok=True,
    )


__all__ = [
    "ENV_DATA_DIR",
    "ENV_DB_PATH",
    "backup_directory",
    "data_directory",
    "database_path",
    "ensure_runtime_directories",
    "project_root",
]
