"""Soft-void purchase documents so delete stays auditable and sync-safe."""

VERSION = 14
NAME = "purchase_voiding"


def upgrade(db):
    db.execute(
        "ALTER TABLE purchases ADD COLUMN is_void INTEGER NOT NULL DEFAULT 0 CHECK(is_void IN (0,1))"
    )
    db.execute(
        "ALTER TABLE purchases ADD COLUMN voided_at TEXT"
    )
    db.execute(
        "CREATE INDEX idx_purchases_tenant_void_date ON purchases(tenant_id,is_void,purchase_date,id)"
    )
