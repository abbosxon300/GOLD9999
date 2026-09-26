from __future__ import annotations

import sqlite3
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


DEFAULT_PULL_LIMIT = 100
MAX_PULL_LIMIT = 500


class InvalidPullRequestError(ValueError):
    """Pull so‘rovi kontrakti noto‘g‘ri."""


@dataclass(frozen=True, slots=True)
class PullResponse:
    changes: tuple[Mapping[str, Any], ...]
    next_cursor: str | None
    batch_id: str
    has_more: bool


def _required_uuid(
    value: object,
    *,
    field_name: str,
) -> str:
    normalized = str(value or "").strip()

    if not normalized:
        raise InvalidPullRequestError(
            f"{field_name} bo‘sh"
        )

    try:
        return str(uuid.UUID(normalized))
    except ValueError as exc:
        raise InvalidPullRequestError(
            f"{field_name} UUID noto‘g‘ri"
        ) from exc


def _positive_integer(
    value: object,
    *,
    field_name: str,
) -> int:
    if isinstance(value, bool):
        raise InvalidPullRequestError(
            f"{field_name} integer bo‘lishi kerak"
        )

    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidPullRequestError(
            f"{field_name} integer bo‘lishi kerak"
        ) from exc

    if normalized <= 0:
        raise InvalidPullRequestError(
            f"{field_name} musbat bo‘lishi kerak"
        )

    return normalized


def _cursor_offset(
    cursor: str | None,
) -> int:
    if cursor is None:
        return 0

    normalized = str(cursor).strip()

    if not normalized:
        return 0

    if not normalized.isdigit():
        raise InvalidPullRequestError(
            "cursor musbat yoki nol integer bo‘lishi kerak"
        )

    return int(normalized)


def _timestamp(
    value: object,
) -> str:
    normalized = str(value or "").strip()

    if normalized:
        return normalized

    return datetime.now(
        timezone.utc
    ).isoformat(timespec="microseconds")


def _wire_change(
    *,
    entity_type: str,
    entity_uuid: object,
    payload: Mapping[str, Any],
    version: object,
    device_uuid: str,
    occurred_at: object,
) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "entity_uuid": _required_uuid(
            entity_uuid,
            field_name=f"{entity_type}.entity_uuid",
        ),
        "operation": "create",
        "payload": dict(payload),
        "version": _positive_integer(
            version,
            field_name=f"{entity_type}.sync_version",
        ),
        "device_uuid": device_uuid,
        "occurred_at": _timestamp(occurred_at),
    }


def _category_changes(
    connection: sqlite3.Connection,
    *,
    device_uuid: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
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
        WHERE entity_uuid IS NOT NULL
          AND TRIM(entity_uuid) <> ''
        ORDER BY id
        """
    ).fetchall()

    return [
        _wire_change(
            entity_type="category",
            entity_uuid=row["entity_uuid"],
            version=row["sync_version"],
            device_uuid=device_uuid,
            occurred_at=row["created_at"],
            payload={
                "name": row["name"],
                "sort_order": int(row["sort_order"]),
                "is_active": int(row["is_active"]),
                "created_at": str(row["created_at"]),
            },
        )
        for row in rows
    ]


def _product_barcodes(
    connection: sqlite3.Connection,
    product_id: int,
) -> list[str]:
    rows = connection.execute(
        """
        SELECT barcode
        FROM product_barcodes
        WHERE product_id=?
        ORDER BY barcode
        """,
        (int(product_id),),
    ).fetchall()

    return [
        str(row["barcode"])
        for row in rows
    ]


def _product_changes(
    connection: sqlite3.Connection,
    *,
    device_uuid: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            p.id,
            p.name,
            p.sell_price_default_uzs,
            p.is_active,
            p.created_at,
            p.entity_uuid,
            p.sync_version,
            c.entity_uuid AS category_uuid
        FROM products p
        JOIN categories c
          ON c.id=p.category_id
        WHERE p.entity_uuid IS NOT NULL
          AND TRIM(p.entity_uuid) <> ''
          AND c.entity_uuid IS NOT NULL
          AND TRIM(c.entity_uuid) <> ''
        ORDER BY p.id
        """
    ).fetchall()

    return [
        _wire_change(
            entity_type="product",
            entity_uuid=row["entity_uuid"],
            version=row["sync_version"],
            device_uuid=device_uuid,
            occurred_at=row["created_at"],
            payload={
                "name": row["name"],
                "category_uuid": str(
                    row["category_uuid"]
                ),
                "sell_price_default_uzs": float(
                    row["sell_price_default_uzs"]
                ),
                "is_active": int(row["is_active"]),
                "created_at": str(row["created_at"]),
                "barcodes": _product_barcodes(
                    connection,
                    int(row["id"]),
                ),
            },
        )
        for row in rows
    ]


def _inventory_changes(
    connection: sqlite3.Connection,
    *,
    device_uuid: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            im.id,
            im.move_date,
            im.move_type,
            im.qty,
            im.unit_cost_uzs,
            im.note,
            im.created_at,
            im.source_type,
            im.source_id,
            im.entity_uuid,
            im.sync_version,
            p.entity_uuid AS product_uuid
        FROM inventory_moves im
        JOIN products p
          ON p.id=im.product_id
        WHERE im.entity_uuid IS NOT NULL
          AND TRIM(im.entity_uuid) <> ''
          AND p.entity_uuid IS NOT NULL
          AND TRIM(p.entity_uuid) <> ''
          AND COALESCE(im.source_type, '') <> 'sale_item'
        ORDER BY im.id
        """
    ).fetchall()

    return [
        _wire_change(
            entity_type="inventory_move",
            entity_uuid=row["entity_uuid"],
            version=row["sync_version"],
            device_uuid=device_uuid,
            occurred_at=row["created_at"],
            payload={
                "move_date": str(row["move_date"]),
                "move_type": str(row["move_type"]),
                "product_uuid": str(
                    row["product_uuid"]
                ),
                "qty": float(row["qty"]),
                "unit_cost_uzs": float(
                    row["unit_cost_uzs"]
                ),
                "note": row["note"],
                "created_at": str(row["created_at"]),
                "source_type": row["source_type"],
                "source_id": row["source_id"],
            },
        )
        for row in rows
    ]


def _sale_items(
    connection: sqlite3.Connection,
    sale_id: int,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            si.entity_uuid,
            si.sync_version,
            si.qty,
            si.sell_price_uzs,
            si.cost_total_uzs,
            p.entity_uuid AS product_uuid
        FROM sale_items si
        JOIN products p
          ON p.id=si.product_id
        WHERE si.sale_id=?
          AND si.entity_uuid IS NOT NULL
          AND TRIM(si.entity_uuid) <> ''
          AND p.entity_uuid IS NOT NULL
          AND TRIM(p.entity_uuid) <> ''
        ORDER BY si.id
        """,
        (sale_id,),
    ).fetchall()

    items: list[dict[str, Any]] = []

    for row in rows:
        qty = float(row["qty"])

        if qty <= 0:
            raise InvalidPullRequestError(
                f"sale_item qty noto‘g‘ri: sale_id={sale_id}"
            )

        unit_cost = (
            float(row["cost_total_uzs"])
            / qty
        )

        items.append({
            "entity_uuid": str(
                row["entity_uuid"]
            ),
            "sync_version": int(
                row["sync_version"]
            ),
            "product_uuid": str(
                row["product_uuid"]
            ),
            "qty": qty,
            "sell_price_uzs": float(
                row["sell_price_uzs"]
            ),
            "unit_cost_uzs": unit_cost,
        })

    return items


def _sale_changes(
    connection: sqlite3.Connection,
    *,
    device_uuid: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            s.id,
            s.sale_date,
            s.created_at,
            s.entity_uuid,
            s.sync_version
        FROM sales s
        WHERE s.entity_uuid IS NOT NULL
          AND TRIM(s.entity_uuid) <> ''
        ORDER BY s.id
        """
    ).fetchall()

    changes: list[dict[str, Any]] = []

    for row in rows:
        items = _sale_items(
            connection,
            int(row["id"]),
        )

        if not items:
            continue

        payload = {
            "schema_version": 1,
            "entity_uuid": str(
                row["entity_uuid"]
            ),
            "sync_version": int(
                row["sync_version"]
            ),
            "sale_date": str(row["sale_date"]),
            # User replication adapter hali yo‘q.
            # Sotuvning o‘zi yo‘qolmasligi uchun
            # agent vaqtincha None yuboriladi.
            "agent_username": None,
            "items": items,
        }

        changes.append(
            _wire_change(
                entity_type="sales_aggregate",
                entity_uuid=row["entity_uuid"],
                version=row["sync_version"],
                device_uuid=device_uuid,
                occurred_at=row["created_at"],
                payload=payload,
            )
        )

    return changes


def build_pull_response(
    connection: sqlite3.Connection,
    *,
    cursor: str | None,
    limit: int = DEFAULT_PULL_LIMIT,
    device_uuid: str,
    include_purchases: bool = False,
    tenant_id: int | None = None,
) -> PullResponse:
    if not isinstance(
        connection,
        sqlite3.Connection,
    ):
        raise TypeError(
            "connection sqlite3.Connection bo‘lishi kerak"
        )

    normalized_limit = _positive_integer(
        limit,
        field_name="limit",
    )

    if normalized_limit > MAX_PULL_LIMIT:
        raise InvalidPullRequestError(
            f"limit {MAX_PULL_LIMIT} dan katta bo‘lmasligi kerak"
        )

    normalized_device_uuid = _required_uuid(
        device_uuid,
        field_name="device_uuid",
    )

    offset = 0 if include_purchases else _cursor_offset(cursor)

    previous_row_factory = connection.row_factory
    connection.row_factory = sqlite3.Row

    try:
        all_changes = (
            _category_changes(
                connection,
                device_uuid=normalized_device_uuid,
            )
            + _product_changes(
                connection,
                device_uuid=normalized_device_uuid,
            )
            + _inventory_changes(
                connection,
                device_uuid=normalized_device_uuid,
            )
            + _sale_changes(
                connection,
                device_uuid=normalized_device_uuid,
            )
        )
    finally:
        connection.row_factory = previous_row_factory

    if tenant_id is not None:
        # Scope even legacy changes to the authenticated device's business.
        def belongs(change):
            kind = change["entity_type"]
            identity = change["entity_uuid"]
            if kind in ("category", "product"):
                table = "categories" if kind == "category" else "products"
                sql = f"SELECT 1 FROM {table} WHERE entity_uuid=? AND tenant_id=?"
            elif kind == "inventory_move":
                sql = "SELECT 1 FROM inventory_moves m JOIN products p ON p.id=m.product_id WHERE m.entity_uuid=? AND p.tenant_id=?"
            else:
                sql = "SELECT 1 FROM sales s JOIN sale_items i ON i.sale_id=s.id JOIN products p ON p.id=i.product_id WHERE s.entity_uuid=? AND p.tenant_id=?"
            return connection.execute(sql, (identity, tenant_id)).fetchone() is not None
        all_changes = [change for change in all_changes if belongs(change)]
    if include_purchases:
        from services.offline.purchase_adapter import purchase_changes
        previous_factory = connection.row_factory
        connection.row_factory = sqlite3.Row
        try:
            all_changes += purchase_changes(connection, normalized_device_uuid, tenant_id)
        finally:
            connection.row_factory = previous_factory

    # Versioned snapshot cursor: inserts into earlier dependency groups must not
    # make a saved numeric offset silently skip new suppliers or movements.
    fingerprint = None
    if include_purchases:
        fingerprint = hashlib.sha256(json.dumps(all_changes, sort_keys=True, default=str).encode()).hexdigest()[:24]
        parts = str(cursor or "").split(":")
        if len(parts) == 3 and parts[0] == "p1" and parts[1] == fingerprint:
            offset = _cursor_offset(parts[2])

    batch_changes = tuple(
        all_changes[
            offset:offset + normalized_limit
        ]
    )

    next_offset = offset + len(batch_changes)
    has_more = next_offset < len(all_changes)

    return PullResponse(
        changes=batch_changes,
        next_cursor=f"p1:{fingerprint}:{next_offset}" if include_purchases else str(next_offset),
        batch_id=str(uuid.uuid4()),
        has_more=has_more,
    )


def pull_response_to_dict(
    response: PullResponse,
) -> dict[str, Any]:
    if not isinstance(response, PullResponse):
        raise TypeError(
            "response PullResponse bo‘lishi kerak"
        )

    return {
        "changes": [
            dict(change)
            for change in response.changes
        ],
        "next_cursor": response.next_cursor,
        "batch_id": response.batch_id,
        "has_more": response.has_more,
    }


__all__ = [
    "DEFAULT_PULL_LIMIT",
    "InvalidPullRequestError",
    "MAX_PULL_LIMIT",
    "PullResponse",
    "build_pull_response",
    "pull_response_to_dict",
]
