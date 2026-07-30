from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SyncCursorState:
    scope: str
    cursor_value: str | None
    last_batch_id: str | None
    last_pulled_at: datetime | None
    updated_at: datetime


class SyncCursorStore(Protocol):
    def get(
        self,
        scope: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> SyncCursorState | None:
        """Berilgan sync scope cursor holatini qaytaradi."""

    def save(
        self,
        scope: str,
        cursor_value: str | None,
        *,
        last_batch_id: str | None = None,
        last_pulled_at: datetime | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> SyncCursorState:
        """
        Cursor holatini yaratadi yoki yangilaydi.

        Caller connection bersa, transaction callerga tegishli
        bo‘ladi va Store commit/rollback/close qilmaydi.
        """

    def reset(
        self,
        scope: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> bool:
        """
        Berilgan scope cursor holatini o‘chiradi.

        Caller connection bersa, transaction callerga tegishli
        bo‘ladi.
        """


__all__ = [
    "SyncCursorState",
    "SyncCursorStore",
]
