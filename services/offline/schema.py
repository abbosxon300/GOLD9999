from __future__ import annotations

import sqlite3
from collections.abc import Iterable

OFFLINE_SYNC_SCHEMA_VERSION = 1

SYNC_QUEUE_TABLE = "sync_queue"
SYNC_LOG_TABLE = "sync_log"
SYNC_CONFLICTS_TABLE = "sync_conflicts"

OFFLINE_SYNC_TABLES = frozenset(
    {
        SYNC_QUEUE_TABLE,
        SYNC_LOG_TABLE,
        SYNC_CONFLICTS_TABLE,
    }
)


def _table_exists(
    con: sqlite3.Connection,
    table_name: str,
) -> bool:
    row = con.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type='table'
          AND name=?
        LIMIT 1
        """,
        (table_name,),
    ).fetchone()

    return row is not None


def _index_exists(
    con: sqlite3.Connection,
    index_name: str,
) -> bool:
    row = con.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type='index'
          AND name=?
        LIMIT 1
        """,
        (index_name,),
    ).fetchone()

    return row is not None


def _required_columns(
    con: sqlite3.Connection,
    table_name: str,
) -> set[str]:
    rows = con.execute(
        f'PRAGMA table_info("{table_name}")'
    ).fetchall()

    return {
        str(row[1])
        for row in rows
    }


def _assert_columns(
    con: sqlite3.Connection,
    table_name: str,
    expected: Iterable[str],
) -> None:
    actual = _required_columns(
        con,
        table_name,
    )

    missing = sorted(
        set(expected) - actual
    )

    if missing:
        raise RuntimeError(
            f"{table_name} ustunlari yetishmaydi: "
            f"{missing}"
        )


def ensure_offline_sync_schema(
    con: sqlite3.Connection,
) -> None:
    """
    Offline sync uchun zarur jadvallarni idempotent
    tarzda yaratadi.

    Mavjud biznes jadvallariga tegmaydi.
    """
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            queue_uuid TEXT NOT NULL UNIQUE,
            entity_type TEXT NOT NULL,
            entity_uuid TEXT NOT NULL,
            operation TEXT NOT NULL
                CHECK (
                    operation IN (
                        'create',
                        'update',
                        'delete'
                    )
                ),
            payload_json TEXT NOT NULL,
            device_uuid TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (
                    status IN (
                        'pending',
                        'syncing',
                        'synced',
                        'failed',
                        'conflict'
                    )
                ),
            attempt_count INTEGER NOT NULL DEFAULT 0
                CHECK (attempt_count >= 0),
            next_attempt_at TEXT,
            last_error TEXT,
            occurred_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            synced_at TEXT
        )
        """
    )

    con.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_sync_queue_status_schedule
        ON sync_queue(
            status,
            next_attempt_at,
            id
        )
        """
    )

    con.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_sync_queue_entity
        ON sync_queue(
            entity_type,
            entity_uuid,
            id
        )
        """
    )

    con.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_sync_queue_device
        ON sync_queue(
            device_uuid,
            id
        )
        """
    )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_uuid TEXT NOT NULL UNIQUE,
            direction TEXT NOT NULL
                CHECK (
                    direction IN (
                        'push',
                        'pull'
                    )
                ),
            entity_type TEXT,
            entity_uuid TEXT,
            queue_uuid TEXT,
            device_uuid TEXT NOT NULL,
            success INTEGER NOT NULL
                CHECK (success IN (0, 1)),
            status_code INTEGER,
            message TEXT,
            request_json TEXT,
            response_json TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    con.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_sync_log_device_created
        ON sync_log(
            device_uuid,
            created_at,
            id
        )
        """
    )

    con.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_sync_log_entity
        ON sync_log(
            entity_type,
            entity_uuid,
            id
        )
        """
    )

    con.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_sync_log_queue
        ON sync_log(
            queue_uuid,
            id
        )
        """
    )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_conflicts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conflict_uuid TEXT NOT NULL UNIQUE,
            entity_type TEXT NOT NULL,
            entity_uuid TEXT NOT NULL,
            local_payload_json TEXT NOT NULL,
            remote_payload_json TEXT NOT NULL,
            local_device_uuid TEXT NOT NULL,
            remote_device_uuid TEXT,
            local_version INTEGER,
            remote_version INTEGER,
            resolution TEXT NOT NULL DEFAULT 'manual'
                CHECK (
                    resolution IN (
                        'manual',
                        'use_local',
                        'use_remote'
                    )
                ),
            resolved INTEGER NOT NULL DEFAULT 0
                CHECK (resolved IN (0, 1)),
            resolved_payload_json TEXT,
            resolved_by TEXT,
            detected_at TEXT NOT NULL,
            resolved_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    con.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_sync_conflicts_open
        ON sync_conflicts(
            resolved,
            detected_at,
            id
        )
        """
    )

    con.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_sync_conflicts_entity
        ON sync_conflicts(
            entity_type,
            entity_uuid,
            id
        )
        """
    )

    validate_offline_sync_schema(con)


def validate_offline_sync_schema(
    con: sqlite3.Connection,
) -> None:
    for table_name in OFFLINE_SYNC_TABLES:
        if not _table_exists(
            con,
            table_name,
        ):
            raise RuntimeError(
                f"{table_name} jadvali topilmadi"
            )

    _assert_columns(
        con,
        SYNC_QUEUE_TABLE,
        {
            "id",
            "queue_uuid",
            "entity_type",
            "entity_uuid",
            "operation",
            "payload_json",
            "device_uuid",
            "status",
            "attempt_count",
            "next_attempt_at",
            "last_error",
            "occurred_at",
            "created_at",
            "updated_at",
            "synced_at",
        },
    )

    _assert_columns(
        con,
        SYNC_LOG_TABLE,
        {
            "id",
            "log_uuid",
            "direction",
            "entity_type",
            "entity_uuid",
            "queue_uuid",
            "device_uuid",
            "success",
            "status_code",
            "message",
            "request_json",
            "response_json",
            "started_at",
            "finished_at",
            "created_at",
        },
    )

    _assert_columns(
        con,
        SYNC_CONFLICTS_TABLE,
        {
            "id",
            "conflict_uuid",
            "entity_type",
            "entity_uuid",
            "local_payload_json",
            "remote_payload_json",
            "local_device_uuid",
            "remote_device_uuid",
            "local_version",
            "remote_version",
            "resolution",
            "resolved",
            "resolved_payload_json",
            "resolved_by",
            "detected_at",
            "resolved_at",
            "created_at",
            "updated_at",
        },
    )

    required_indexes = {
        "idx_sync_queue_status_schedule",
        "idx_sync_queue_entity",
        "idx_sync_queue_device",
        "idx_sync_log_device_created",
        "idx_sync_log_entity",
        "idx_sync_log_queue",
        "idx_sync_conflicts_open",
        "idx_sync_conflicts_entity",
    }

    missing_indexes = sorted(
        index_name
        for index_name in required_indexes
        if not _index_exists(
            con,
            index_name,
        )
    )

    if missing_indexes:
        raise RuntimeError(
            "Offline sync indekslari yetishmaydi: "
            f"{missing_indexes}"
        )
