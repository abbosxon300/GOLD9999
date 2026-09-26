"""Supplier-level payments with FIFO allocations and one cash movement."""

VERSION = 15
NAME = "supplier_fifo_payments"


def upgrade(db):
    statements = [
        """CREATE TABLE supplier_payments (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id),
            supplier_id INTEGER NOT NULL,
            payment_date TEXT NOT NULL,
            amount_uzs REAL NOT NULL CHECK(amount_uzs > 0),
            method TEXT NOT NULL CHECK(method IN ('cash','click')),
            note TEXT NOT NULL DEFAULT '',
            cash_move_id INTEGER UNIQUE REFERENCES cash_moves(id) ON DELETE RESTRICT,
            click_move_id INTEGER UNIQUE REFERENCES click_moves(id) ON DELETE RESTRICT,
            entity_uuid TEXT NOT NULL UNIQUE,
            sync_version INTEGER NOT NULL DEFAULT 1,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(id, tenant_id),
            FOREIGN KEY(supplier_id, tenant_id) REFERENCES suppliers(id, tenant_id),
            CHECK((method='cash' AND cash_move_id IS NOT NULL AND click_move_id IS NULL)
               OR (method='click' AND click_move_id IS NOT NULL AND cash_move_id IS NULL))
        )""",
        "CREATE INDEX idx_supplier_payments_supplier_date ON supplier_payments(supplier_id,payment_date,id)",
        """CREATE TABLE supplier_payment_allocations (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL,
            supplier_payment_id INTEGER NOT NULL,
            purchase_id INTEGER NOT NULL,
            amount_uzs REAL NOT NULL CHECK(amount_uzs > 0),
            FOREIGN KEY(supplier_payment_id, tenant_id)
                REFERENCES supplier_payments(id, tenant_id) ON DELETE RESTRICT,
            FOREIGN KEY(purchase_id, tenant_id) REFERENCES purchases(id, tenant_id),
            UNIQUE(supplier_payment_id,purchase_id)
        )""",
        "CREATE INDEX idx_supplier_payment_allocations_purchase ON supplier_payment_allocations(purchase_id)",
    ]
    for statement in statements:
        db.execute(statement)

    for table, column in (
        ("cash_moves", "cash_move_id"),
        ("click_moves", "click_move_id"),
    ):
        db.execute(f"""CREATE TRIGGER protect_supplier_{table}_update
            BEFORE UPDATE OF move_date, direction, amount_uzs, sale_id ON {table}
            WHEN EXISTS(SELECT 1 FROM supplier_payments WHERE {column}=OLD.id)
            BEGIN SELECT RAISE(ABORT, 'Yetkazuvchi tolovini kassadan ozgartirib bolmaydi'); END""")
        db.execute(f"""CREATE TRIGGER protect_supplier_{table}_delete
            BEFORE DELETE ON {table}
            WHEN EXISTS(SELECT 1 FROM supplier_payments WHERE {column}=OLD.id)
            BEGIN SELECT RAISE(ABORT, 'Yetkazuvchi tolovini kassadan ochirib bolmaydi'); END""")
