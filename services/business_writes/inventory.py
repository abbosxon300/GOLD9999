from __future__ import annotations

import math
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from services.db import get_db
from services.device_identity import (
    get_device_identity,
)
from services.offline.constants import (
    OPERATION_CREATE,
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


VALID_INVENTORY_MOVE_TYPES = frozenset(
    {
        "IN",
        "OUT",
    }
)


@dataclass(frozen=True, slots=True)
class InventoryMoveResult:
    id: int
    move_date: str
    move_type: str
    product_id: int
    qty: float
    unit_cost_uzs: float
    note: str
    source_type: str | None
    source_id: int | None


def normalize_inventory_move_type(
    value: Any,
) -> str:
    move_type = str(
        value or ""
    ).strip().upper()

    if move_type not in VALID_INVENTORY_MOVE_TYPES:
        raise ValueError(
            "Ombor harakati turi noto‘g‘ri"
        )

    return move_type


def _normalize_move_date(
    value: Any,
) -> str:
    text = str(
        value or ""
    ).strip()

    if not text:
        return date.today().isoformat()

    try:
        return date.fromisoformat(
            text
        ).isoformat()

    except ValueError as exc:
        raise ValueError(
            "Sana noto‘g‘ri"
        ) from exc


def _normalize_positive_number(
    value: Any,
    *,
    error_message: str,
) -> float:
    try:
        number = float(value)

    except (TypeError, ValueError) as exc:
        raise ValueError(
            error_message
        ) from exc

    if (
        not math.isfinite(number)
        or number <= 0
    ):
        raise ValueError(
            error_message
        )

    return number


def _normalize_non_negative_number(
    value: Any,
    *,
    error_message: str,
) -> float:
    try:
        number = float(value)

    except (TypeError, ValueError) as exc:
        raise ValueError(
            error_message
        ) from exc

    if (
        not math.isfinite(number)
        or number < 0
    ):
        raise ValueError(
            error_message
        )

    return number


def _normalize_positive_id(
    value: Any,
    *,
    error_message: str,
) -> int:
    try:
        normalized = int(value)

    except (TypeError, ValueError) as exc:
        raise ValueError(
            error_message
        ) from exc

    if normalized <= 0:
        raise ValueError(
            error_message
        )

    return normalized


def _normalize_source(
    source_type: Any,
    source_id: Any,
) -> tuple[str | None, int | None]:
    normalized_type = (
        str(source_type).strip()
        if source_type is not None
        else ""
    )

    has_type = bool(normalized_type)
    has_id = source_id is not None

    if has_type != has_id:
        raise ValueError(
            "Ombor manbasi to‘liq ko‘rsatilmagan"
        )

    if not has_type:
        return None, None

    normalized_id = _normalize_positive_id(
        source_id,
        error_message=(
            "Ombor manba identifikatori noto‘g‘ri"
        ),
    )

    return normalized_type, normalized_id


def _normalize_note(
    value: Any,
) -> str:
    return str(
        value or ""
    ).strip()


def _row_to_result(
    row: sqlite3.Row,
) -> InventoryMoveResult:
    return InventoryMoveResult(
        id=int(row["id"]),
        move_date=str(
            row["move_date"]
        ),
        move_type=str(
            row["move_type"]
        ),
        product_id=int(
            row["product_id"]
        ),
        qty=float(
            row["qty"]
        ),
        unit_cost_uzs=float(
            row["unit_cost_uzs"]
        ),
        note=str(
            row["note"] or ""
        ),
        source_type=(
            str(row["source_type"])
            if row["source_type"] is not None
            else None
        ),
        source_id=(
            int(row["source_id"])
            if row["source_id"] is not None
            else None
        ),
    )


def get_inventory_move(
    connection: sqlite3.Connection,
    move_id: int,
) -> InventoryMoveResult | None:
    normalized_id = _normalize_positive_id(
        move_id,
        error_message=(
            "Ombor harakati noto‘g‘ri"
        ),
    )

    row = connection.execute(
        """
        SELECT
            id,
            move_date,
            move_type,
            product_id,
            qty,
            unit_cost_uzs,
            note,
            source_type,
            source_id
        FROM inventory_moves
        WHERE id=?
        """,
        (
            normalized_id,
        ),
    ).fetchone()

    if row is None:
        return None

    return _row_to_result(
        row
    )


def get_product_stock(
    connection: sqlite3.Connection,
    product_id: int,
) -> float:
    normalized_product_id = _normalize_positive_id(
        product_id,
        error_message="Mahsulot noto‘g‘ri",
    )

    row = connection.execute(
        """
        SELECT COALESCE(stock_qty, 0)
        FROM products
        WHERE id=?
        """,
        (
            normalized_product_id,
        ),
    ).fetchone()

    if row is None:
        raise LookupError(
            "Mahsulot topilmadi"
        )

    stock = float(
        row[0] or 0
    )

    if not math.isfinite(stock):
        raise ValueError(
            "Mahsulot qoldig‘i noto‘g‘ri"
        )

    return stock


def _require_product(
    connection: sqlite3.Connection,
    *,
    product_id: Any,
    category_id: Any = None,
    require_active: bool = True,
) -> sqlite3.Row:
    normalized_product_id = _normalize_positive_id(
        product_id,
        error_message="Mahsulot noto‘g‘ri",
    )

    conditions = [
        "id=?",
    ]
    params: list[Any] = [
        normalized_product_id,
    ]

    if category_id is not None:
        normalized_category_id = _normalize_positive_id(
            category_id,
            error_message="Kategoriya noto‘g‘ri",
        )

        conditions.append(
            "category_id=?"
        )
        params.append(
            normalized_category_id
        )

    if require_active:
        conditions.append(
            "is_active=1"
        )

    row = connection.execute(
        f"""
        SELECT
            id,
            category_id,
            is_active,
            COALESCE(stock_qty, 0)
                AS stock_qty
        FROM products
        WHERE {' AND '.join(conditions)}
        """,
        tuple(params),
    ).fetchone()

    if row is None:
        raise ValueError(
            "Mahsulot topilmadi yoki nofaol"
        )

    return row


def record_inventory_move(
    connection: sqlite3.Connection,
    *,
    move_date: Any,
    move_type: Any,
    product_id: Any,
    qty: Any,
    unit_cost_uzs: Any,
    note: Any = "",
    source_type: Any = None,
    source_id: Any = None,
) -> InventoryMoveResult:
    normalized_date = _normalize_move_date(
        move_date
    )

    normalized_type = normalize_inventory_move_type(
        move_type
    )

    normalized_product_id = _normalize_positive_id(
        product_id,
        error_message="Mahsulot noto‘g‘ri",
    )

    normalized_qty = _normalize_positive_number(
        qty,
        error_message="Miqdor noto‘g‘ri",
    )

    normalized_cost = _normalize_non_negative_number(
        unit_cost_uzs,
        error_message="Tannarx noto‘g‘ri",
    )

    normalized_note = _normalize_note(
        note
    )

    (
        normalized_source_type,
        normalized_source_id,
    ) = _normalize_source(
        source_type,
        source_id,
    )

    _require_product(
        connection,
        product_id=normalized_product_id,
        require_active=True,
    )

    cursor = connection.execute(
        """
        INSERT INTO inventory_moves(
            move_date,
            move_type,
            product_id,
            qty,
            unit_cost_uzs,
            note,
            source_type,
            source_id,
            entity_uuid,
            sync_version
        )
        VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            normalized_date,
            normalized_type,
            normalized_product_id,
            normalized_qty,
            normalized_cost,
            normalized_note,
            normalized_source_type,
            normalized_source_id,
            str(uuid.uuid4()),
            1,
        ),
    )

    result = get_inventory_move(
        connection,
        int(cursor.lastrowid),
    )

    if result is None:
        raise RuntimeError(
            "Ombor harakati yaratilmadi"
        )

    if _desktop_sync_enabled():
        row = connection.execute(
            """
            SELECT
                im.entity_uuid,
                im.sync_version,
                im.move_date,
                im.move_type,
                p.entity_uuid AS product_uuid,
                im.qty,
                im.unit_cost_uzs,
                im.note,
                im.source_type,
                im.source_id,
                im.created_at
            FROM inventory_moves im
            JOIN products p
              ON p.id=im.product_id
            WHERE im.id=?
            """,
            (result.id,),
        ).fetchone()

        if row is None:
            raise RuntimeError(
                "Inventory sync row topilmadi"
            )

        entity_uuid = str(
            row["entity_uuid"] or ""
        ).strip()

        product_uuid = str(
            row["product_uuid"] or ""
        ).strip()

        if not entity_uuid:
            raise RuntimeError(
                "Inventory entity_uuid mavjud emas"
            )

        if not product_uuid:
            raise RuntimeError(
                "Mahsulot entity_uuid mavjud emas"
            )

        payload = {
            "move_date": str(
                row["move_date"]
            ),
            "move_type": str(
                row["move_type"]
            ),
            "product_uuid": product_uuid,
            "qty": float(
                row["qty"]
            ),
            "unit_cost_uzs": float(
                row["unit_cost_uzs"] or 0
            ),
            "note": str(
                row["note"] or ""
            ),
            "source_type": (
                str(row["source_type"])
                if row["source_type"] is not None
                else None
            ),
            "source_id": (
                int(row["source_id"])
                if row["source_id"] is not None
                else None
            ),
            "created_at": str(
                row["created_at"]
            ),
            "sync_version": int(
                row["sync_version"]
            ),
        }

        queue = SQLiteSyncQueue(
            lambda: get_db()
        )

        queue.enqueue(
            SyncRecord(
                entity_type="inventory_move",
                entity_uuid=entity_uuid,
                operation=OPERATION_CREATE,
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

    return result


def receive_stock(
    connection: sqlite3.Connection,
    *,
    move_date: Any,
    product_id: Any,
    qty: Any,
    unit_cost_uzs: Any,
    note: Any = "",
    category_id: Any = None,
    source_type: Any = None,
    source_id: Any = None,
) -> InventoryMoveResult:
    normalized_product_id = _normalize_positive_id(
        product_id,
        error_message="Mahsulot noto‘g‘ri",
    )

    normalized_qty = _normalize_positive_number(
        qty,
        error_message="Miqdor noto‘g‘ri",
    )

    _require_product(
        connection,
        product_id=normalized_product_id,
        category_id=category_id,
        require_active=True,
    )

    movement = record_inventory_move(
        connection,
        move_date=move_date,
        move_type="IN",
        product_id=normalized_product_id,
        qty=normalized_qty,
        unit_cost_uzs=unit_cost_uzs,
        note=note,
        source_type=source_type,
        source_id=source_id,
    )

    cursor = connection.execute(
        """
        UPDATE products
        SET stock_qty=
            COALESCE(stock_qty, 0) + ?
        WHERE id=?
        """,
        (
            normalized_qty,
            normalized_product_id,
        ),
    )

    if cursor.rowcount != 1:
        raise RuntimeError(
            "Mahsulot qoldig‘i yangilanmadi"
        )

    return movement


def consume_stock(
    connection: sqlite3.Connection,
    *,
    move_date: Any,
    product_id: Any,
    qty: Any,
    unit_cost_uzs: Any,
    note: Any = "",
    source_type: Any = None,
    source_id: Any = None,
) -> InventoryMoveResult:
    normalized_product_id = _normalize_positive_id(
        product_id,
        error_message="Mahsulot noto‘g‘ri",
    )

    normalized_qty = _normalize_positive_number(
        qty,
        error_message="Miqdor noto‘g‘ri",
    )

    product = _require_product(
        connection,
        product_id=normalized_product_id,
        require_active=True,
    )

    available = float(
        product["stock_qty"] or 0
    )

    if (
        not math.isfinite(available)
        or available + 1e-9 < normalized_qty
    ):
        raise ValueError(
            "Qoldiq yetarli emas"
        )

    movement = record_inventory_move(
        connection,
        move_date=move_date,
        move_type="OUT",
        product_id=normalized_product_id,
        qty=normalized_qty,
        unit_cost_uzs=unit_cost_uzs,
        note=note,
        source_type=source_type,
        source_id=source_id,
    )

    cursor = connection.execute(
        """
        UPDATE products
        SET stock_qty=
            COALESCE(stock_qty, 0) - ?
        WHERE id=?
          AND COALESCE(stock_qty, 0) + 1e-9 >= ?
        """,
        (
            normalized_qty,
            normalized_product_id,
            normalized_qty,
        ),
    )

    if cursor.rowcount != 1:
        raise ValueError(
            "Qoldiq yetarli emas"
        )

    current_stock = get_product_stock(
        connection,
        normalized_product_id,
    )

    if current_stock < -1e-9:
        raise RuntimeError(
            "Mahsulot qoldig‘i manfiy bo‘lib qoldi"
        )

    return movement
