from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass


ENTITY_TABLES = {
    "category": "categories",
    "product": "products",
    "inventory_move": "inventory_moves",
    "sale": "sales",
    "cash_move": "cash_moves",
}


@dataclass(frozen=True)
class EntityIdentity:
    entity_type: str
    table_name: str
    local_id: int
    entity_uuid: str
    sync_version: int


def normalize_entity_type(entity_type: str) -> str:
    value = entity_type.strip().lower()

    if value not in ENTITY_TABLES:
        raise ValueError(
            f"Unknown entity_type: {entity_type}"
        )

    return value


def normalize_entity_uuid(entity_uuid: str) -> str:
    return str(uuid.UUID(entity_uuid))


def get_entity_table(entity_type: str) -> str:
    return ENTITY_TABLES[
        normalize_entity_type(entity_type)
    ]


def find_local_entity(
    connection: sqlite3.Connection,
    entity_type: str,
    entity_uuid: str,
) -> EntityIdentity | None:

    table = get_entity_table(entity_type)
    entity_uuid = normalize_entity_uuid(entity_uuid)

    row = connection.execute(
        f"""
        SELECT
            id,
            entity_uuid,
            sync_version
        FROM "{table}"
        WHERE entity_uuid=?
        """,
        (entity_uuid,),
    ).fetchone()

    if row is None:
        return None

    return EntityIdentity(
        entity_type=normalize_entity_type(entity_type),
        table_name=table,
        local_id=int(row["id"]),
        entity_uuid=str(row["entity_uuid"]),
        sync_version=int(row["sync_version"]),
    )


def require_local_entity(
    connection: sqlite3.Connection,
    entity_type: str,
    entity_uuid: str,
) -> EntityIdentity:

    entity = find_local_entity(
        connection,
        entity_type,
        entity_uuid,
    )

    if entity is None:
        raise LookupError(
            f"{entity_type}: {entity_uuid} not found"
        )

    return entity


def get_entity_identity(
    connection: sqlite3.Connection,
    entity_type: str,
    local_id: int,
) -> EntityIdentity | None:

    table = get_entity_table(entity_type)

    row = connection.execute(
        f"""
        SELECT
            id,
            entity_uuid,
            sync_version
        FROM "{table}"
        WHERE id=?
        """,
        (int(local_id),),
    ).fetchone()

    if row is None:
        return None

    return EntityIdentity(
        entity_type=normalize_entity_type(entity_type),
        table_name=table,
        local_id=int(row["id"]),
        entity_uuid=str(row["entity_uuid"]),
        sync_version=int(row["sync_version"]),
    )


__all__ = [
    "EntityIdentity",
    "ENTITY_TABLES",
    "find_local_entity",
    "get_entity_identity",
    "get_entity_table",
    "normalize_entity_type",
    "normalize_entity_uuid",
    "require_local_entity",
]
