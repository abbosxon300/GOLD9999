from __future__ import annotations

import sqlite3


VERSION = 10
NAME = "sale_payments"


def upgrade(
    connection: sqlite3.Connection,
) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS sale_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            sale_id INTEGER NOT NULL,

            payment_method TEXT NOT NULL
                CHECK (
                    payment_method IN (
                        'CASH',
                        'CLICK'
                    )
                ),

            amount_uzs REAL NOT NULL
                CHECK (amount_uzs > 0),

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (sale_id)
                REFERENCES sales(id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS
            idx_sale_payments_sale
        ON sale_payments(
            sale_id
        );

        CREATE INDEX IF NOT EXISTS
            idx_sale_payments_method
        ON sale_payments(
            payment_method
        );

        CREATE UNIQUE INDEX IF NOT EXISTS
            idx_sale_payments_sale_method
        ON sale_payments(
            sale_id,
            payment_method
        );
        """
    )
