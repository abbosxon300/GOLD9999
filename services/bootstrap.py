from __future__ import annotations

import os

from werkzeug.security import generate_password_hash

from services.db import exec_sql, get_db, q1


def init_db(backup_dir: str) -> None:
    os.makedirs(backup_dir, exist_ok=True)

    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      full_name TEXT,
      role TEXT NOT NULL DEFAULT 'admin', -- admin / agent
      is_active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS categories(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT UNIQUE NOT NULL,
      sort_order INTEGER NOT NULL DEFAULT 100,
      is_active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS products(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT UNIQUE NOT NULL,
      category_id INTEGER NOT NULL,
      sell_price_default_uzs REAL NOT NULL DEFAULT 0,
      stock_qty REAL NOT NULL DEFAULT 0,
      is_active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE RESTRICT
    );

    -- Kirim: batch (FIFO)
    CREATE TABLE IF NOT EXISTS batches(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      product_id INTEGER NOT NULL,
      batch_date TEXT NOT NULL,
      qty_in REAL NOT NULL,
      qty_left REAL NOT NULL,
      unit_cost_uzs REAL NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT
    );

    CREATE INDEX IF NOT EXISTS idx_batches_product ON batches(product_id);

    -- Sotuv (faqat so'm)
    CREATE TABLE IF NOT EXISTS sales(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      sale_date TEXT NOT NULL,
      agent_id INTEGER,
      total_sell_uzs REAL NOT NULL DEFAULT 0,
      total_cost_uzs REAL NOT NULL DEFAULT 0,
      total_profit_uzs REAL NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(agent_id) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS sale_items(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      sale_id INTEGER NOT NULL,
      product_id INTEGER NOT NULL,
      qty REAL NOT NULL,
      sell_price_uzs REAL NOT NULL,
      sell_total_uzs REAL NOT NULL,
      cost_total_uzs REAL NOT NULL,
      profit_uzs REAL NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(sale_id) REFERENCES sales(id) ON DELETE CASCADE,
      FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT
    );

    CREATE TABLE IF NOT EXISTS sale_batch_consumptions(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      sale_item_id INTEGER NOT NULL,
      batch_id INTEGER NOT NULL,
      qty_used REAL NOT NULL,
      unit_cost_uzs REAL NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(sale_item_id) REFERENCES sale_items(id) ON DELETE CASCADE,
      FOREIGN KEY(batch_id) REFERENCES batches(id) ON DELETE RESTRICT
    );
    -- Inventory moves (NO FIFO): IN/OUT movements
    CREATE TABLE IF NOT EXISTS inventory_moves(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      move_date TEXT NOT NULL,
      move_type TEXT NOT NULL, -- IN / OUT
      product_id INTEGER NOT NULL,
      qty REAL NOT NULL,
      unit_cost_uzs REAL NOT NULL DEFAULT 0,
      note TEXT,
      source_type TEXT,
      source_id INTEGER,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT
    );

    CREATE INDEX IF NOT EXISTS idx_inv_moves_prod_date
      ON inventory_moves(product_id, move_date);

    CREATE INDEX IF NOT EXISTS idx_inv_moves_type_date
      ON inventory_moves(move_type, move_date);


    """)

    # --- cash_moves: sale_id + unique index (auto kassa IN uchun) ---
    try:
        cur = db.cursor()
        try:
            cols = [r[1] for r in cur.execute("PRAGMA table_info(cash_moves)").fetchall()]
            if "sale_id" not in cols:
                cur.execute("ALTER TABLE cash_moves ADD COLUMN sale_id INTEGER")
        except Exception:
            pass
        try:
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_cash_moves_sale_id ON cash_moves(sale_id)")
        except Exception:
            pass
    except Exception:
        pass
    db.commit()

    # Ensure products.stock_qty exists for older DBs
    try:
        db.execute(
            "ALTER TABLE products "
            "ADD COLUMN stock_qty REAL NOT NULL DEFAULT 0"
        )
        db.commit()
    except Exception:
        # column already exists (or older sqlite limitations)
        pass

    # inventory_moves source identity migration
    inventory_move_columns = {
        row[1]
        for row in db.execute(
            "PRAGMA table_info(inventory_moves)"
        ).fetchall()
    }

    if "source_type" not in inventory_move_columns:
        db.execute(
            "ALTER TABLE inventory_moves "
            "ADD COLUMN source_type TEXT"
        )

    if "source_id" not in inventory_move_columns:
        db.execute(
            "ALTER TABLE inventory_moves "
            "ADD COLUMN source_id INTEGER"
        )

    db.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_inv_moves_source
        ON inventory_moves(source_type, source_id)
        WHERE source_type IS NOT NULL
          AND source_id IS NOT NULL
    """)
    db.commit()

    # default admin
    admin = q1("SELECT id FROM users WHERE username='admin'")
    if not admin:
        exec_sql(
            "INSERT INTO users(username, password_hash, full_name, role) VALUES(?,?,?,?)",
            ("admin", generate_password_hash("admin123"), "Administrator", "admin")
        )
