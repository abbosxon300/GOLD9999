from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol


@dataclass(frozen=True, slots=True)
class SyncLogEntry:
    direction: str
    device_uuid: str
    success: bool
    started_at: datetime
    finished_at: datetime
    entity_type: str | None = None
    entity_uuid: str | None = None
    queue_uuid: str | None = None
    status_code: int | None = None
    message: str | None = None
    request_payload: Mapping[str, Any] | None = None
    response_payload: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class StoredSyncLog:
    log_uuid: str
    direction: str
    device_uuid: str
    success: bool
    started_at: datetime
    finished_at: datetime
    created_at: datetime
    entity_type: str | None = None
    entity_uuid: str | None = None
    queue_uuid: str | None = None
    status_code: int | None = None
    message: str | None = None
    request_payload: Mapping[str, Any] | None = None
    response_payload: Mapping[str, Any] | None = None


class SyncLogStore(Protocol):
    def record(
        self,
        entry: SyncLogEntry,
    ) -> str:
        """Sync log yozuvini saqlaydi."""

    def recent(
        self,
        *,
        limit: int = 100,
    ) -> tuple[StoredSyncLog, ...]:
        """Oxirgi sync log yozuvlarini qaytaradi."""

    def count(
        self,
        *,
        success: bool | None = None,
        direction: str | None = None,
    ) -> int:
        """Filtr bo‘yicha loglar sonini qaytaradi."""
