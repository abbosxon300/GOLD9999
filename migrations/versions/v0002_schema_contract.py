"""Install the canonical GOLD9999 business schema.

This migration is safe for both:
- existing production databases;
- completely fresh databases.

v0001 remains an immutable production baseline.
"""

from __future__ import annotations

import sqlite3


VERSION = 2
NAME = "canonical_business_schema"


SCHEMA_STATEMENTS = ['CREATE TABLE IF NOT EXISTS users(\n'
 '      id INTEGER PRIMARY KEY AUTOINCREMENT,\n'
 '      username TEXT UNIQUE NOT NULL,\n'
 '      password_hash TEXT NOT NULL,\n'
 '      full_name TEXT,\n'
 "      role TEXT NOT NULL DEFAULT 'admin', -- admin / agent\n"
 '      is_active INTEGER NOT NULL DEFAULT 1,\n'
 '      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP\n'
 '    )',
 'CREATE TABLE IF NOT EXISTS agents(\n'
 '        id INTEGER PRIMARY KEY AUTOINCREMENT,\n'
 '        full_name TEXT,\n'
 '        phone TEXT,\n'
 '        is_active INTEGER DEFAULT 1\n'
 '    )',
 'CREATE TABLE IF NOT EXISTS categories(\n'
 '      id INTEGER PRIMARY KEY AUTOINCREMENT,\n'
 '      name TEXT UNIQUE NOT NULL,\n'
 '      sort_order INTEGER NOT NULL DEFAULT 100,\n'
 '      is_active INTEGER NOT NULL DEFAULT 1,\n'
 '      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP\n'
 '    )',
 'CREATE TABLE IF NOT EXISTS products(\n'
 '      id INTEGER PRIMARY KEY AUTOINCREMENT,\n'
 '      name TEXT UNIQUE NOT NULL,\n'
 '      category_id INTEGER NOT NULL,\n'
 '      sell_price_default_uzs REAL NOT NULL DEFAULT 0,\n'
 '      is_active INTEGER NOT NULL DEFAULT 1,\n'
 '      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, stock_qty REAL DEFAULT 0,\n'
 '      FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE RESTRICT\n'
 '    )',
 'CREATE TABLE IF NOT EXISTS batches(\n'
 '      id INTEGER PRIMARY KEY AUTOINCREMENT,\n'
 '      product_id INTEGER NOT NULL,\n'
 '      batch_date TEXT NOT NULL,\n'
 '      qty_in REAL NOT NULL,\n'
 '      qty_left REAL NOT NULL,\n'
 '      unit_cost_uzs REAL NOT NULL,\n'
 '      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,\n'
 '      FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT\n'
 '    )',
 'CREATE TABLE IF NOT EXISTS sales(\n'
 '      id INTEGER PRIMARY KEY AUTOINCREMENT,\n'
 '      sale_date TEXT NOT NULL,\n'
 '      agent_id INTEGER,\n'
 '      total_sell_uzs REAL NOT NULL DEFAULT 0,\n'
 '      total_cost_uzs REAL NOT NULL DEFAULT 0,\n'
 '      total_profit_uzs REAL NOT NULL DEFAULT 0,\n'
 '      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,\n'
 '      FOREIGN KEY(agent_id) REFERENCES users(id) ON DELETE SET NULL\n'
 '    )',
 'CREATE TABLE IF NOT EXISTS sale_items(\n'
 '      id INTEGER PRIMARY KEY AUTOINCREMENT,\n'
 '      sale_id INTEGER NOT NULL,\n'
 '      product_id INTEGER NOT NULL,\n'
 '      qty REAL NOT NULL,\n'
 '      sell_price_uzs REAL NOT NULL,\n'
 '      sell_total_uzs REAL NOT NULL,\n'
 '      cost_total_uzs REAL NOT NULL,\n'
 '      profit_uzs REAL NOT NULL,\n'
 '      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,\n'
 '      FOREIGN KEY(sale_id) REFERENCES sales(id) ON DELETE CASCADE,\n'
 '      FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT\n'
 '    )',
 'CREATE TABLE IF NOT EXISTS sale_batch_consumptions(\n'
 '      id INTEGER PRIMARY KEY AUTOINCREMENT,\n'
 '      sale_item_id INTEGER NOT NULL,\n'
 '      batch_id INTEGER NOT NULL,\n'
 '      qty_used REAL NOT NULL,\n'
 '      unit_cost_uzs REAL NOT NULL,\n'
 '      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,\n'
 '      FOREIGN KEY(sale_item_id) REFERENCES sale_items(id) ON DELETE CASCADE,\n'
 '      FOREIGN KEY(batch_id) REFERENCES batches(id) ON DELETE RESTRICT\n'
 '    )',
 'CREATE TABLE IF NOT EXISTS inventory_moves(\n'
 '      id INTEGER PRIMARY KEY AUTOINCREMENT,\n'
 '      move_date TEXT NOT NULL,\n'
 '      move_type TEXT NOT NULL, -- IN / OUT\n'
 '      product_id INTEGER NOT NULL,\n'
 '      qty REAL NOT NULL,\n'
 '      unit_cost_uzs REAL NOT NULL DEFAULT 0,\n'
 '      note TEXT,\n'
 '      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, source_type TEXT, '
 'source_id INTEGER,\n'
 '      FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT\n'
 '    )',
 'CREATE TABLE IF NOT EXISTS cash_moves (\n'
 '  id INTEGER PRIMARY KEY AUTOINCREMENT,\n'
 "  move_date TEXT DEFAULT (date('now')),\n"
 "  direction TEXT NOT NULL,          -- 'IN' yoki 'OUT'\n"
 '  amount_uzs REAL NOT NULL,\n'
 "  note TEXT DEFAULT '',\n"
 "  created_at TEXT DEFAULT (datetime('now'))\n"
 ', sale_id INTEGER)',
 'CREATE INDEX IF NOT EXISTS idx_batches_product ON batches(product_id)',
 'CREATE UNIQUE INDEX IF NOT EXISTS idx_cash_moves_sale_id ON cash_moves(sale_id)',
 'CREATE INDEX IF NOT EXISTS idx_inv_moves_prod_date ON inventory_moves(product_id, '
 'move_date)',
 'CREATE UNIQUE INDEX IF NOT EXISTS idx_inv_moves_source\n'
 '        ON inventory_moves(source_type, source_id)\n'
 '        WHERE source_type IS NOT NULL\n'
 '          AND source_id IS NOT NULL',
 'CREATE INDEX IF NOT EXISTS idx_inv_moves_type_date ON inventory_moves(move_type, '
 'move_date)',
 'CREATE INDEX IF NOT EXISTS idx_inventory_date ON inventory_moves(move_date)',
 'CREATE INDEX IF NOT EXISTS idx_inventory_product ON inventory_moves(product_id)',
 'CREATE INDEX IF NOT EXISTS idx_products_active ON products(is_active)',
 'CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id)']


COLUMN_CONTRACT = {'cash_moves': {'sale_id': 'INTEGER'},
 'products': {'stock_qty': 'REAL NOT NULL DEFAULT 0'},
 'inventory_moves': {'source_type': 'TEXT', 'source_id': 'INTEGER'}}


def _table_columns(
    connection: sqlite3.Connection,
    table: str,
) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(
            f'PRAGMA table_info("{table}")'
        ).fetchall()
    }


def _ensure_columns(
    connection: sqlite3.Connection,
) -> None:
    for table, columns in COLUMN_CONTRACT.items():
        existing = _table_columns(
            connection,
            table,
        )

        for column, definition in columns.items():
            if column in existing:
                continue

            connection.execute(
                f'ALTER TABLE "{table}" '
                f'ADD COLUMN "{column}" {definition}'
            )


def upgrade(
    connection: sqlite3.Connection,
) -> None:
    for statement in SCHEMA_STATEMENTS:
        connection.execute(statement)

    _ensure_columns(connection)

    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
        idx_cash_moves_sale_id
        ON cash_moves(sale_id)
        """
    )

    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
        idx_inv_moves_source
        ON inventory_moves(source_type, source_id)
        WHERE source_type IS NOT NULL
          AND source_id IS NOT NULL
        """
    )
