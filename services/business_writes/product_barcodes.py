from __future__ import annotations

import sqlite3

from services.business_writes.master_data import (
    queue_product_related_update,
)
from services.business_writes.transaction import (
    business_transaction,
)
from services.db import get_db


MAX_BARCODE_LENGTH = 128


def normalize_barcode(
    value: object,
) -> str:
    normalized = str(
        value or ""
    ).strip()

    if not normalized:
        raise ValueError(
            "Shtrix-kod bo‘sh bo‘lishi mumkin emas"
        )

    if len(normalized) > MAX_BARCODE_LENGTH:
        raise ValueError(
            "Shtrix-kod juda uzun"
        )

    if any(
        char.isspace()
        for char in normalized
    ):
        raise ValueError(
            "Shtrix-kod ichida bo‘sh joy bo‘lishi mumkin emas"
        )

    return normalized


def _product_row(
    connection: sqlite3.Connection,
    product_id: int,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT
            id,
            name,
            tenant_id,
            entity_uuid,
            sync_version
        FROM products
        WHERE id=?
        """,
        (int(product_id),),
    ).fetchone()

    if row is None:
        raise LookupError(
            "Mahsulot topilmadi"
        )

    tenant_id = int(
        row["tenant_id"] or 0
    )

    if tenant_id <= 0:
        raise RuntimeError(
            "Mahsulot tenant_id mavjud emas"
        )

    return row


def list_product_barcodes(
    product_id: int,
    *,
    connection: sqlite3.Connection | None = None,
) -> list[sqlite3.Row]:
    con = (
        connection
        if connection is not None
        else get_db()
    )

    _product_row(
        con,
        product_id,
    )

    return con.execute(
        """
        SELECT
            id,
            product_id,
            tenant_id,
            barcode,
            created_at
        FROM product_barcodes
        WHERE product_id=?
        ORDER BY id
        """,
        (int(product_id),),
    ).fetchall()


def add_product_barcode(
    product_id: int,
    *,
    barcode: str,
    connection: sqlite3.Connection | None = None,
) -> int:
    normalized = normalize_barcode(
        barcode
    )

    with business_transaction(
        connection
    ) as tx:
        product = _product_row(
            tx,
            product_id,
        )

        tenant_id = int(
            product["tenant_id"]
        )

        existing = tx.execute(
            """
            SELECT
                pb.id,
                pb.product_id,
                p.name AS product_name
            FROM product_barcodes pb
            JOIN products p
              ON p.id=pb.product_id
            WHERE pb.tenant_id=?
              AND pb.barcode=?
            LIMIT 1
            """,
            (
                tenant_id,
                normalized,
            ),
        ).fetchone()

        if existing is not None:
            if (
                int(existing["product_id"])
                == int(product_id)
            ):
                raise ValueError(
                    "Bu shtrix-kod mahsulotga "
                    "allaqachon qo‘shilgan"
                )

            raise ValueError(
                "Bu shtrix-kod boshqa mahsulotga "
                "biriktirilgan: "
                f"{existing['product_name']}"
            )

        cursor = tx.execute(
            """
            INSERT INTO product_barcodes(
                product_id,
                tenant_id,
                barcode
            )
            VALUES (?, ?, ?)
            """,
            (
                int(product_id),
                tenant_id,
                normalized,
            ),
        )

        queue_product_related_update(
            product_id,
            connection=tx,
        )

        return int(
            cursor.lastrowid
        )


def delete_product_barcode(
    product_id: int,
    barcode_id: int,
    *,
    connection: sqlite3.Connection | None = None,
) -> None:
    with business_transaction(
        connection
    ) as tx:
        _product_row(
            tx,
            product_id,
        )

        row = tx.execute(
            """
            SELECT id
            FROM product_barcodes
            WHERE id=?
              AND product_id=?
            """,
            (
                int(barcode_id),
                int(product_id),
            ),
        ).fetchone()

        if row is None:
            raise LookupError(
                "Shtrix-kod topilmadi"
            )

        cursor = tx.execute(
            """
            DELETE FROM product_barcodes
            WHERE id=?
              AND product_id=?
            """,
            (
                int(barcode_id),
                int(product_id),
            ),
        )

        if cursor.rowcount != 1:
            raise LookupError(
                "Shtrix-kod topilmadi"
            )

        queue_product_related_update(
            product_id,
            connection=tx,
        )



def generate_product_barcode(
    product_id: int,
    *,
    connection: sqlite3.Connection | None = None,
) -> int:
    """Create a barcode only for a product without barcodes."""
    from secrets import randbelow
    from services.barcode_labels import ean13_check_digit

    with business_transaction(connection) as tx:
        # Acquire the SQLite write lock before checking existing codes.
        tx.execute(
            "UPDATE products SET id=id WHERE id=?",
            (int(product_id),),
        )
        product = _product_row(tx, product_id)

        existing = tx.execute(
            "SELECT id FROM product_barcodes "
            "WHERE product_id=? ORDER BY id LIMIT 1",
            (int(product_id),),
        ).fetchone()

        if existing is not None:
            return int(existing["id"])

        for _ in range(100):
            body = "20" + f"{randbelow(10**10):010d}"
            code = body + ean13_check_digit(body)

            duplicate = tx.execute(
                "SELECT 1 FROM product_barcodes WHERE barcode=? LIMIT 1",
                (code,),
            ).fetchone()
            if duplicate is not None:
                continue

            # Use the existing write and sync mechanism.
            return add_product_barcode(
                int(product["id"]),
                barcode=code,
                connection=tx,
            )

        raise RuntimeError("Bo‘sh shtrix-kod yaratilmadi. Qayta urinib ko‘ring.")

__all__ = [
    "generate_product_barcode",
    "MAX_BARCODE_LENGTH",
    "add_product_barcode",
    "delete_product_barcode",
    "list_product_barcodes",
    "normalize_barcode",
]
