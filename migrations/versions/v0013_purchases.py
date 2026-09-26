"""Purchase documents and supplier accounts; legacy inventory stays untouched."""

VERSION = 13
NAME = "purchases_and_suppliers"


def upgrade(db):
    statements = [
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_products_id_tenant ON products(id, tenant_id)",
        """CREATE TABLE suppliers (
            id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL REFERENCES tenants(id),
            name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
            entity_uuid TEXT NOT NULL UNIQUE, sync_version INTEGER NOT NULL DEFAULT 1,
            payload_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(id, tenant_id))""",
        "CREATE INDEX idx_suppliers_tenant_name ON suppliers(tenant_id, name)",
        """CREATE TABLE purchases (
            id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL REFERENCES tenants(id),
            supplier_id INTEGER NOT NULL, purchase_date TEXT NOT NULL,
            reference TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
            total_uzs REAL NOT NULL CHECK(total_uzs > 0),
            entity_uuid TEXT NOT NULL UNIQUE, sync_version INTEGER NOT NULL DEFAULT 1,
            payload_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(id, tenant_id),
            FOREIGN KEY(supplier_id, tenant_id) REFERENCES suppliers(id, tenant_id))""",
        "CREATE INDEX idx_purchases_tenant_date ON purchases(tenant_id, purchase_date, id)",
        "CREATE INDEX idx_purchases_supplier ON purchases(supplier_id)",
        """CREATE TABLE purchase_items (
            id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL,
            purchase_id INTEGER NOT NULL, product_id INTEGER NOT NULL,
            qty REAL NOT NULL CHECK(qty > 0), unit_cost_uzs REAL NOT NULL CHECK(unit_cost_uzs > 0),
            total_uzs REAL NOT NULL CHECK(total_uzs > 0),
            inventory_move_id INTEGER NOT NULL UNIQUE REFERENCES inventory_moves(id),
            FOREIGN KEY(purchase_id, tenant_id) REFERENCES purchases(id, tenant_id),
            FOREIGN KEY(product_id, tenant_id) REFERENCES products(id, tenant_id),
            UNIQUE(purchase_id, product_id))""",
        """CREATE TABLE purchase_payments (
            id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL,
            purchase_id INTEGER NOT NULL, payment_date TEXT NOT NULL,
            amount_uzs REAL NOT NULL CHECK(amount_uzs > 0),
            method TEXT NOT NULL CHECK(method IN ('cash','click')),
            note TEXT NOT NULL DEFAULT '',
            cash_move_id INTEGER UNIQUE REFERENCES cash_moves(id) ON DELETE RESTRICT,
            click_move_id INTEGER UNIQUE REFERENCES click_moves(id) ON DELETE RESTRICT,
            entity_uuid TEXT NOT NULL UNIQUE, sync_version INTEGER NOT NULL DEFAULT 1,
            payload_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(purchase_id, tenant_id) REFERENCES purchases(id, tenant_id),
            CHECK((method='cash' AND cash_move_id IS NOT NULL AND click_move_id IS NULL)
               OR (method='click' AND click_move_id IS NOT NULL AND cash_move_id IS NULL)))""",
        "CREATE INDEX idx_purchase_payments_document ON purchase_payments(purchase_id)",
    ]
    for statement in statements:
        db.execute(statement)
    # Generic cash editors must not detach a payment from its supplier account.
    for table, column in (
        ("cash_moves", "cash_move_id"),
        ("click_moves", "click_move_id"),
    ):
        db.execute(f"""CREATE TRIGGER protect_purchase_{table}_update
            BEFORE UPDATE OF move_date, direction, amount_uzs, sale_id ON {table}
            WHEN EXISTS(SELECT 1 FROM purchase_payments WHERE {column}=OLD.id)
            BEGIN SELECT RAISE(ABORT, 'Kirim tolovini kassadan ozgartirib bolmaydi'); END""")
