"""Add stable sync identity to root business entities."""

from __future__ import annotations

import sqlite3
import uuid


VERSION = 4
NAME = "business_entity_identity"


ROOT_ENTITY_TABLES = (
    "categories",
    "products",
    "inventory_moves",
    "sales",
    "cash_moves",
)


def _table_columns(
    connection: sqlite3.Connection,
    table: str,
) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(
            f'PRAGMA table_info("{table}")'
        ).fetchall()
    }


def _ensure_identity_columns(
    connection: sqlite3.Connection,
    table: str,
) -> None:
    columns = _table_columns(
        connection,
        table,
    )

    if "entity_uuid" not in columns:
        connection.execute(
            f"""
            ALTER TABLE "{table}"
            ADD COLUMN entity_uuid TEXT
            """
        )

    if "sync_version" not in columns:
        connection.execute(
            f"""
            ALTER TABLE "{table}"
            ADD COLUMN sync_version INTEGER
                NOT NULL DEFAULT 1
                CHECK (sync_version >= 1)
            """
        )


def _backfill_entity_uuid(
    connection: sqlite3.Connection,
    table: str,
) -> None:
    rows = connection.execute(
        f"""
        SELECT id
        FROM "{table}"
        WHERE entity_uuid IS NULL
           OR TRIM(entity_uuid) = ''
        ORDER BY id
        """
    ).fetchall()

    for row in rows:
        connection.execute(
            f"""
            UPDATE "{table}"
            SET entity_uuid=?
            WHERE id=?
            """,
            (
                str(uuid.uuid4()),
                int(row[0]),
            ),
        )


def _validate_table_identity(
    connection: sqlite3.Connection,
    table: str,
) -> None:
    missing_uuid = int(
        connection.execute(
            f"""
            SELECT COUNT(*)
            FROM "{table}"
            WHERE entity_uuid IS NULL
               OR TRIM(entity_uuid) = ''
            """
        ).fetchone()[0]
    )

    invalid_version = int(
        connection.execute(
            f"""
            SELECT COUNT(*)
            FROM "{table}"
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
                FROM "{table}"
                GROUP BY entity_uuid
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]
    )

    if missing_uuid:
        raise RuntimeError(
            f"{table}: entity_uuid backfill incomplete"
        )

    if invalid_version:
        raise RuntimeError(
            f"{table}: invalid sync_version"
        )

    if duplicate_uuid:
        raise RuntimeError(
            f"{table}: duplicate entity_uuid"
        )


def _ensure_unique_index(
    connection: sqlite3.Connection,
    table: str,
) -> None:
    connection.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS
            idx_{table}_entity_uuid
        ON "{table}"(entity_uuid)
        """
    )


def upgrade(
    connection: sqlite3.Connection,
) -> None:
    for table in ROOT_ENTITY_TABLES:
        _ensure_identity_columns(
            connection,
            table,
        )

        _backfill_entity_uuid(
            connection,
            table,
        )

        _validate_table_identity(
            connection,
            table,
        )

        _ensure_unique_index(
            connection,
            table,
        )


__all__ = [
    "NAME",
    "ROOT_ENTITY_TABLES",
    "VERSION",
    "upgrade",
]
