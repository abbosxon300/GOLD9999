from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Any

from services.business_writes.cash import (
    create_cash_move,
)


PAYMENT_CASH = "CASH"
PAYMENT_CLICK = "CLICK"

VALID_PAYMENT_METHODS = frozenset({
    PAYMENT_CASH,
    PAYMENT_CLICK,
})

PAYMENT_TOLERANCE = 0.000001


@dataclass(frozen=True, slots=True)
class SalePaymentResult:
    id: int
    sale_id: int
    payment_method: str
    amount_uzs: float
    created_at: str


@dataclass(frozen=True, slots=True)
class SalePaymentSummary:
    sale_id: int
    total_uzs: float
    cash_uzs: float
    click_uzs: float
    payments: tuple[SalePaymentResult, ...]


def normalize_payment_method(
    value: Any,
) -> str:
    method = str(
        value or ""
    ).strip().upper()

    if method not in VALID_PAYMENT_METHODS:
        raise ValueError(
            "To‘lov turi noto‘g‘ri "
            "(CASH / CLICK)"
        )

    return method


def _normalize_sale_id(
    value: Any,
) -> int:
    try:
        sale_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Sotuv ID noto‘g‘ri"
        ) from exc

    if sale_id <= 0:
        raise ValueError(
            "Sotuv ID noto‘g‘ri"
        )

    return sale_id


def _normalize_non_negative_amount(
    value: Any,
    *,
    field_name: str,
) -> float:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} noto‘g‘ri"
        ) from exc

    if (
        not math.isfinite(amount)
        or amount < 0
    ):
        raise ValueError(
            f"{field_name} noto‘g‘ri"
        )

    return amount


def _sale_total(
    connection: sqlite3.Connection,
    sale_id: int,
) -> float:
    row = connection.execute(
        """
        SELECT
            id,
            total_sell_uzs
        FROM sales
        WHERE id=?
        """,
        (sale_id,),
    ).fetchone()

    if row is None:
        raise LookupError(
            "Sotuv topilmadi"
        )

    total = float(
        row["total_sell_uzs"]
        if isinstance(row, sqlite3.Row)
        else row[1]
    )

    if (
        not math.isfinite(total)
        or total <= 0
    ):
        raise ValueError(
            "Sotuv jami noto‘g‘ri"
        )

    return total


def _payment_row_to_result(
    row: sqlite3.Row,
) -> SalePaymentResult:
    return SalePaymentResult(
        id=int(row["id"]),
        sale_id=int(row["sale_id"]),
        payment_method=str(
            row["payment_method"]
        ),
        amount_uzs=float(
            row["amount_uzs"]
        ),
        created_at=str(
            row["created_at"] or ""
        ),
    )


def get_sale_payments(
    connection: sqlite3.Connection,
    *,
    sale_id: int,
) -> tuple[SalePaymentResult, ...]:
    normalized_sale_id = _normalize_sale_id(
        sale_id
    )

    rows = connection.execute(
        """
        SELECT
            id,
            sale_id,
            payment_method,
            amount_uzs,
            created_at
        FROM sale_payments
        WHERE sale_id=?
        ORDER BY
            CASE payment_method
                WHEN 'CASH' THEN 1
                WHEN 'CLICK' THEN 2
                ELSE 9
            END,
            id
        """,
        (normalized_sale_id,),
    ).fetchall()

    return tuple(
        _payment_row_to_result(row)
        for row in rows
    )


def get_sale_payment_summary(
    connection: sqlite3.Connection,
    *,
    sale_id: int,
) -> SalePaymentSummary:
    normalized_sale_id = _normalize_sale_id(
        sale_id
    )

    payments = get_sale_payments(
        connection,
        sale_id=normalized_sale_id,
    )

    cash = sum(
        row.amount_uzs
        for row in payments
        if row.payment_method == PAYMENT_CASH
    )

    click = sum(
        row.amount_uzs
        for row in payments
        if row.payment_method == PAYMENT_CLICK
    )

    return SalePaymentSummary(
        sale_id=normalized_sale_id,
        total_uzs=cash + click,
        cash_uzs=cash,
        click_uzs=click,
        payments=payments,
    )


def _existing_sale_cash_move(
    connection: sqlite3.Connection,
    sale_id: int,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT
            id,
            move_date,
            direction,
            amount_uzs,
            note,
            sale_id
        FROM cash_moves
        WHERE sale_id=?
        LIMIT 1
        """,
        (sale_id,),
    ).fetchone()


def _assert_existing_state_matches(
    connection: sqlite3.Connection,
    *,
    sale_id: int,
    cash_uzs: float,
    click_uzs: float,
) -> SalePaymentSummary | None:
    summary = get_sale_payment_summary(
        connection,
        sale_id=sale_id,
    )

    if not summary.payments:
        return None

    if (
        abs(summary.cash_uzs - cash_uzs)
        > PAYMENT_TOLERANCE
        or abs(summary.click_uzs - click_uzs)
        > PAYMENT_TOLERANCE
    ):
        raise ValueError(
            "Sotuv paymentlari oldin boshqa "
            "summada saqlangan"
        )

    cash_move = _existing_sale_cash_move(
        connection,
        sale_id,
    )

    if cash_uzs > PAYMENT_TOLERANCE:
        if cash_move is None:
            raise ValueError(
                "Naqd payment bor, lekin "
                "kassa yozuvi topilmadi"
            )

        direction = str(
            cash_move["direction"]
        ).upper()

        amount = float(
            cash_move["amount_uzs"]
        )

        if (
            direction != "IN"
            or abs(amount - cash_uzs)
            > PAYMENT_TOLERANCE
        ):
            raise ValueError(
                "Naqd payment va kassa yozuvi "
                "bir-biriga mos emas"
            )

    elif cash_move is not None:
        raise ValueError(
            "CLICK-only sotuvda Naqd kassa "
            "yozuvi mavjud"
        )

    return summary


def record_sale_payments(
    connection: sqlite3.Connection,
    *,
    sale_id: int,
    cash_uzs: Any = 0,
    click_uzs: Any = 0,
    move_date: Any = None,
) -> SalePaymentSummary:
    normalized_sale_id = _normalize_sale_id(
        sale_id
    )

    normalized_cash = (
        _normalize_non_negative_amount(
            cash_uzs,
            field_name="Naqd summa",
        )
    )

    normalized_click = (
        _normalize_non_negative_amount(
            click_uzs,
            field_name="Click summa",
        )
    )

    if (
        normalized_cash <= PAYMENT_TOLERANCE
        and normalized_click <= PAYMENT_TOLERANCE
    ):
        raise ValueError(
            "Kamida bitta to‘lov summasi "
            "musbat bo‘lishi kerak"
        )

    canonical_total = _sale_total(
        connection,
        normalized_sale_id,
    )

    payment_total = (
        normalized_cash
        + normalized_click
    )

    if abs(
        payment_total - canonical_total
    ) > PAYMENT_TOLERANCE:
        raise ValueError(
            "Naqd + Click summasi "
            "sotuv jami bilan teng emas"
        )

    existing = _assert_existing_state_matches(
        connection,
        sale_id=normalized_sale_id,
        cash_uzs=normalized_cash,
        click_uzs=normalized_click,
    )

    if existing is not None:
        return existing

    stale_cash_move = (
        _existing_sale_cash_move(
            connection,
            normalized_sale_id,
        )
    )

    if stale_cash_move is not None:
        raise ValueError(
            "Sotuv uchun payment yaratilmagan, "
            "lekin eski kassa yozuvi mavjud"
        )

    if normalized_cash > PAYMENT_TOLERANCE:
        connection.execute(
            """
            INSERT INTO sale_payments(
                sale_id,
                payment_method,
                amount_uzs
            )
            VALUES(?, 'CASH', ?)
            """,
            (
                normalized_sale_id,
                normalized_cash,
            ),
        )

        normalized_date = (
            str(move_date).strip()
            if move_date is not None
            else date.today().isoformat()
        )

        create_cash_move(
            connection,
            move_date=normalized_date,
            direction="IN",
            amount_uzs=normalized_cash,
            note=(
                f"Auto CASH sale "
                f"#{normalized_sale_id}"
            ),
            sale_id=normalized_sale_id,
        )

    if normalized_click > PAYMENT_TOLERANCE:
        connection.execute(
            """
            INSERT INTO sale_payments(
                sale_id,
                payment_method,
                amount_uzs
            )
            VALUES(?, 'CLICK', ?)
            """,
            (
                normalized_sale_id,
                normalized_click,
            ),
        )

    result = get_sale_payment_summary(
        connection,
        sale_id=normalized_sale_id,
    )

    if abs(
        result.total_uzs - canonical_total
    ) > PAYMENT_TOLERANCE:
        raise RuntimeError(
            "Saqlangan payment jami "
            "sotuv jami bilan teng emas"
        )

    return result


def payment_method_total(
    connection: sqlite3.Connection,
    *,
    payment_method: Any,
) -> float:
    method = normalize_payment_method(
        payment_method
    )

    row = connection.execute(
        """
        SELECT
            COALESCE(
                SUM(amount_uzs),
                0
            ) AS total
        FROM sale_payments
        WHERE payment_method=?
        """,
        (method,),
    ).fetchone()

    if isinstance(row, sqlite3.Row):
        return float(row["total"] or 0)

    return float(row[0] or 0)


__all__ = [
    "PAYMENT_CASH",
    "PAYMENT_CLICK",
    "PAYMENT_TOLERANCE",
    "SalePaymentResult",
    "SalePaymentSummary",
    "VALID_PAYMENT_METHODS",
    "get_sale_payment_summary",
    "get_sale_payments",
    "normalize_payment_method",
    "payment_method_total",
    "record_sale_payments",
]
