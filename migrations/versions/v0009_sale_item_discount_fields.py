from __future__ import annotations

import sqlite3


VERSION = 9
NAME = "sale_item_discount_fields"

TABLE = "sale_items"


def _columns(
    connection: sqlite3.Connection,
) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(
            f'PRAGMA table_info("{TABLE}")'
        ).fetchall()
    }


def upgrade(
    connection: sqlite3.Connection,
) -> None:
    columns = _columns(connection)

    definitions = {
        # Mahsulotning skidkadan oldingi bir dona narxi.
        "list_price_uzs":
            "REAL NOT NULL DEFAULT 0",

        # Skidka turi:
        # none / percent / amount
        "discount_type":
            "TEXT NOT NULL DEFAULT 'none'",

        # Foydalanuvchi kiritgan qiymat:
        # percent bo'lsa %, amount bo'lsa bir dona uchun so'm.
        "discount_value":
            "REAL NOT NULL DEFAULT 0",

        # Shu sale_item bo'yicha jami skidka.
        "discount_total_uzs":
            "REAL NOT NULL DEFAULT 0",
    }

    for column, definition in definitions.items():
        if column in columns:
            continue

        connection.execute(
            f'ALTER TABLE "{TABLE}" '
            f'ADD COLUMN "{column}" {definition}'
        )

    # Eski sotuvlarda skidka bo'lmagan.
    # Ularning original narxi amaldagi sell_price bilan teng.
    connection.execute(
        """
        UPDATE sale_items
        SET list_price_uzs = sell_price_uzs
        WHERE COALESCE(list_price_uzs, 0) <= 0
        """
    )

    connection.execute(
        """
        UPDATE sale_items
        SET
            discount_type = 'none',
            discount_value = 0,
            discount_total_uzs = 0
        WHERE discount_type IS NULL
           OR TRIM(discount_type) = ''
        """
    )


__all__ = [
    "NAME",
    "VERSION",
    "upgrade",
]
