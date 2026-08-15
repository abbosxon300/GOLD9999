from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from services.offline.constants import OPERATION_CREATE
from services.offline.models import SyncRecord
from services.offline.sqlite_queue import SQLiteSyncQueue


@dataclass(frozen=True)
class LegacyMasterDataRecoveryResult:
    categories_recovered: int
    products_recovered: int
    queue_created: int


def _device_uuid(connection: sqlite3.Connection) -> str:
    row = connection.execute(
        """
        SELECT device_uuid
        FROM device_id
        ORDER BY id ASC
        LIMIT 1
        """
    ).fetchone()

    if row is None:
        raise RuntimeError(
            "Offline device UUID topilmadi"
        )

    value = str(row["device_uuid"] or "").strip()

    if not value:
        raise RuntimeError(
            "Offline device UUID topilmadi"
        )

    return value


def _queue_exists(
    connection: sqlite3.Connection,
    *,
    entity_type: str,
    entity_uuid: str,
) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM sync_queue
        WHERE entity_type=?
          AND entity_uuid=?
        LIMIT 1
        """,
        (
            entity_type,
            entity_uuid,
        ),
    ).fetchone()

    return row is not None


def _successful_push_exists(
    connection: sqlite3.Connection,
    *,
    entity_type: str,
    entity_uuid: str,
) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM sync_log
        WHERE direction='push'
          AND entity_type=?
          AND entity_uuid=?
          AND success=1
        LIMIT 1
        """,
        (
            entity_type,
            entity_uuid,
        ),
    ).fetchone()

    return row is not None


def _enqueue_create_if_required(
    connection: sqlite3.Connection,
    *,
    entity_type: str,
    entity_uuid: str,
    payload: dict[str, Any],
    device_uuid: str,
) -> bool:
    if _queue_exists(
        connection,
        entity_type=entity_type,
        entity_uuid=entity_uuid,
    ):
        return False

    if _successful_push_exists(
        connection,
        entity_type=entity_type,
        entity_uuid=entity_uuid,
    ):
        return False

    queue = SQLiteSyncQueue(
        lambda: connection
    )

    queue.enqueue(
        SyncRecord(
            entity_type=entity_type,
            entity_uuid=entity_uuid,
            operation=OPERATION_CREATE,
            payload=payload,
            device_uuid=device_uuid,
            occurred_at=datetime.now(
                timezone.utc
            ),
        ),
        connection=connection,
    )

    return True


def _category_payload(
    row: sqlite3.Row,
) -> dict[str, Any]:
    return {
        "name": str(row["name"]),
        "sort_order": int(row["sort_order"]),
        "is_active": int(row["is_active"]),
        "created_at": str(row["created_at"]),
        "sync_version": int(row["sync_version"]),
    }


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
        "is_active": int(row["is_active"]),
        "created_at": str(row["created_at"]),
        "sync_version": int(row["sync_version"]),
    }


def recover_legacy_master_data(
    connection: sqlite3.Connection,
) -> LegacyMasterDataRecoveryResult:
    if not isinstance(
        connection,
        sqlite3.Connection,
    ):
        raise TypeError(
            "connection sqlite3.Connection bo'lishi kerak"
        )

    connection.row_factory = sqlite3.Row

    device_uuid = _device_uuid(connection)

    categories_recovered = 0
    products_recovered = 0
    queue_created = 0

    connection.execute(
        "SAVEPOINT legacy_master_data_recovery"
    )

    try:
        categories = connection.execute(
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
            ORDER BY id ASC
            """
        ).fetchall()

        for row in categories:
            entity_uuid = str(
                row["entity_uuid"] or ""
            ).strip()

            recovered = False

            if not entity_uuid:
                entity_uuid = str(uuid.uuid4())

                connection.execute(
                    """
                    UPDATE categories
                    SET
                        entity_uuid=?,
                        sync_version=
                            CASE
                                WHEN sync_version IS NULL
                                     OR sync_version < 1
                                THEN 1
                                ELSE sync_version
                            END
                    WHERE id=?
                    """,
                    (
                        entity_uuid,
                        row["id"],
                    ),
                )

                categories_recovered += 1
                recovered = True

            if recovered:
                fresh = connection.execute(
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
                    (row["id"],),
                ).fetchone()

                if _enqueue_create_if_required(
                    connection,
                    entity_type="category",
                    entity_uuid=entity_uuid,
                    payload=_category_payload(fresh),
                    device_uuid=device_uuid,
                ):
                    queue_created += 1

        products = connection.execute(
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
            ORDER BY p.id ASC
            """
        ).fetchall()

        for row in products:
            entity_uuid = str(
                row["entity_uuid"] or ""
            ).strip()

            recovered = False

            if not entity_uuid:
                entity_uuid = str(uuid.uuid4())

                connection.execute(
                    """
                    UPDATE products
                    SET
                        entity_uuid=?,
                        sync_version=
                            CASE
                                WHEN sync_version IS NULL
                                     OR sync_version < 1
                                THEN 1
                                ELSE sync_version
                            END
                    WHERE id=?
                    """,
                    (
                        entity_uuid,
                        row["id"],
                    ),
                )

                products_recovered += 1
                recovered = True

            if recovered:
                fresh = connection.execute(
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
                    (row["id"],),
                ).fetchone()

                if _enqueue_create_if_required(
                    connection,
                    entity_type="product",
                    entity_uuid=entity_uuid,
                    payload=_product_payload(fresh),
                    device_uuid=device_uuid,
                ):
                    queue_created += 1

        connection.execute(
            "RELEASE SAVEPOINT legacy_master_data_recovery"
        )

    except Exception:
        connection.execute(
            "ROLLBACK TO SAVEPOINT legacy_master_data_recovery"
        )
        connection.execute(
            "RELEASE SAVEPOINT legacy_master_data_recovery"
        )
        raise

    return LegacyMasterDataRecoveryResult(
        categories_recovered=categories_recovered,
        products_recovered=products_recovered,
        queue_created=queue_created,
    )


__all__ = [
    "LegacyMasterDataRecoveryResult",
    "recover_legacy_master_data",
]
