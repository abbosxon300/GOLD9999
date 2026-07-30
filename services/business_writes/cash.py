from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Any


VALID_CASH_DIRECTIONS = frozenset(
    {
        "IN",
        "OUT",
    }
)


@dataclass(frozen=True, slots=True)
class CashMoveResult:
    id: int
    move_date: str
    direction: str
    amount_uzs: float
    note: str
    sale_id: int | None


def normalize_cash_direction(
    value: Any,
) -> str:
    direction = str(
        value or ""
    ).strip().upper()

    if direction not in VALID_CASH_DIRECTIONS:
        raise ValueError(
            "Direction xato (IN/OUT)"
        )

    return direction


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


def _normalize_amount(
    value: Any,
) -> float:
    try:
        amount = float(value)

    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Summa noto‘g‘ri"
        ) from exc

    if (
        not math.isfinite(amount)
        or amount <= 0
    ):
        raise ValueError(
            "Summa noto‘g‘ri"
        )

    return amount


def _normalize_note(
    value: Any,
) -> str:
    return str(
        value or ""
    ).strip()


def _normalize_optional_id(
    value: Any,
    *,
    field_name: str,
) -> int | None:
    if value is None:
        return None

    try:
        normalized = int(value)

    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} noto‘g‘ri"
        ) from exc

    if normalized <= 0:
        raise ValueError(
            f"{field_name} noto‘g‘ri"
        )

    return normalized


def _row_to_result(
    row: sqlite3.Row,
) -> CashMoveResult:
    return CashMoveResult(
        id=int(row["id"]),
        move_date=str(
            row["move_date"] or ""
        ),
        direction=str(
            row["direction"]
        ),
        amount_uzs=float(
            row["amount_uzs"]
        ),
        note=str(
            row["note"] or ""
        ),
        sale_id=(
            int(row["sale_id"])
            if row["sale_id"] is not None
            else None
        ),
    )


def get_cash_move(
    connection: sqlite3.Connection,
    move_id: int,
) -> CashMoveResult | None:
    normalized_id = _normalize_optional_id(
        move_id,
        field_name="Kassa yozuvi",
    )

    row = connection.execute(
        """
        SELECT
            id,
            move_date,
            direction,
            amount_uzs,
            note,
            sale_id
        FROM cash_moves
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


def create_cash_move(
    connection: sqlite3.Connection,
    *,
    move_date: Any = None,
    direction: Any,
    amount_uzs: Any,
    note: Any = "",
    sale_id: Any = None,
) -> CashMoveResult:
    normalized_date = _normalize_move_date(
        move_date
    )
    normalized_direction = (
        normalize_cash_direction(
            direction
        )
    )
    normalized_amount = _normalize_amount(
        amount_uzs
    )
    normalized_note = _normalize_note(
        note
    )
    normalized_sale_id = _normalize_optional_id(
        sale_id,
        field_name="Sotuv",
    )

    cursor = connection.execute(
        """
        INSERT INTO cash_moves(
            move_date,
            direction,
            amount_uzs,
            note,
            sale_id
        )
        VALUES(?,?,?,?,?)
        """,
        (
            normalized_date,
            normalized_direction,
            normalized_amount,
            normalized_note,
            normalized_sale_id,
        ),
    )

    move = get_cash_move(
        connection,
        int(cursor.lastrowid),
    )

    if move is None:
        raise RuntimeError(
            "Kassa yozuvi yaratilmadi"
        )

    return move


def update_cash_move(
    connection: sqlite3.Connection,
    *,
    move_id: int,
    move_date: Any,
    direction: Any,
    amount_uzs: Any,
    note: Any = "",
) -> CashMoveResult:
    current = get_cash_move(
        connection,
        move_id,
    )

    if current is None:
        raise LookupError(
            "Topilmadi"
        )

    if current.sale_id is not None:
        raise ValueError(
            "Auto sale yozuvida faqat izohni "
            "o‘zgartirish mumkin"
        )

    normalized_date = _normalize_move_date(
        move_date
    )
    normalized_direction = (
        normalize_cash_direction(
            direction
        )
    )
    normalized_amount = _normalize_amount(
        amount_uzs
    )
    normalized_note = _normalize_note(
        note
    )

    cursor = connection.execute(
        """
        UPDATE cash_moves
        SET
            move_date=?,
            direction=?,
            amount_uzs=?,
            note=?
        WHERE id=?
        """,
        (
            normalized_date,
            normalized_direction,
            normalized_amount,
            normalized_note,
            current.id,
        ),
    )

    if cursor.rowcount != 1:
        raise RuntimeError(
            "Kassa yozuvi yangilanmadi"
        )

    updated = get_cash_move(
        connection,
        current.id,
    )

    if updated is None:
        raise RuntimeError(
            "Yangilangan kassa yozuvi topilmadi"
        )

    return updated


def update_cash_move_note(
    connection: sqlite3.Connection,
    *,
    move_id: int,
    note: Any,
) -> CashMoveResult:
    current = get_cash_move(
        connection,
        move_id,
    )

    if current is None:
        raise LookupError(
            "Topilmadi"
        )

    normalized_note = _normalize_note(
        note
    )

    cursor = connection.execute(
        """
        UPDATE cash_moves
        SET note=?
        WHERE id=?
        """,
        (
            normalized_note,
            current.id,
        ),
    )

    if cursor.rowcount != 1:
        raise RuntimeError(
            "Kassa izohi yangilanmadi"
        )

    updated = get_cash_move(
        connection,
        current.id,
    )

    if updated is None:
        raise RuntimeError(
            "Yangilangan kassa yozuvi topilmadi"
        )

    return updated


def delete_cash_move(
    connection: sqlite3.Connection,
    *,
    move_id: int,
) -> CashMoveResult:
    current = get_cash_move(
        connection,
        move_id,
    )

    if current is None:
        raise LookupError(
            "Topilmadi"
        )

    if current.sale_id is not None:
        raise ValueError(
            "Auto sale yozuvini o‘chirib bo‘lmaydi"
        )

    cursor = connection.execute(
        """
        DELETE FROM cash_moves
        WHERE id=?
        """,
        (
            current.id,
        ),
    )

    if cursor.rowcount != 1:
        raise RuntimeError(
            "Kassa yozuvi o‘chirilmadi"
        )

    return current


def ensure_sale_cash_move(
    connection: sqlite3.Connection,
    *,
    sale_id: int,
    move_date: Any,
    amount_uzs: Any,
    note: Any | None = None,
) -> CashMoveResult:
    normalized_sale_id = _normalize_optional_id(
        sale_id,
        field_name="Sotuv",
    )

    existing = connection.execute(
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
        (
            normalized_sale_id,
        ),
    ).fetchone()

    if existing is not None:
        return _row_to_result(
            existing
        )

    sale_row = connection.execute(
        """
        SELECT
            id,
            total_sell_uzs
        FROM sales
        WHERE id=?
        """,
        (
            normalized_sale_id,
        ),
    ).fetchone()

    if sale_row is None:
        raise LookupError(
            "Sotuv topilmadi"
        )

    normalized_amount = _normalize_amount(
        amount_uzs
    )
    canonical_total = _normalize_amount(
        sale_row["total_sell_uzs"]
    )

    if abs(
        normalized_amount - canonical_total
    ) > 0.000001:
        raise ValueError(
            "Kassa summasi sotuv summasiga mos emas"
        )

    return create_cash_move(
        connection,
        move_date=move_date,
        direction="IN",
        amount_uzs=canonical_total,
        note=(
            note
            if note is not None
            else (
                f"Auto sale "
                f"#{normalized_sale_id}"
            )
        ),
        sale_id=normalized_sale_id,
    )
