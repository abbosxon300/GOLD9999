from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol

CONFLICT_RESOLUTION_MANUAL = "manual"
CONFLICT_RESOLUTION_USE_LOCAL = "use_local"
CONFLICT_RESOLUTION_USE_REMOTE = "use_remote"

CONFLICT_RESOLUTIONS = frozenset(
    {
        CONFLICT_RESOLUTION_MANUAL,
        CONFLICT_RESOLUTION_USE_LOCAL,
        CONFLICT_RESOLUTION_USE_REMOTE,
    }
)


@dataclass(frozen=True, slots=True)
class SyncConflictEntry:
    entity_type: str
    entity_uuid: str
    local_payload: Mapping[str, Any]
    remote_payload: Mapping[str, Any]
    local_device_uuid: str
    detected_at: datetime
    remote_device_uuid: str | None = None
    local_version: int | None = None
    remote_version: int | None = None


@dataclass(frozen=True, slots=True)
class StoredSyncConflict:
    conflict_uuid: str
    entity_type: str
    entity_uuid: str
    local_payload: Mapping[str, Any]
    remote_payload: Mapping[str, Any]
    local_device_uuid: str
    detected_at: datetime
    resolution: str
    resolved: bool
    created_at: datetime
    updated_at: datetime
    remote_device_uuid: str | None = None
    local_version: int | None = None
    remote_version: int | None = None
    resolved_payload: Mapping[str, Any] | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None


class SyncConflictStore(Protocol):
    def record(
        self,
        conflict: SyncConflictEntry,
    ) -> str:
        ...

    def open_conflicts(
        self,
        *,
        limit: int = 100,
    ) -> tuple[StoredSyncConflict, ...]:
        ...

    def get(
        self,
        conflict_uuid: str,
    ) -> StoredSyncConflict | None:
        ...

    def resolve(
        self,
        conflict_uuid: str,
        *,
        resolution: str,
        resolved_payload: Mapping[str, Any],
        resolved_by: str,
    ) -> None:
        ...

    def count(
        self,
        *,
        resolved: bool | None = None,
    ) -> int:
        ...


__all__ = [
    "CONFLICT_RESOLUTION_MANUAL",
    "CONFLICT_RESOLUTION_USE_LOCAL",
    "CONFLICT_RESOLUTION_USE_REMOTE",
    "CONFLICT_RESOLUTIONS",
    "StoredSyncConflict",
    "SyncConflictEntry",
    "SyncConflictStore",
]
