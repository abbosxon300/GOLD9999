"""Add stable sync identity to sale item entities."""

from __future__ import annotations

import sqlite3
import uuid


VERSION = 5
NAME = "sale_items_entity_identity"

TABLE = "sale_items"
INDEX = "idx_sale_items_entity_uuid"


def _table_columns(
    connection: sqlite3.Connection,
) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(
            f'PRAGMA table_info("{TABLE}")'
        ).fetchall()
    }


def _ensure_identity_columns(
    connection: sqlite3.Connection,
) -> None:
    columns = _table_columns(connection)

    if "entity_uuid" not in columns:
        connection.execute(
            f"""
            ALTER TABLE "{TABLE}"
            ADD COLUMN entity_uuid TEXT
            """
        )

    if "sync_version" not in columns:
        connection.execute(
            f"""
            ALTER TABLE "{TABLE}"
            ADD COLUMN sync_version INTEGER
                NOT NULL DEFAULT 1
                CHECK (sync_version >= 1)
            """
        )


def _backfill_entity_uuid(
    connection: sqlite3.Connection,
) -> None:
    rows = connection.execute(
        f"""
        SELECT id
        FROM "{TABLE}"
        WHERE entity_uuid IS NULL
           OR TRIM(entity_uuid) = ''
        ORDER BY id
        """
    ).fetchall()

    for row in rows:
        connection.execute(
            f"""
            UPDATE "{TABLE}"
            SET entity_uuid=?
            WHERE id=?
            """,
            (
                str(uuid.uuid4()),
                int(row[0]),
            ),
        )


def _validate_identity(
    connection: sqlite3.Connection,
) -> None:
    missing_uuid = int(
        connection.execute(
            f"""
            SELECT COUNT(*)
            FROM "{TABLE}"
            WHERE entity_uuid IS NULL
               OR TRIM(entity_uuid) = ''
            """
        ).fetchone()[0]
    )

    invalid_version = int(
        connection.execute(
            f"""
            SELECT COUNT(*)
            FROM "{TABLE}"
            WHERE sync_version IS NULL
               OR sync_version < 1
            """
        ).fetchone()[0]
    )

    duplicate_uuid = int(
        connection.execute(
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT entity_uuid
                FROM "{TABLE}"
                GROUP BY entity_uuid
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]
    )

    if missing_uuid:
        raise RuntimeError(
            f"{TABLE}: entity_uuid backfill incomplete"
        )

    if invalid_version:
        raise RuntimeError(
            f"{TABLE}: invalid sync_version"
        )

    if duplicate_uuid:
        raise RuntimeError(
            f"{TABLE}: duplicate entity_uuid"
        )


def _ensure_unique_index(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS
            {INDEX}
        ON "{TABLE}"(entity_uuid)
        """
    )


def upgrade(
    connection: sqlite3.Connection,
) -> None:
    _ensure_identity_columns(connection)
    _backfill_entity_uuid(connection)
    _validate_identity(connection)
    _ensure_unique_index(connection)


__all__ = [
    "INDEX",
    "NAME",
    "TABLE",
    "VERSION",
    "upgrade",
]
