from __future__ import annotations

import sqlite3
from typing import Any

from services.business_writes import (
    consume_stock,
    ensure_sale_cash_move,
)
from services.offline.entity_lookup import (
    find_local_entity,
)
from services.offline.remote_applier import (
    InvalidRemotePayloadError,
    MissingDependencyError,
    RemoteApplyContext,
    RemoteApplyResult,
    StaleRemoteChangeError,
    register_remote_handler,
)
from services.offline.sales_aggregate import (
    InvalidSaleAggregatePayloadError,
    SaleAggregatePayload,
    parse_sale_aggregate_payload,
)


def _float_equal(
    left: object,
    right: object,
    *,
    tolerance: float = 1e-6,
) -> bool:
    try:
        return (
            abs(float(left) - float(right))
            <= tolerance
        )
    except (TypeError, ValueError):
        return False


def _parse_payload(
    context: RemoteApplyContext,
) -> SaleAggregatePayload:
    try:
        aggregate = parse_sale_aggregate_payload(
            context.payload
        )
    except InvalidSaleAggregatePayloadError as exc:
        raise InvalidRemotePayloadError(
            str(exc)
        ) from exc

    if aggregate.entity_uuid != context.entity_uuid:
        raise InvalidRemotePayloadError(
            "Sale payload UUID va record UUID "
            "bir xil bo‘lishi kerak"
        )

    if (
        aggregate.sync_version
        != context.remote_version
    ):
        raise InvalidRemotePayloadError(
            "Sale payload sync_version va "
            "record version bir xil bo‘lishi kerak"
        )

    return aggregate


def _resolve_agent_id(
    connection: sqlite3.Connection,
    username: str | None,
) -> int | None:
    if username is None:
        return None

    row = connection.execute(
        """
        SELECT
            id,
            is_active
        FROM users
        WHERE username=?
        """,
        (username,),
    ).fetchone()

    if row is None:
        raise MissingDependencyError(
            "Sale agent server bazasida "
            f"topilmadi: {username}"
        )

    if int(row["is_active"]) != 1:
        raise MissingDependencyError(
            "Sale agent serverda faol emas: "
            f"{username}"
        )

    return int(row["id"])


def _resolve_products(
    connection: sqlite3.Connection,
    aggregate: SaleAggregatePayload,
) -> dict[str, int]:
    product_ids: dict[str, int] = {}

    for item in aggregate.items:
        if item.product_uuid in product_ids:
            continue

        product = find_local_entity(
            connection,
            "product",
            item.product_uuid,
        )

        if product is None:
            raise MissingDependencyError(
                "Sale mahsuloti server bazasida "
                "topilmadi: "
                f"{item.product_uuid}"
            )

        row = connection.execute(
            """
            SELECT
                id,
                is_active
            FROM products
            WHERE id=?
            """,
            (product.local_id,),
        ).fetchone()

        if row is None:
            raise MissingDependencyError(
                "Sale product row topilmadi: "
                f"{item.product_uuid}"
            )

        if int(row["is_active"]) != 1:
            raise MissingDependencyError(
                "Sale mahsuloti serverda faol emas: "
                f"{item.product_uuid}"
            )

        product_ids[item.product_uuid] = int(
            row["id"]
        )

    return product_ids


def _sale_row(
    connection: sqlite3.Connection,
    sale_id: int,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT
            id,
            sale_date,
            agent_id,
            total_sell_uzs,
            total_cost_uzs,
            total_profit_uzs,
            entity_uuid,
            sync_version
        FROM sales
        WHERE id=?
        """,
        (sale_id,),
    ).fetchone()

    if row is None:
        raise RuntimeError(
            "Sale identity mavjud, "
            "lekin sale row topilmadi"
        )

    return row


def _existing_items(
    connection: sqlite3.Connection,
    sale_id: int,
) -> tuple[sqlite3.Row, ...]:
    rows = connection.execute(
        """
        SELECT
            si.id,
            si.entity_uuid,
            si.sync_version,
            si.product_id,
            si.qty,
            si.sell_price_uzs,
            si.sell_total_uzs,
            si.cost_total_uzs,
            si.profit_uzs,
            p.entity_uuid AS product_uuid
        FROM sale_items si
        JOIN products p
          ON p.id=si.product_id
        WHERE si.sale_id=?
        ORDER BY si.entity_uuid
        """,
        (sale_id,),
    ).fetchall()

    return tuple(rows)


def _aggregate_matches(
    connection: sqlite3.Connection,
    *,
    sale_id: int,
    aggregate: SaleAggregatePayload,
    agent_id: int | None,
) -> bool:
    sale = _sale_row(
        connection,
        sale_id,
    )

    if str(sale["sale_date"]) != aggregate.sale_date:
        return False

    stored_agent_id = (
        int(sale["agent_id"])
        if sale["agent_id"] is not None
        else None
    )

    if stored_agent_id != agent_id:
        return False

    if not _float_equal(
        sale["total_sell_uzs"],
        aggregate.total_sell_uzs,
    ):
        return False

    if not _float_equal(
        sale["total_cost_uzs"],
        aggregate.total_cost_uzs,
    ):
        return False

    if not _float_equal(
        sale["total_profit_uzs"],
        aggregate.total_profit_uzs,
    ):
        return False

    rows = _existing_items(
        connection,
        sale_id,
    )

    if len(rows) != len(aggregate.items):
        return False

    row_by_uuid = {
        str(row["entity_uuid"]): row
        for row in rows
    }

    for item in aggregate.items:
        row = row_by_uuid.get(
            item.entity_uuid
        )

        if row is None:
            return False

        if (
            int(row["sync_version"])
            != item.sync_version
        ):
            return False

        if (
            str(row["product_uuid"])
            != item.product_uuid
        ):
            return False

        if not _float_equal(
            row["qty"],
            item.qty,
        ):
            return False

        if not _float_equal(
            row["sell_price_uzs"],
            item.sell_price_uzs,
        ):
            return False

        if not _float_equal(
            row["sell_total_uzs"],
            item.sell_total_uzs,
        ):
            return False

        if not _float_equal(
            row["cost_total_uzs"],
            item.cost_total_uzs,
        ):
            return False

        if not _float_equal(
            row["profit_uzs"],
            item.profit_uzs,
        ):
            return False

    return True


def _assert_item_uuid_available(
    connection: sqlite3.Connection,
    aggregate: SaleAggregatePayload,
) -> None:
    for item in aggregate.items:
        row = connection.execute(
            """
            SELECT
                id,
                sale_id
            FROM sale_items
            WHERE entity_uuid=?
            """,
            (item.entity_uuid,),
        ).fetchone()

        if row is not None:
            raise InvalidRemotePayloadError(
                "Sale item UUID boshqa yozuvda "
                "allaqachon mavjud: "
                f"{item.entity_uuid}"
            )


def _insert_sale(
    context: RemoteApplyContext,
    aggregate: SaleAggregatePayload,
    *,
    agent_id: int | None,
    product_ids: dict[str, int],
) -> int:
    _assert_item_uuid_available(
        context.connection,
        aggregate,
    )

    try:
        cursor = context.connection.execute(
            """
            INSERT INTO sales(
                sale_date,
                agent_id,
                total_sell_uzs,
                total_cost_uzs,
                total_profit_uzs,
                entity_uuid,
                sync_version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                aggregate.sale_date,
                agent_id,
                aggregate.total_sell_uzs,
                aggregate.total_cost_uzs,
                aggregate.total_profit_uzs,
                aggregate.entity_uuid,
                aggregate.sync_version,
            ),
        )

        sale_id = int(cursor.lastrowid)

        for item in aggregate.items:
            product_id = product_ids[
                item.product_uuid
            ]

            item_cursor = (
                context.connection.execute(
                    """
                    INSERT INTO sale_items(
                        sale_id,
                        product_id,
                        qty,
                        sell_price_uzs,
                        sell_total_uzs,
                        cost_total_uzs,
                        profit_uzs,
                        entity_uuid,
                        sync_version
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sale_id,
                        product_id,
                        item.qty,
                        item.sell_price_uzs,
                        item.sell_total_uzs,
                        item.cost_total_uzs,
                        item.profit_uzs,
                        item.entity_uuid,
                        item.sync_version,
                    ),
                )
            )

            sale_item_id = int(
                item_cursor.lastrowid
            )

            consume_stock(
                context.connection,
                move_date=aggregate.sale_date,
                product_id=product_id,
                qty=item.qty,
                unit_cost_uzs=item.unit_cost_uzs,
                note=f"Remote sotuv #{sale_id}",
                source_type="sale_item",
                source_id=sale_item_id,
            )

        ensure_sale_cash_move(
            context.connection,
            sale_id=sale_id,
            move_date=aggregate.sale_date,
            amount_uzs=aggregate.total_sell_uzs,
            note=f"Auto remote sale #{sale_id}",
        )

    except sqlite3.IntegrityError as exc:
        raise InvalidRemotePayloadError(
            "Sale aggregate database "
            f"chekloviga zid: {exc}"
        ) from exc

    except ValueError as exc:
        raise InvalidRemotePayloadError(
            str(exc)
        ) from exc

    return sale_id


def apply_sales_aggregate_remote(
    context: RemoteApplyContext,
) -> RemoteApplyResult:
    aggregate = _parse_payload(context)

    if context.operation != "create":
        raise InvalidRemotePayloadError(
            "Sales aggregate hozircha faqat "
            "create operationni qabul qiladi"
        )

    agent_id = _resolve_agent_id(
        context.connection,
        aggregate.agent_username,
    )

    if context.existing is not None:
        previous_version = (
            context.existing.sync_version
        )

        if (
            aggregate.sync_version
            != previous_version
        ):
            raise StaleRemoteChangeError(
                "Mavjud sale aggregate "
                "update qilinmaydi"
            )

        if not _aggregate_matches(
            context.connection,
            sale_id=context.existing.local_id,
            aggregate=aggregate,
            agent_id=agent_id,
        ):
            raise StaleRemoteChangeError(
                "Sale aggregate bir xil version "
                "bilan boshqa ma’lumot yubordi"
            )

        return RemoteApplyResult(
            entity_type=context.entity_type,
            entity_uuid=context.entity_uuid,
            local_id=context.existing.local_id,
            previous_version=previous_version,
            applied_version=previous_version,
            created=False,
            changed=False,
        )

    product_ids = _resolve_products(
        context.connection,
        aggregate,
    )

    sale_id = _insert_sale(
        context,
        aggregate,
        agent_id=agent_id,
        product_ids=product_ids,
    )

    return RemoteApplyResult(
        entity_type=context.entity_type,
        entity_uuid=context.entity_uuid,
        local_id=sale_id,
        previous_version=None,
        applied_version=aggregate.sync_version,
        created=True,
        changed=True,
    )


register_remote_handler(
    "sales_aggregate",
    apply_sales_aggregate_remote,
)


__all__ = [
    "apply_sales_aggregate_remote",
]
