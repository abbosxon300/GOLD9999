from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ConnectionStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    SYNCING = "syncing"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class OfflineStatus:
    connection: ConnectionStatus
    pending_count: int
    failed_count: int
    last_sync_at: str | None = None
    message: str | None = None
