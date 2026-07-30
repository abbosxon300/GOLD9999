from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone

from services.offline.cursor import SyncCursorState

ConnectionFactory = Callable[[], sqlite3.Connection]


def utc_now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat(timespec="microseconds")


def _required_text(
    value: object,
    field_name: str,
) -> str:
    if not isinstance(value, str):
        raise TypeError(
            f"{field_name} matn bo‘lishi kerak"
        )

    normalized = value.strip()

    if not normalized:
        raise ValueError(
            f"{field_name} bo‘sh bo‘lishi mumkin emas"
        )

    return normalized


def _optional_text(
    value: object,
    field_name: str,
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise TypeError(
            f"{field_name} matn bo‘lishi kerak"
        )

    return value.strip() or None


def _normalized_datetime(
    value: object,
    field_name: str,
) -> datetime | None:
    if value is None:
        return None

    if not isinstance(value, datetime):
        raise TypeError(
            f"{field_name} datetime yoki None bo‘lishi kerak"
        )

    if value.tzinfo is None:
        return value.replace(
            tzinfo=timezone.utc
        )

    return value


def _parsed_datetime(
    value: str | None,
    field_name: str,
) -> datetime | None:
    if value is None:
        return None

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"{field_name} noto‘g‘ri datetime"
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed


def _validate_connection(
    connection: sqlite3.Connection | None,
) -> sqlite3.Connection | None:
    if (
        connection is not None
        and not isinstance(connection, sqlite3.Connection)
    ):
        raise TypeError(
            "connection sqlite3.Connection yoki None "
            "bo‘lishi kerak"
        )

    return connection


def _row_to_cursor(
    row: sqlite3.Row,
) -> SyncCursorState:
    updated_at = _parsed_datetime(
        row["updated_at"],
        "updated_at",
    )

    if updated_at is None:
        raise ValueError(
            "updated_at bo‘sh bo‘lishi mumkin emas"
        )

    return SyncCursorState(
        scope=row["scope"],
        cursor_value=row["cursor_value"],
        last_batch_id=row["last_batch_id"],
        last_pulled_at=_parsed_datetime(
            row["last_pulled_at"],
            "last_pulled_at",
        ),
        updated_at=updated_at,
    )


class SQLiteSyncCursorStore:
    def __init__(
        self,
        connection_factory: ConnectionFactory,
    ) -> None:
        if not callable(connection_factory):
            raise TypeError(
                "connection_factory callable bo‘lishi kerak"
            )

        self._connection_factory = connection_factory

    def _acquire_connection(
        self,
        connection: sqlite3.Connection | None,
    ) -> tuple[sqlite3.Connection, bool]:
        caller_connection = _validate_connection(
            connection
        )

        if caller_connection is not None:
            return caller_connection, False

        return self._connection_factory(), True

    def get(
        self,
        scope: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> SyncCursorState | None:
        normalized_scope = _required_text(
            scope,
            "scope",
        )

        con, owns_connection = self._acquire_connection(
            connection
        )
        previous_row_factory = con.row_factory
        con.row_factory = sqlite3.Row

        try:
            row = con.execute(
                """
                SELECT
                    scope,
                    cursor_value,
                    last_batch_id,
                    last_pulled_at,
                    updated_at
                FROM sync_cursor
                WHERE scope=?
                LIMIT 1
                """,
                (normalized_scope,),
            ).fetchone()
        finally:
            con.row_factory = previous_row_factory

            if owns_connection:
                con.close()

        if row is None:
            return None

        return _row_to_cursor(row)

    def save(
        self,
        scope: str,
        cursor_value: str | None,
        *,
        last_batch_id: str | None = None,
        last_pulled_at: datetime | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> SyncCursorState:
        normalized_scope = _required_text(
            scope,
            "scope",
        )
        normalized_cursor = _optional_text(
            cursor_value,
            "cursor_value",
        )
        normalized_batch_id = _optional_text(
            last_batch_id,
            "last_batch_id",
        )
        normalized_pulled_at = _normalized_datetime(
            last_pulled_at,
            "last_pulled_at",
        )

        pulled_at_iso = (
            normalized_pulled_at.isoformat(
                timespec="microseconds"
            )
            if normalized_pulled_at is not None
            else None
        )
        now = utc_now_iso()

        con, owns_connection = self._acquire_connection(
            connection
        )
        previous_row_factory = con.row_factory
        con.row_factory = sqlite3.Row

        try:
            con.execute(
                """
                INSERT INTO sync_cursor (
                    scope,
                    cursor_value,
                    last_batch_id,
                    last_pulled_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(scope) DO UPDATE SET
                    cursor_value=excluded.cursor_value,
                    last_batch_id=excluded.last_batch_id,
                    last_pulled_at=excluded.last_pulled_at,
                    updated_at=excluded.updated_at
                """,
                (
                    normalized_scope,
                    normalized_cursor,
                    normalized_batch_id,
                    pulled_at_iso,
                    now,
                ),
            )

            row = con.execute(
                """
                SELECT
                    scope,
                    cursor_value,
                    last_batch_id,
                    last_pulled_at,
                    updated_at
                FROM sync_cursor
                WHERE scope=?
                LIMIT 1
                """,
                (normalized_scope,),
            ).fetchone()

            if row is None:
                raise RuntimeError(
                    "Cursor saqlangandan keyin topilmadi"
                )

            if owns_connection:
                con.commit()
        except Exception:
            if owns_connection:
                con.rollback()
            raise
        finally:
            con.row_factory = previous_row_factory

            if owns_connection:
                con.close()

        return _row_to_cursor(row)

    def reset(
        self,
        scope: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> bool:
        normalized_scope = _required_text(
            scope,
            "scope",
        )

        con, owns_connection = self._acquire_connection(
            connection
        )

        try:
            cursor = con.execute(
                """
                DELETE FROM sync_cursor
                WHERE scope=?
                """,
                (normalized_scope,),
            )

            deleted = cursor.rowcount > 0

            if owns_connection:
                con.commit()
        except Exception:
            if owns_connection:
                con.rollback()
            raise
        finally:
            if owns_connection:
                con.close()

        return deleted


__all__ = [
    "SQLiteSyncCursorStore",
]
