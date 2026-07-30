from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from services.offline.constants import (
    DIRECTION_PULL,
    DIRECTION_PUSH,
    SYNC_DIRECTIONS,
)
from services.offline.log import (
    StoredSyncLog,
    SyncLogEntry,
)
from services.offline.serializer import (
    deserialize_payload,
    serialize_payload,
)

ConnectionFactory = Callable[[], sqlite3.Connection]


def new_log_uuid() -> str:
    return str(uuid.uuid4())


def utc_now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat(timespec="microseconds")


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


def _normalize_optional_text(
    value: object,
    *,
    field_name: str,
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise TypeError(
            f"{field_name} matn bo‘lishi kerak"
        )

    normalized = value.strip()

    return normalized or None


def _normalize_status_code(
    value: object,
) -> int | None:
    if value is None:
        return None

    if isinstance(value, bool):
        raise TypeError(
            "status_code integer bo‘lishi kerak"
        )

    if not isinstance(value, int):
        raise TypeError(
            "status_code integer bo‘lishi kerak"
        )

    if value < 0:
        raise ValueError(
            "status_code manfiy bo‘lishi mumkin emas"
        )

    return value


def _normalize_datetime(
    value: object,
    *,
    field_name: str,
) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(
            f"{field_name} datetime bo‘lishi kerak"
        )

    if value.tzinfo is None:
        return value.replace(
            tzinfo=timezone.utc
        )

    return value


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


def _serialize_optional_payload(
    value: Mapping[str, Any] | None,
    *,
    field_name: str,
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, Mapping):
        raise TypeError(
            f"{field_name} Mapping bo‘lishi kerak"
        )

    return serialize_payload(value)


def _deserialize_optional_payload(
    value: str | None,
) -> dict[str, Any] | None:
    if value is None:
        return None

    return deserialize_payload(value)


class SQLiteSyncLog:
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

    def record(
        self,
        entry: SyncLogEntry,
    ) -> str:
        if not isinstance(entry, SyncLogEntry):
            raise TypeError(
                "entry SyncLogEntry bo‘lishi kerak"
            )

        direction = _normalize_required_text(
            entry.direction,
            field_name="direction",
        )

        if direction not in SYNC_DIRECTIONS:
            raise ValueError(
                f"Noto‘g‘ri direction: {direction}"
            )

        device_uuid = _normalize_required_text(
            entry.device_uuid,
            field_name="device_uuid",
        )

        if not isinstance(entry.success, bool):
            raise TypeError(
                "success bool bo‘lishi kerak"
            )

        started_at = _normalize_datetime(
            entry.started_at,
            field_name="started_at",
        )
        finished_at = _normalize_datetime(
            entry.finished_at,
            field_name="finished_at",
        )

        if finished_at < started_at:
            raise ValueError(
                "finished_at started_at dan "
                "oldin bo‘lishi mumkin emas"
            )

        entity_type = _normalize_optional_text(
            entry.entity_type,
            field_name="entity_type",
        )
        entity_uuid = _normalize_optional_text(
            entry.entity_uuid,
            field_name="entity_uuid",
        )
        queue_uuid = _normalize_optional_text(
            entry.queue_uuid,
            field_name="queue_uuid",
        )
        message = _normalize_optional_text(
            entry.message,
            field_name="message",
        )
        status_code = _normalize_status_code(
            entry.status_code
        )

        request_json = _serialize_optional_payload(
            entry.request_payload,
            field_name="request_payload",
        )
        response_json = _serialize_optional_payload(
            entry.response_payload,
            field_name="response_payload",
        )

        log_uuid = new_log_uuid()

        con = self._connection_factory()

        try:
            con.execute(
                """
                INSERT INTO sync_log (
                    log_uuid,
                    direction,
                    entity_type,
                    entity_uuid,
                    queue_uuid,
                    device_uuid,
                    success,
                    status_code,
                    message,
                    request_json,
                    response_json,
                    started_at,
                    finished_at,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log_uuid,
                    direction,
                    entity_type,
                    entity_uuid,
                    queue_uuid,
                    device_uuid,
                    int(entry.success),
                    status_code,
                    message,
                    request_json,
                    response_json,
                    started_at.isoformat(
                        timespec="microseconds"
                    ),
                    finished_at.isoformat(
                        timespec="microseconds"
                    ),
                    utc_now_iso(),
                ),
            )

            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

        return log_uuid

    def recent(
        self,
        *,
        limit: int = 100,
    ) -> tuple[StoredSyncLog, ...]:
        if isinstance(limit, bool):
            raise TypeError(
                "limit integer bo‘lishi kerak"
            )

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
                    log_uuid,
                    direction,
                    entity_type,
                    entity_uuid,
                    queue_uuid,
                    device_uuid,
                    success,
                    status_code,
                    message,
                    request_json,
                    response_json,
                    started_at,
                    finished_at,
                    created_at
                FROM sync_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        finally:
            con.close()

        return tuple(
            StoredSyncLog(
                log_uuid=row["log_uuid"],
                direction=row["direction"],
                entity_type=row["entity_type"],
                entity_uuid=row["entity_uuid"],
                queue_uuid=row["queue_uuid"],
                device_uuid=row["device_uuid"],
                success=bool(row["success"]),
                status_code=row["status_code"],
                message=row["message"],
                request_payload=(
                    _deserialize_optional_payload(
                        row["request_json"]
                    )
                ),
                response_payload=(
                    _deserialize_optional_payload(
                        row["response_json"]
                    )
                ),
                started_at=_parse_datetime(
                    row["started_at"],
                    field_name="started_at",
                ),
                finished_at=_parse_datetime(
                    row["finished_at"],
                    field_name="finished_at",
                ),
                created_at=_parse_datetime(
                    row["created_at"],
                    field_name="created_at",
                ),
            )
            for row in rows
        )

    def count(
        self,
        *,
        success: bool | None = None,
        direction: str | None = None,
    ) -> int:
        if (
            success is not None
            and not isinstance(success, bool)
        ):
            raise TypeError(
                "success bool yoki None bo‘lishi kerak"
            )

        normalized_direction = None

        if direction is not None:
            normalized_direction = (
                _normalize_required_text(
                    direction,
                    field_name="direction",
                )
            )

            if (
                normalized_direction
                not in SYNC_DIRECTIONS
            ):
                raise ValueError(
                    "Noto‘g‘ri direction: "
                    f"{normalized_direction}"
                )

        where = []
        params: list[object] = []

        if success is not None:
            where.append("success=?")
            params.append(int(success))

        if normalized_direction is not None:
            where.append("direction=?")
            params.append(normalized_direction)

        sql = "SELECT COUNT(*) FROM sync_log"

        if where:
            sql += " WHERE " + " AND ".join(where)

        con = self._connection_factory()

        try:
            row = con.execute(
                sql,
                tuple(params),
            ).fetchone()
        finally:
            con.close()

        return int(row[0])

    def purge_older_than(
        self,
        cutoff: datetime,
    ) -> int:
        normalized_cutoff = _normalize_datetime(
            cutoff,
            field_name="cutoff",
        )

        con = self._connection_factory()

        try:
            cursor = con.execute(
                """
                DELETE FROM sync_log
                WHERE created_at < ?
                """,
                (
                    normalized_cutoff.isoformat(
                        timespec="microseconds"
                    ),
                ),
            )

            deleted = int(cursor.rowcount)
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

        return deleted


__all__ = [
    "DIRECTION_PULL",
    "DIRECTION_PUSH",
    "SQLiteSyncLog",
    "new_log_uuid",
]
