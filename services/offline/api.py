from __future__ import annotations

from typing import Protocol

from services.offline.models import SyncRecord, SyncResult


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
    ) -> tuple[SyncRecord, ...]:
        """Serverdagi yangi o‘zgarishlarni oladi."""
