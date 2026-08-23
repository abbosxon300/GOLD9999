from __future__ import annotations

VERSION = 11
NAME = "click_moves"


def upgrade(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS click_moves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            move_date TEXT NOT NULL
                DEFAULT (date('now')),
            direction TEXT NOT NULL
                CHECK(direction IN ('IN', 'OUT')),
            amount_uzs REAL NOT NULL
                CHECK(amount_uzs > 0),
            note TEXT NOT NULL DEFAULT '',
            sale_id INTEGER,
            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,
            entity_uuid TEXT,
            sync_version INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(sale_id)
                REFERENCES sales(id)
                ON DELETE SET NULL
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
            idx_click_moves_date
        ON click_moves(move_date)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
            idx_click_moves_sale_id
        ON click_moves(sale_id)
        """
    )

    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
            uq_click_moves_sale_in
        ON click_moves(sale_id)
        WHERE sale_id IS NOT NULL
          AND direction='IN'
        """
    )


def downgrade(connection) -> None:
    connection.execute(
        """
        DROP INDEX IF EXISTS
            uq_click_moves_sale_in
        """
    )

    connection.execute(
        """
        DROP INDEX IF EXISTS
            idx_click_moves_sale_id
        """
    )

    connection.execute(
        """
        DROP INDEX IF EXISTS
            idx_click_moves_date
        """
    )

    connection.execute(
        "DROP TABLE IF EXISTS click_moves"
    )
