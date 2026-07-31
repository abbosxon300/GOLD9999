from __future__ import annotations

from collections.abc import Callable
import sqlite3
from typing import Any

from .constants import (
    SYNC_STATUS_FAILED,
    SYNC_STATUS_PENDING,
    SYNC_STATUS_SYNCING,
)
from .sqlite_conflict import SQLiteSyncConflictStore
from .sqlite_log import SQLiteSyncLog
from .sqlite_queue import SQLiteSyncQueue
from .status import ConnectionStatus, OfflineStatus


ConnectionFactory = Callable[[], sqlite3.Connection]


class OfflineStatusService:
    """Offline sync holatini bitta markazdan yig‘uvchi servis."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._queue = SQLiteSyncQueue(connection_factory)
        self._log = SQLiteSyncLog(connection_factory)
        self._conflicts = SQLiteSyncConflictStore(connection_factory)

    def get_status(
        self,
        *,
        connection: ConnectionStatus = ConnectionStatus.ONLINE,
        message: str | None = None,
    ) -> OfflineStatus:
        pending_count = self._queue.count_by_status(
            SYNC_STATUS_PENDING
        )
        syncing_count = self._queue.count_by_status(
            SYNC_STATUS_SYNCING
        )
        failed_count = self._queue.count_by_status(
            SYNC_STATUS_FAILED
        )
        conflict_count = self._conflicts.count(
            resolved=False
        )
        last_sync_at = self._get_last_sync_at()

        effective_connection = self._resolve_connection(
            requested=connection,
            syncing_count=syncing_count,
            failed_count=failed_count,
        )

        effective_message = message or self._build_message(
            connection=effective_connection,
            pending_count=pending_count,
            syncing_count=syncing_count,
            failed_count=failed_count,
            conflict_count=conflict_count,
        )

        return OfflineStatus(
            connection=effective_connection,
            pending_count=pending_count,
            syncing_count=syncing_count,
            failed_count=failed_count,
            conflict_count=conflict_count,
            last_sync_at=last_sync_at,
            message=effective_message,
        )

    def recent_logs(
        self,
        *,
        limit: int = 20,
    ) -> tuple[Any, ...]:
        safe_limit = max(1, min(int(limit), 100))
        return self._log.recent(limit=safe_limit)

    def open_conflicts(
        self,
        *,
        limit: int = 20,
    ) -> tuple[Any, ...]:
        safe_limit = max(1, min(int(limit), 100))
        return self._conflicts.open_conflicts(
            limit=safe_limit
        )

    def _get_last_sync_at(self) -> str | None:
        recent = self._log.recent(limit=1)

        if not recent:
            return None

        entry = recent[0]

        for field_name in (
            "created_at",
            "occurred_at",
            "logged_at",
            "synced_at",
        ):
            value = getattr(entry, field_name, None)

            if value:
                return str(value)

        return None

    @staticmethod
    def _resolve_connection(
        *,
        requested: ConnectionStatus,
        syncing_count: int,
        failed_count: int,
    ) -> ConnectionStatus:
        if requested == ConnectionStatus.OFFLINE:
            return ConnectionStatus.OFFLINE

        if syncing_count > 0:
            return ConnectionStatus.SYNCING

        if failed_count > 0:
            return ConnectionStatus.ERROR

        return requested

    @staticmethod
    def _build_message(
        *,
        connection: ConnectionStatus,
        pending_count: int,
        syncing_count: int,
        failed_count: int,
        conflict_count: int,
    ) -> str:
        if connection == ConnectionStatus.OFFLINE:
            return "Internet aloqasi mavjud emas."

        if syncing_count > 0:
            return (
                f"{syncing_count} ta yozuv "
                "sinxronlanmoqda."
            )

        if failed_count > 0 or conflict_count > 0:
            return (
                f"{failed_count} ta xato, "
                f"{conflict_count} ta konflikt mavjud."
            )

        if pending_count > 0:
            return (
                f"{pending_count} ta yozuv "
                "sinxronlash navbatida."
            )

        return "Barcha ma’lumotlar sinxronlangan."
