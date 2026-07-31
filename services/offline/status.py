from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ConnectionStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    SYNCING = "syncing"
    ERROR = "error"


@dataclass(frozen=True)
class OfflineStatus:
    connection: ConnectionStatus
    pending_count: int
    failed_count: int
    last_sync_at: str | None
    message: str | None
    syncing_count: int = 0
    conflict_count: int = 0

    @property
    def has_attention_items(self) -> bool:
        return self.failed_count > 0 or self.conflict_count > 0

    @property
    def is_busy(self) -> bool:
        return self.syncing_count > 0

    @property
    def is_clean(self) -> bool:
        return (
            self.pending_count == 0
            and self.syncing_count == 0
            and self.failed_count == 0
            and self.conflict_count == 0
        )
