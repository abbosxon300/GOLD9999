from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from services.offline.engine import SyncEngine
from services.runtime_paths import database_path
from services.offline.http_api import HttpSyncApi
from services.offline.schema import (
    ensure_offline_sync_schema,
    validate_offline_sync_schema,
)
from services.offline.pull_runner import (
    run_remote_pull,
)
from services.offline.sqlite_conflict import (
    SQLiteSyncConflictStore,
)
from services.offline.sqlite_cursor import (
    SQLiteSyncCursorStore,
)
from services.offline.sqlite_log import SQLiteSyncLog
from services.offline.sqlite_queue import SQLiteSyncQueue


DEFAULT_LIMIT = 100
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 0.25

ENV_SYNC_URL = "OFFLINE_SYNC_URL"
ENV_SYNC_TOKEN = "OFFLINE_SYNC_TOKEN"
ENV_DEVICE_UUID = "OFFLINE_DEVICE_UUID"
ENV_DB_PATH = "OFFLINE_DB_PATH"


def _project_db_path() -> Path:
    return database_path()


def _required_text(
    value: str | None,
    *,
    field_name: str,
) -> str:
    if value is None:
        raise RuntimeError(
            f"{field_name} environment o‘zgaruvchisi "
            "o‘rnatilmagan"
        )

    normalized = value.strip()

    if not normalized:
        raise RuntimeError(
            f"{field_name} environment o‘zgaruvchisi "
            "bo‘sh bo‘lishi mumkin emas"
        )

    return normalized


def _positive_integer(
    value: int,
    *,
    field_name: str,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"{field_name} integer bo‘lishi kerak"
        )

    if value <= 0:
        raise ValueError(
            f"{field_name} musbat bo‘lishi kerak"
        )

    return value


def _positive_number(
    value: float,
    *,
    field_name: str,
) -> float:
    if isinstance(value, bool) or not isinstance(
        value,
        (int, float),
    ):
        raise TypeError(
            f"{field_name} son bo‘lishi kerak"
        )

    normalized = float(value)

    if normalized <= 0:
        raise ValueError(
            f"{field_name} musbat bo‘lishi kerak"
        )

    return normalized


@dataclass(frozen=True, slots=True)
class SyncRunnerConfig:
    db_path: Path
    base_url: str
    token: str
    device_uuid: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    retry_backoff_seconds: float = (
        DEFAULT_RETRY_BACKOFF_SECONDS
    )

    def __post_init__(self) -> None:
        db_path = Path(self.db_path).expanduser().resolve()

        if not db_path.exists():
            raise FileNotFoundError(
                f"Offline database topilmadi: {db_path}"
            )

        if not db_path.is_file():
            raise RuntimeError(
                f"Offline database fayl emas: {db_path}"
            )

        base_url = _required_text(
            self.base_url,
            field_name="base_url",
        ).rstrip("/")

        token = _required_text(
            self.token,
            field_name="token",
        )

        device_uuid = _required_text(
            self.device_uuid,
            field_name="device_uuid",
        )

        timeout_seconds = _positive_number(
            self.timeout_seconds,
            field_name="timeout_seconds",
        )

        max_attempts = _positive_integer(
            self.max_attempts,
            field_name="max_attempts",
        )

        retry_backoff_seconds = _positive_number(
            self.retry_backoff_seconds,
            field_name="retry_backoff_seconds",
        )

        object.__setattr__(self, "db_path", db_path)
        object.__setattr__(self, "base_url", base_url)
        object.__setattr__(self, "token", token)
        object.__setattr__(
            self,
            "device_uuid",
            device_uuid,
        )
        object.__setattr__(
            self,
            "timeout_seconds",
            timeout_seconds,
        )
        object.__setattr__(
            self,
            "max_attempts",
            max_attempts,
        )
        object.__setattr__(
            self,
            "retry_backoff_seconds",
            retry_backoff_seconds,
        )

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "SyncRunnerConfig":
        env = os.environ if environment is None else environment

        db_path_value = (
            env.get(ENV_DB_PATH)
            or str(_project_db_path())
        )

        return cls(
            db_path=Path(db_path_value),
            base_url=_required_text(
                env.get(ENV_SYNC_URL),
                field_name=ENV_SYNC_URL,
            ),
            token=_required_text(
                env.get(ENV_SYNC_TOKEN),
                field_name=ENV_SYNC_TOKEN,
            ),
            device_uuid=_required_text(
                env.get(ENV_DEVICE_UUID),
                field_name=ENV_DEVICE_UUID,
            ),
        )


def create_connection_factory(
    db_path: Path,
):
    resolved_path = Path(db_path).expanduser().resolve()

    def connection_factory() -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(resolved_path),
            timeout=30,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(
            "PRAGMA foreign_keys = ON"
        )
        connection.execute(
            "PRAGMA busy_timeout = 30000"
        )
        return connection

    return connection_factory


def prepare_offline_database(
    config: SyncRunnerConfig,
) -> None:
    connection_factory = create_connection_factory(
        config.db_path
    )

    connection = connection_factory()

    try:
        ensure_offline_sync_schema(connection)
        validate_offline_sync_schema(connection)
    finally:
        connection.close()


def build_sync_engine(
    config: SyncRunnerConfig,
) -> SyncEngine:
    prepare_offline_database(config)

    connection_factory = create_connection_factory(
        config.db_path
    )

    queue = SQLiteSyncQueue(connection_factory)
    log = SQLiteSyncLog(connection_factory)
    conflicts = SQLiteSyncConflictStore(
        connection_factory
    )

    api = HttpSyncApi(
        config.base_url,
        config.token,
        installation_uuid=config.device_uuid,
        timeout_seconds=config.timeout_seconds,
        max_attempts=config.max_attempts,
        retry_backoff_seconds=(
            config.retry_backoff_seconds
        ),
    )

    return SyncEngine(
        queue=queue,
        api=api,
        log=log,
        conflicts=conflicts,
    )


def run_pending_sync(
    *,
    limit: int = DEFAULT_LIMIT,
    config: SyncRunnerConfig | None = None,
) -> int:
    normalized_limit = _positive_integer(
        limit,
        field_name="limit",
    )

    active_config = (
        config
        if config is not None
        else SyncRunnerConfig.from_environment()
    )

    engine = build_sync_engine(active_config)

    engine.queue.reset_stuck_syncing()

    pushed_count = engine.push_pending(
        limit=normalized_limit
    )

    connection_factory = create_connection_factory(
        active_config.db_path
    )

    cursor_store = SQLiteSyncCursorStore(
        connection_factory
    )

    pulled_count = run_remote_pull(
        api=engine.api,
        cursor_store=cursor_store,
        connection_factory=connection_factory,
        limit=normalized_limit,
    )

    return pushed_count + pulled_count


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "GOLD9999 offline queue yozuvlarini "
            "remote serverga yuboradi."
        )
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=(
            "Bir ishga tushishda yuboriladigan "
            "maksimal queue yozuvlari soni."
        ),
    )

    return parser


def main() -> int:
    parser = _build_argument_parser()
    arguments = parser.parse_args()

    try:
        synced_count = run_pending_sync(
            limit=arguments.limit
        )
    except Exception as exc:
        print(
            "OFFLINE SYNC FAILED:",
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    print(
        "OFFLINE SYNC OK:",
        f"synced={synced_count}",
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_LIMIT",
    "ENV_DB_PATH",
    "ENV_DEVICE_UUID",
    "ENV_SYNC_TOKEN",
    "ENV_SYNC_URL",
    "SyncRunnerConfig",
    "build_sync_engine",
    "create_connection_factory",
    "prepare_offline_database",
    "run_pending_sync",
]
