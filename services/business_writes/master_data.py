from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from services.business_writes.transaction import (
    business_transaction,
)
from services.db import get_db
from services.device_identity import (
    get_device_identity,
)
from services.offline.constants import (
    OPERATION_CREATE,
    OPERATION_UPDATE,
)
from services.offline.models import SyncRecord
from services.offline.sqlite_queue import (
    SQLiteSyncQueue,
)


def _desktop_sync_enabled() -> bool:
    return bool(
        str(
            os.environ.get(
                "GOLD9999_DATA_DIR",
                "",
            )
        ).strip()
    )


def _device_uuid(
    connection: sqlite3.Connection,
) -> str:
    env_value = str(
        os.environ.get(
            "OFFLINE_DEVICE_UUID",
            "",
        )
    ).strip()

    if env_value:
        return env_value

    identity = get_device_identity(
        connection
    )

    if identity is None:
        raise RuntimeError(
            "Offline device identity topilmadi"
        )

    value = str(
        getattr(
            identity,
            "installation_uuid",
            "",
        )
        or getattr(
            identity,
            "device_uuid",
            "",
        )
        or ""
    ).strip()

    if not value:
        raise RuntimeError(
            "Offline device UUID topilmadi"
        )

    return value


def _queue_change(
    connection: sqlite3.Connection,
    *,
    entity_type: str,
    entity_uuid: str,
    operation: str,
    payload: dict[str, Any],
) -> None:
    if not _desktop_sync_enabled():
        return

    queue = SQLiteSyncQueue(
        lambda: get_db()
    )

    queue.enqueue(
        SyncRecord(
            entity_type=entity_type,
            entity_uuid=entity_uuid,
            operation=operation,
            payload=payload,
            device_uuid=_device_uuid(
                connection
            ),
            occurred_at=datetime.now(
                timezone.utc
            ),
        ),
        connection=connection,
    )


def _category_row(
    connection: sqlite3.Connection,
    category_id: int,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT
            id,
            name,
            sort_order,
            is_active,
            created_at,
            entity_uuid,
            sync_version
        FROM categories
        WHERE id=?
        """,
        (category_id,),
    ).fetchone()

    if row is None:
        raise LookupError(
            "Kategoriya topilmadi"
        )

    return row


def _category_payload(
    row: sqlite3.Row,
) -> dict[str, Any]:
    return {
        "name": str(row["name"]),
        "sort_order": int(
            row["sort_order"]
        ),
        "is_active": int(
            row["is_active"]
        ),
        "created_at": str(
            row["created_at"]
        ),
    }


def _product_row(
    connection: sqlite3.Connection,
    product_id: int,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT
            p.id,
            p.name,
            p.category_id,
            p.sell_price_default_uzs,
            p.is_active,
            p.created_at,
            p.entity_uuid,
            p.sync_version,
            c.entity_uuid AS category_uuid
        FROM products p
        JOIN categories c
          ON c.id=p.category_id
        WHERE p.id=?
        """,
        (product_id,),
    ).fetchone()

    if row is None:
        raise LookupError(
            "Mahsulot topilmadi"
        )

    return row


def _product_payload(
    row: sqlite3.Row,
) -> dict[str, Any]:
    category_uuid = str(
        row["category_uuid"] or ""
    ).strip()

    if not category_uuid:
        raise RuntimeError(
            "Kategoriya entity_uuid mavjud emas"
        )

    return {
        "name": str(row["name"]),
        "category_uuid": category_uuid,
        "sell_price_default_uzs": float(
            row["sell_price_default_uzs"]
        ),
        "is_active": int(
            row["is_active"]
        ),
        "created_at": str(
            row["created_at"]
        ),
    }


def create_category(
    *,
    name: str,
    sort_order: int,
    connection: sqlite3.Connection | None = None,
) -> int:
    with business_transaction(
        connection
    ) as tx:
        entity_uuid = str(uuid.uuid4())

        cursor = tx.execute(
            """
            INSERT INTO categories(
                name,
                sort_order,
                is_active,
                entity_uuid,
                sync_version
            )
            VALUES (?, ?, 1, ?, 1)
            """,
            (
                name,
                int(sort_order),
                entity_uuid,
            ),
        )

        category_id = int(
            cursor.lastrowid
        )

        row = _category_row(
            tx,
            category_id,
        )

        _queue_change(
            tx,
            entity_type="category",
            entity_uuid=entity_uuid,
            operation=OPERATION_CREATE,
            payload=_category_payload(row),
        )

        return category_id


def update_category(
    category_id: int,
    *,
    name: str,
    sort_order: int,
    connection: sqlite3.Connection | None = None,
) -> None:
    with business_transaction(
        connection
    ) as tx:
        current = _category_row(
            tx,
            category_id,
        )

        entity_uuid = str(
            current["entity_uuid"] or ""
        ).strip()

        if not entity_uuid:
            entity_uuid = str(
                uuid.uuid4()
            )

        cursor = tx.execute(
            """
            UPDATE categories
            SET
                name=?,
                sort_order=?,
                entity_uuid=?,
                sync_version=sync_version+1
            WHERE id=?
            """,
            (
                name,
                int(sort_order),
                entity_uuid,
                category_id,
            ),
        )

        if cursor.rowcount != 1:
            raise LookupError(
                "Kategoriya topilmadi"
            )

        row = _category_row(
            tx,
            category_id,
        )

        _queue_change(
            tx,
            entity_type="category",
            entity_uuid=entity_uuid,
            operation=OPERATION_UPDATE,
            payload=_category_payload(row),
        )


def set_category_active(
    category_id: int,
    *,
    is_active: int,
    connection: sqlite3.Connection | None = None,
) -> None:
    with business_transaction(
        connection
    ) as tx:
        current = _category_row(
            tx,
            category_id,
        )

        entity_uuid = str(
            current["entity_uuid"] or ""
        ).strip()

        if not entity_uuid:
            entity_uuid = str(
                uuid.uuid4()
            )

        cursor = tx.execute(
            """
            UPDATE categories
            SET
                is_active=?,
                entity_uuid=?,
                sync_version=sync_version+1
            WHERE id=?
            """,
            (
                int(is_active),
                entity_uuid,
                category_id,
            ),
        )

        if cursor.rowcount != 1:
            raise LookupError(
                "Kategoriya topilmadi"
            )

        row = _category_row(
            tx,
            category_id,
        )

        _queue_change(
            tx,
            entity_type="category",
            entity_uuid=entity_uuid,
            operation=OPERATION_UPDATE,
            payload=_category_payload(row),
        )


def create_product(
    *,
    name: str,
    category_id: int,
    sell_price_default_uzs: float,
    connection: sqlite3.Connection | None = None,
) -> int:
    with business_transaction(
        connection
    ) as tx:
        category = _category_row(
            tx,
            category_id,
        )

        category_uuid = str(
            category["entity_uuid"] or ""
        ).strip()

        if not category_uuid:
            raise RuntimeError(
                "Kategoriya entity_uuid mavjud emas"
            )

        entity_uuid = str(uuid.uuid4())

        cursor = tx.execute(
            """
            INSERT INTO products(
                name,
                category_id,
                sell_price_default_uzs,
                is_active,
                entity_uuid,
                sync_version
            )
            VALUES (?, ?, ?, 1, ?, 1)
            """,
            (
                name,
                category_id,
                float(
                    sell_price_default_uzs
                ),
                entity_uuid,
            ),
        )

        product_id = int(
            cursor.lastrowid
        )

        row = _product_row(
            tx,
            product_id,
        )

        _queue_change(
            tx,
            entity_type="product",
            entity_uuid=entity_uuid,
            operation=OPERATION_CREATE,
            payload=_product_payload(row),
        )

        return product_id


def update_product(
    product_id: int,
    *,
    name: str,
    category_id: int,
    sell_price_default_uzs: float,
    connection: sqlite3.Connection | None = None,
) -> None:
    with business_transaction(
        connection
    ) as tx:
        current = _product_row(
            tx,
            product_id,
        )

        category = _category_row(
            tx,
            category_id,
        )

        if not str(
            category["entity_uuid"] or ""
        ).strip():
            raise RuntimeError(
                "Kategoriya entity_uuid mavjud emas"
            )

        entity_uuid = str(
            current["entity_uuid"] or ""
        ).strip()

        if not entity_uuid:
            entity_uuid = str(
                uuid.uuid4()
            )

        cursor = tx.execute(
            """
            UPDATE products
            SET
                name=?,
                category_id=?,
                sell_price_default_uzs=?,
                entity_uuid=?,
                sync_version=sync_version+1
            WHERE id=?
            """,
            (
                name,
                category_id,
                float(
                    sell_price_default_uzs
                ),
                entity_uuid,
                product_id,
            ),
        )

        if cursor.rowcount != 1:
            raise LookupError(
                "Mahsulot topilmadi"
            )

        row = _product_row(
            tx,
            product_id,
        )

        _queue_change(
            tx,
            entity_type="product",
            entity_uuid=entity_uuid,
            operation=OPERATION_UPDATE,
            payload=_product_payload(row),
        )


def set_product_active(
    product_id: int,
    *,
    is_active: int,
    connection: sqlite3.Connection | None = None,
) -> None:
    with business_transaction(
        connection
    ) as tx:
        current = _product_row(
            tx,
            product_id,
        )

        entity_uuid = str(
            current["entity_uuid"] or ""
        ).strip()

        if not entity_uuid:
            entity_uuid = str(
                uuid.uuid4()
            )

        cursor = tx.execute(
            """
            UPDATE products
            SET
                is_active=?,
                entity_uuid=?,
                sync_version=sync_version+1
            WHERE id=?
            """,
            (
                int(is_active),
                entity_uuid,
                product_id,
            ),
        )

        if cursor.rowcount != 1:
            raise LookupError(
                "Mahsulot topilmadi"
            )

        row = _product_row(
            tx,
            product_id,
        )

        _queue_change(
            tx,
            entity_type="product",
            entity_uuid=entity_uuid,
            operation=OPERATION_UPDATE,
            payload=_product_payload(row),
        )


__all__ = [
    "create_category",
    "create_product",
    "set_category_active",
    "set_product_active",
    "update_category",
    "update_product",
]
