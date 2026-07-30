from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from services.offline.conflict import (
    CONFLICT_RESOLUTION_USE_LOCAL,
    CONFLICT_RESOLUTION_USE_REMOTE,
    CONFLICT_RESOLUTIONS,
    StoredSyncConflict,
    SyncConflictEntry,
)
from services.offline.serializer import (
    deserialize_payload,
    serialize_payload,
)

ConnectionFactory = Callable[[], sqlite3.Connection]


def new_conflict_uuid() -> str:
    return str(uuid.uuid4())


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

    value = value.strip()

    if not value:
        raise ValueError(
            f"{field_name} bo‘sh bo‘lishi mumkin emas"
        )

    return value


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

    value = value.strip()

    return value or None


def _normalized_datetime(
    value: object,
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


def _normalized_version(
    value: object,
    field_name: str,
) -> int | None:
    if value is None:
        return None

    if isinstance(value, bool):
        raise TypeError(
            f"{field_name} integer bo‘lishi kerak"
        )

    if not isinstance(value, int):
        raise TypeError(
            f"{field_name} integer bo‘lishi kerak"
        )

    if value < 0:
        raise ValueError(
            f"{field_name} manfiy bo‘lishi mumkin emas"
        )

    return value


def _payload(
    value: object,
    field_name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(
            f"{field_name} Mapping bo‘lishi kerak"
        )

    return value


def _optional_payload(
    value: str | None,
) -> dict[str, Any] | None:
    if value is None:
        return None

    return deserialize_payload(value)


def _row_to_conflict(
    row: sqlite3.Row,
) -> StoredSyncConflict:
    detected_at = _parsed_datetime(
        row["detected_at"],
        "detected_at",
    )
    created_at = _parsed_datetime(
        row["created_at"],
        "created_at",
    )
    updated_at = _parsed_datetime(
        row["updated_at"],
        "updated_at",
    )

    if detected_at is None:
        raise ValueError(
            "detected_at bo‘sh bo‘lishi mumkin emas"
        )

    if created_at is None:
        raise ValueError(
            "created_at bo‘sh bo‘lishi mumkin emas"
        )

    if updated_at is None:
        raise ValueError(
            "updated_at bo‘sh bo‘lishi mumkin emas"
        )

    return StoredSyncConflict(
        conflict_uuid=row["conflict_uuid"],
        entity_type=row["entity_type"],
        entity_uuid=row["entity_uuid"],
        local_payload=deserialize_payload(
            row["local_payload_json"]
        ),
        remote_payload=deserialize_payload(
            row["remote_payload_json"]
        ),
        local_device_uuid=row["local_device_uuid"],
        remote_device_uuid=row["remote_device_uuid"],
        local_version=row["local_version"],
        remote_version=row["remote_version"],
        resolution=row["resolution"],
        resolved=bool(row["resolved"]),
        resolved_payload=_optional_payload(
            row["resolved_payload_json"]
        ),
        resolved_by=row["resolved_by"],
        detected_at=detected_at,
        resolved_at=_parsed_datetime(
            row["resolved_at"],
            "resolved_at",
        ),
        created_at=created_at,
        updated_at=updated_at,
    )


class SQLiteSyncConflictStore:
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
        conflict: SyncConflictEntry,
    ) -> str:
        if not isinstance(
            conflict,
            SyncConflictEntry,
        ):
            raise TypeError(
                "conflict SyncConflictEntry bo‘lishi kerak"
            )

        entity_type = _required_text(
            conflict.entity_type,
            "entity_type",
        )
        entity_uuid = _required_text(
            conflict.entity_uuid,
            "entity_uuid",
        )
        local_device_uuid = _required_text(
            conflict.local_device_uuid,
            "local_device_uuid",
        )
        remote_device_uuid = _optional_text(
            conflict.remote_device_uuid,
            "remote_device_uuid",
        )

        local_payload = _payload(
            conflict.local_payload,
            "local_payload",
        )
        remote_payload = _payload(
            conflict.remote_payload,
            "remote_payload",
        )

        local_version = _normalized_version(
            conflict.local_version,
            "local_version",
        )
        remote_version = _normalized_version(
            conflict.remote_version,
            "remote_version",
        )
        detected_at = _normalized_datetime(
            conflict.detected_at,
            "detected_at",
        )

        conflict_uuid = new_conflict_uuid()
        now = utc_now_iso()

        con = self._connection_factory()

        try:
            con.execute(
                """
                INSERT INTO sync_conflicts (
                    conflict_uuid,
                    entity_type,
                    entity_uuid,
                    local_payload_json,
                    remote_payload_json,
                    local_device_uuid,
                    remote_device_uuid,
                    local_version,
                    remote_version,
                    resolution,
                    resolved,
                    detected_at,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    'manual', 0, ?, ?, ?
                )
                """,
                (
                    conflict_uuid,
                    entity_type,
                    entity_uuid,
                    serialize_payload(
                        local_payload
                    ),
                    serialize_payload(
                        remote_payload
                    ),
                    local_device_uuid,
                    remote_device_uuid,
                    local_version,
                    remote_version,
                    detected_at.isoformat(
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

        return conflict_uuid

    def open_conflicts(
        self,
        *,
        limit: int = 100,
    ) -> tuple[StoredSyncConflict, ...]:
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
                    conflict_uuid,
                    entity_type,
                    entity_uuid,
                    local_payload_json,
                    remote_payload_json,
                    local_device_uuid,
                    remote_device_uuid,
                    local_version,
                    remote_version,
                    resolution,
                    resolved,
                    resolved_payload_json,
                    resolved_by,
                    detected_at,
                    resolved_at,
                    created_at,
                    updated_at
                FROM sync_conflicts
                WHERE resolved=0
                ORDER BY detected_at ASC, id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        finally:
            con.close()

        return tuple(
            _row_to_conflict(row)
            for row in rows
        )

    def get(
        self,
        conflict_uuid: str,
    ) -> StoredSyncConflict | None:
        normalized_uuid = _required_text(
            conflict_uuid,
            "conflict_uuid",
        )

        con = self._connection_factory()
        con.row_factory = sqlite3.Row

        try:
            row = con.execute(
                """
                SELECT
                    conflict_uuid,
                    entity_type,
                    entity_uuid,
                    local_payload_json,
                    remote_payload_json,
                    local_device_uuid,
                    remote_device_uuid,
                    local_version,
                    remote_version,
                    resolution,
                    resolved,
                    resolved_payload_json,
                    resolved_by,
                    detected_at,
                    resolved_at,
                    created_at,
                    updated_at
                FROM sync_conflicts
                WHERE conflict_uuid=?
                LIMIT 1
                """,
                (normalized_uuid,),
            ).fetchone()
        finally:
            con.close()

        if row is None:
            return None

        return _row_to_conflict(row)

    def resolve(
        self,
        conflict_uuid: str,
        *,
        resolution: str,
        resolved_payload: Mapping[str, Any],
        resolved_by: str,
    ) -> None:
        normalized_uuid = _required_text(
            conflict_uuid,
            "conflict_uuid",
        )
        normalized_resolution = _required_text(
            resolution,
            "resolution",
        )
        normalized_resolved_by = _required_text(
            resolved_by,
            "resolved_by",
        )

        if (
            normalized_resolution
            not in CONFLICT_RESOLUTIONS
        ):
            raise ValueError(
                "Noto‘g‘ri resolution: "
                f"{normalized_resolution}"
            )

        if normalized_resolution not in {
            CONFLICT_RESOLUTION_USE_LOCAL,
            CONFLICT_RESOLUTION_USE_REMOTE,
        }:
            raise ValueError(
                "Yakuniy resolution faqat "
                "use_local yoki use_remote "
                "bo‘lishi kerak"
            )

        payload = _payload(
            resolved_payload,
            "resolved_payload",
        )

        now = utc_now_iso()
        con = self._connection_factory()

        try:
            cursor = con.execute(
                """
                UPDATE sync_conflicts
                SET
                    resolution=?,
                    resolved=1,
                    resolved_payload_json=?,
                    resolved_by=?,
                    resolved_at=?,
                    updated_at=?
                WHERE conflict_uuid=?
                  AND resolved=0
                """,
                (
                    normalized_resolution,
                    serialize_payload(payload),
                    normalized_resolved_by,
                    now,
                    now,
                    normalized_uuid,
                ),
            )

            if cursor.rowcount == 0:
                row = con.execute(
                    """
                    SELECT resolved
                    FROM sync_conflicts
                    WHERE conflict_uuid=?
                    LIMIT 1
                    """,
                    (normalized_uuid,),
                ).fetchone()

                if row is None:
                    raise LookupError(
                        "Conflict topilmadi: "
                        f"{normalized_uuid}"
                    )

                raise RuntimeError(
                    "Conflict avval yechilgan: "
                    f"{normalized_uuid}"
                )

            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def count(
        self,
        *,
        resolved: bool | None = None,
    ) -> int:
        if (
            resolved is not None
            and not isinstance(resolved, bool)
        ):
            raise TypeError(
                "resolved bool yoki None "
                "bo‘lishi kerak"
            )

        sql = (
            "SELECT COUNT(*) "
            "FROM sync_conflicts"
        )
        params: tuple[object, ...] = ()

        if resolved is not None:
            sql += " WHERE resolved=?"
            params = (int(resolved),)

        con = self._connection_factory()

        try:
            row = con.execute(
                sql,
                params,
            ).fetchone()
        finally:
            con.close()

        return int(row[0])


__all__ = [
    "SQLiteSyncConflictStore",
    "new_conflict_uuid",
]
