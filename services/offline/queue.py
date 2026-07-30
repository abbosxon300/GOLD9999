from __future__ import annotations

from typing import Protocol

from services.offline.models import SyncRecord


class SyncQueue(Protocol):
    def enqueue(
        self,
        record: SyncRecord,
    ) -> str:
        """Sync yozuvini navbatga qo‘shadi."""

    def pending(
        self,
        *,
        limit: int = 100,
    ) -> tuple[SyncRecord, ...]:
        """Yuborilmagan yozuvlarni qaytaradi."""

    def claim_pending(
        self,
        *,
        limit: int = 100,
    ) -> tuple[SyncRecord, ...]:
        """
        Yozuvlarni atomik tarzda olib,
        syncing holatiga o‘tkazadi.
        """

    def mark_synced(
        self,
        entity_uuid: str,
    ) -> None:
        """Yozuvni yuborilgan deb belgilaydi."""

    def mark_failed(
        self,
        entity_uuid: str,
        error_message: str,
    ) -> None:
        """Yozuvni xatolik holatiga o‘tkazadi."""

    def mark_conflict(
        self,
        entity_uuid: str,
        error_message: str,
    ) -> None:
        """Yozuvni conflict holatiga o‘tkazadi."""

    def count_by_status(
        self,
        status: str,
    ) -> int:
        """Berilgan holatdagi yozuvlar soni."""

    def reset_stuck_syncing(self) -> int:
        """Uzilib qolgan syncing yozuvlarini qaytaradi."""
