from __future__ import annotations

from typing import Protocol

from services.offline.models import (
    PullBatch,
    SyncRecord,
    SyncResult,
)


class SyncApi(Protocol):
    def push(
        self,
        records: tuple[SyncRecord, ...],
    ) -> tuple[SyncResult, ...]:
        """Mahalliy o‘zgarishlarni serverga yuboradi."""

    def pull(
        self,
        *,
        cursor: str | None,
        limit: int = 100,
    ) -> PullBatch:
        """
        Serverdagi yangi o‘zgarishlar batchini qaytaradi.

        PullBatch quyidagilarni saqlaydi:
        - remote changes
        - keyingi cursor
        - batch identifikatori
        - yana batch mavjudligi
        """


__all__ = [
    "SyncApi",
]
