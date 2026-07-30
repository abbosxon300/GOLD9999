from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from services.offline.constants import (
    SYNC_STATUS_CONFLICT,
    SYNC_STATUS_FAILED,
    SYNC_STATUS_PENDING,
    SYNC_STATUS_SYNCED,
    SYNC_STATUS_SYNCING,
    SYNC_STATUSES,
    SYNC_OPERATIONS,
)
from services.offline.models import SyncRecord
from services.offline.serializer import (
    deserialize_payload,
    serialize_payload,
)

ConnectionFactory = Callable[[], sqlite3.Connection]


def utc_now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat(timespec="microseconds")


def new_queue_uuid() -> str:
    return str(uuid.uuid4())


def _normalize_required_text(
    value: object,
    *,
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


def _parse_datetime(
    value: str,
    *,
    field_name: str,
) -> datetime:
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


class SQLiteSyncQueue:
    def __init__(
        self,
        connection_factory: ConnectionFactory,
    ) -> None:
        if not callable(connection_factory):
            raise TypeError(
                "connection_factory callable bo‘lishi kerak"
            )

        self._connection_factory = (
            connection_factory
        )

    def enqueue(
        self,
        record: SyncRecord,
    ) -> str:
        if not isinstance(record, SyncRecord):
            raise TypeError(
                "record SyncRecord bo‘lishi kerak"
            )

        entity_type = _normalize_required_text(
            record.entity_type,
            field_name="entity_type",
        )
        entity_uuid = _normalize_required_text(
            record.entity_uuid,
            field_name="entity_uuid",
        )
        device_uuid = _normalize_required_text(
            record.device_uuid,
            field_name="device_uuid",
        )
        operation = _normalize_required_text(
            record.operation,
            field_name="operation",
        )

        if operation not in SYNC_OPERATIONS:
            raise ValueError(
                f"Noto‘g‘ri operation: {operation}"
            )

        if not isinstance(
            record.occurred_at,
            datetime,
        ):
            raise TypeError(
                "occurred_at datetime bo‘lishi kerak"
            )

        occurred_at = record.occurred_at

        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(
                tzinfo=timezone.utc
            )

        queue_uuid = new_queue_uuid()
        now = utc_now_iso()

        con = self._connection_factory()

        try:
            con.execute(
                """
                INSERT INTO sync_queue (
                    queue_uuid,
                    entity_type,
                    entity_uuid,
                    operation,
                    payload_json,
                    device_uuid,
                    status,
                    attempt_count,
                    occurred_at,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    queue_uuid,
                    entity_type,
                    entity_uuid,
                    operation,
                    serialize_payload(
                        record.payload
                    ),
                    device_uuid,
                    SYNC_STATUS_PENDING,
                    occurred_at.isoformat(
                        timespec="microseconds"
                    ),
                    now,
                    now,
                ),
            )

            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

        return queue_uuid

    def pending(
        self,
        *,
        limit: int = 100,
    ) -> tuple[SyncRecord, ...]:
        if not isinstance(limit, int):
            raise TypeError(
                "limit integer bo‘lishi kerak"
            )

        if limit <= 0:
            raise ValueError(
                "limit musbat bo‘lishi kerak"
            )

        con = self._connection_factory()
        con.row_factory = sqlite3.Row

        try:
            rows = con.execute(
                """
                SELECT
                    entity_type,
                    entity_uuid,
                    operation,
                    payload_json,
                    device_uuid,
                    occurred_at
                FROM sync_queue
                WHERE status IN (?, ?)
                  AND (
                      next_attempt_at IS NULL
                      OR next_attempt_at <= ?
                  )
                ORDER BY id ASC
                LIMIT ?
                """,
                (
                    SYNC_STATUS_PENDING,
                    SYNC_STATUS_FAILED,
                    utc_now_iso(),
                    limit,
                ),
            ).fetchall()
        finally:
            con.close()

        return tuple(
            SyncRecord(
                entity_type=row["entity_type"],
                entity_uuid=row["entity_uuid"],
                operation=row["operation"],
                payload=deserialize_payload(
                    row["payload_json"]
                ),
                device_uuid=row["device_uuid"],
                occurred_at=_parse_datetime(
                    row["occurred_at"],
                    field_name="occurred_at",
                ),
            )
            for row in rows
        )

    def claim_pending(
        self,
        *,
        limit: int = 100,
    ) -> tuple[SyncRecord, ...]:
        if not isinstance(limit, int):
            raise TypeError(
                "limit integer bo‘lishi kerak"
            )

        if limit <= 0:
            raise ValueError(
                "limit musbat bo‘lishi kerak"
            )

        con = self._connection_factory()
        con.row_factory = sqlite3.Row

        try:
            con.execute("BEGIN IMMEDIATE")

            rows = con.execute(
                """
                SELECT
                    id,
                    entity_type,
                    entity_uuid,
                    operation,
                    payload_json,
                    device_uuid,
                    occurred_at
                FROM sync_queue
                WHERE status IN (?, ?)
                  AND (
                      next_attempt_at IS NULL
                      OR next_attempt_at <= ?
                  )
                ORDER BY id ASC
                LIMIT ?
                """,
                (
                    SYNC_STATUS_PENDING,
                    SYNC_STATUS_FAILED,
                    utc_now_iso(),
                    limit,
                ),
            ).fetchall()

            if rows:
                ids = [
                    int(row["id"])
                    for row in rows
                ]

                placeholders = ",".join(
                    "?"
                    for _ in ids
                )

                now = utc_now_iso()

                con.execute(
                    f"""
                    UPDATE sync_queue
                    SET
                        status=?,
                        attempt_count=attempt_count + 1,
                        last_error=NULL,
                        updated_at=?
                    WHERE id IN ({placeholders})
                    """,
                    (
                        SYNC_STATUS_SYNCING,
                        now,
                        *ids,
                    ),
                )

            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

        return tuple(
            SyncRecord(
                entity_type=row["entity_type"],
                entity_uuid=row["entity_uuid"],
                operation=row["operation"],
                payload=deserialize_payload(
                    row["payload_json"]
                ),
                device_uuid=row["device_uuid"],
                occurred_at=_parse_datetime(
                    row["occurred_at"],
                    field_name="occurred_at",
                ),
            )
            for row in rows
        )

    def mark_synced(
        self,
        entity_uuid: str,
    ) -> None:
        normalized_uuid = _normalize_required_text(
            entity_uuid,
            field_name="entity_uuid",
        )

        now = utc_now_iso()
        con = self._connection_factory()

        try:
            cursor = con.execute(
                """
                UPDATE sync_queue
                SET
                    status=?,
                    last_error=NULL,
                    next_attempt_at=NULL,
                    synced_at=?,
                    updated_at=?
                WHERE entity_uuid=?
                  AND status<>?
                """,
                (
                    SYNC_STATUS_SYNCED,
                    now,
                    now,
                    normalized_uuid,
                    SYNC_STATUS_SYNCED,
                ),
            )

            if cursor.rowcount == 0:
                existing = con.execute(
                    """
                    SELECT status
                    FROM sync_queue
                    WHERE entity_uuid=?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (normalized_uuid,),
                ).fetchone()

                if existing is None:
                    raise LookupError(
                        "Sync queue yozuvi topilmadi: "
                        f"{normalized_uuid}"
                    )

            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def mark_failed(
        self,
        entity_uuid: str,
        error_message: str,
    ) -> None:
        normalized_uuid = _normalize_required_text(
            entity_uuid,
            field_name="entity_uuid",
        )
        normalized_error = _normalize_required_text(
            error_message,
            field_name="error_message",
        )

        now = utc_now_iso()
        con = self._connection_factory()

        try:
            cursor = con.execute(
                """
                UPDATE sync_queue
                SET
                    status=?,
                    last_error=?,
                    next_attempt_at=NULL,
                    updated_at=?
                WHERE entity_uuid=?
                  AND status<>?
                """,
                (
                    SYNC_STATUS_FAILED,
                    normalized_error,
                    now,
                    normalized_uuid,
                    SYNC_STATUS_SYNCED,
                ),
            )

            if cursor.rowcount == 0:
                existing = con.execute(
                    """
                    SELECT status
                    FROM sync_queue
                    WHERE entity_uuid=?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (normalized_uuid,),
                ).fetchone()

                if existing is None:
                    raise LookupError(
                        "Sync queue yozuvi topilmadi: "
                        f"{normalized_uuid}"
                    )

            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def mark_conflict(
        self,
        entity_uuid: str,
        error_message: str,
    ) -> None:
        normalized_uuid = _normalize_required_text(
            entity_uuid,
            field_name="entity_uuid",
        )
        normalized_error = _normalize_required_text(
            error_message,
            field_name="error_message",
        )

        now = utc_now_iso()
        con = self._connection_factory()

        try:
            cursor = con.execute(
                """
                UPDATE sync_queue
                SET
                    status=?,
                    last_error=?,
                    next_attempt_at=NULL,
                    updated_at=?
                WHERE entity_uuid=?
                  AND status<>?
                """,
                (
                    SYNC_STATUS_CONFLICT,
                    normalized_error,
                    now,
                    normalized_uuid,
                    SYNC_STATUS_SYNCED,
                ),
            )

            if cursor.rowcount == 0:
                existing = con.execute(
                    """
                    SELECT status
                    FROM sync_queue
                    WHERE entity_uuid=?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (normalized_uuid,),
                ).fetchone()

                if existing is None:
                    raise LookupError(
                        "Sync queue yozuvi topilmadi: "
                        f"{normalized_uuid}"
                    )

            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def count_by_status(
        self,
        status: str,
    ) -> int:
        normalized_status = _normalize_required_text(
            status,
            field_name="status",
        )

        if normalized_status not in SYNC_STATUSES:
            raise ValueError(
                f"Noto‘g‘ri sync status: "
                f"{normalized_status}"
            )

        con = self._connection_factory()

        try:
            row = con.execute(
                """
                SELECT COUNT(*)
                FROM sync_queue
                WHERE status=?
                """,
                (normalized_status,),
            ).fetchone()
        finally:
            con.close()

        return int(row[0])

    def reset_stuck_syncing(self) -> int:
        now = utc_now_iso()
        con = self._connection_factory()

        try:
            cursor = con.execute(
                """
                UPDATE sync_queue
                SET
                    status=?,
                    updated_at=?
                WHERE status=?
                """,
                (
                    SYNC_STATUS_PENDING,
                    now,
                    SYNC_STATUS_SYNCING,
                ),
            )

            changed = cursor.rowcount
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

        return int(changed)
