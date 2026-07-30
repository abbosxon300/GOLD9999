from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class SyncRecord:
    entity_type: str
    entity_uuid: str
    operation: str
    payload: Mapping[str, Any]
    device_uuid: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class SyncResult:
    success: bool
    status: str
    message: str
    remote_version: int | None = None


@dataclass(frozen=True, slots=True)
class SyncConflict:
    entity_type: str
    entity_uuid: str
    local_payload: Mapping[str, Any]
    remote_payload: Mapping[str, Any]
    detected_at: datetime
