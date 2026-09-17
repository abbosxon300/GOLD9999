from __future__ import annotations

import sqlite3


VERSION = 12
NAME = "product_barcodes"


def upgrade(
    connection: sqlite3.Connection,
) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS product_barcodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            product_id INTEGER NOT NULL,
            tenant_id INTEGER NOT NULL,

            barcode TEXT NOT NULL
                CHECK (
                    TRIM(barcode) <> ''
                    AND LENGTH(barcode) <= 128
                ),

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (product_id)
                REFERENCES products(id)
                ON DELETE CASCADE,

            FOREIGN KEY (tenant_id)
                REFERENCES tenants(id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS
            idx_product_barcodes_product
        ON product_barcodes(product_id);

        CREATE INDEX IF NOT EXISTS
            idx_product_barcodes_tenant
        ON product_barcodes(tenant_id);

        CREATE UNIQUE INDEX IF NOT EXISTS
            uq_product_barcodes_tenant_barcode
        ON product_barcodes(
            tenant_id,
            barcode
        );

        CREATE TRIGGER IF NOT EXISTS
            trg_product_barcodes_tenant_insert
        BEFORE INSERT ON product_barcodes
        FOR EACH ROW
        WHEN NOT EXISTS (
            SELECT 1
            FROM products p
            WHERE p.id=NEW.product_id
              AND p.tenant_id=NEW.tenant_id
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'product_barcodes tenant mismatch'
            );
        END;

        CREATE TRIGGER IF NOT EXISTS
            trg_product_barcodes_tenant_update
        BEFORE UPDATE OF product_id, tenant_id
        ON product_barcodes
        FOR EACH ROW
        WHEN NOT EXISTS (
            SELECT 1
            FROM products p
            WHERE p.id=NEW.product_id
              AND p.tenant_id=NEW.tenant_id
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'product_barcodes tenant mismatch'
            );
        END;
        """
    )


def downgrade(
    connection: sqlite3.Connection,
) -> None:
    connection.executescript(
        """
        DROP TRIGGER IF EXISTS
            trg_product_barcodes_tenant_update;

        DROP TRIGGER IF EXISTS
            trg_product_barcodes_tenant_insert;

        DROP INDEX IF EXISTS
            uq_product_barcodes_tenant_barcode;

        DROP INDEX IF EXISTS
            idx_product_barcodes_tenant;

        DROP INDEX IF EXISTS
            idx_product_barcodes_product;

        DROP TABLE IF EXISTS product_barcodes;
        """
    )


__all__ = [
    "NAME",
    "VERSION",
    "downgrade",
    "upgrade",
]
