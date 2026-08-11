from __future__ import annotations

import sqlite3


VERSION = 8
NAME = "saas_tenant_foundation"


def _columns(
    connection: sqlite3.Connection,
    table: str,
) -> set[str]:
    rows = connection.execute(
        f"PRAGMA table_info({table})"
    ).fetchall()

    return {
        str(row[1])
        for row in rows
    }


def upgrade(
    connection: sqlite3.Connection,
) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS tenants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            is_active INTEGER NOT NULL DEFAULT 1
                CHECK (is_active IN (0, 1)),
            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    tenant = connection.execute(
        """
        SELECT id
        FROM tenants
        ORDER BY id
        LIMIT 1
        """
    ).fetchone()

    if tenant is None:
        cursor = connection.execute(
            """
            INSERT INTO tenants(
                name,
                slug,
                is_active
            )
            VALUES (?, ?, 1)
            """,
            (
                "Default Business",
                "default",
            ),
        )

        default_tenant_id = int(
            cursor.lastrowid
        )
    else:
        default_tenant_id = int(
            tenant[0]
        )

    for table in (
        "users",
        "agents",
        "categories",
        "products",
    ):
        columns = _columns(
            connection,
            table,
        )

        if "tenant_id" not in columns:
            connection.execute(
                f"""
                ALTER TABLE {table}
                ADD COLUMN tenant_id INTEGER
                """
            )

        connection.execute(
            f"""
            UPDATE {table}
            SET tenant_id=?
            WHERE tenant_id IS NULL
            """,
            (default_tenant_id,),
        )

    credential_columns = _columns(
        connection,
        "offline_device_credentials",
    )

    if (
        "tenant_id"
        not in credential_columns
    ):
        connection.execute(
            """
            ALTER TABLE offline_device_credentials
            ADD COLUMN tenant_id INTEGER
            """
        )

    if (
        "user_id"
        not in credential_columns
    ):
        connection.execute(
            """
            ALTER TABLE offline_device_credentials
            ADD COLUMN user_id INTEGER
            """
        )

    connection.executescript(
        """
        CREATE INDEX IF NOT EXISTS
            idx_users_tenant
        ON users(
            tenant_id,
            is_active
        );

        CREATE INDEX IF NOT EXISTS
            idx_agents_tenant
        ON agents(
            tenant_id,
            is_active
        );

        CREATE INDEX IF NOT EXISTS
            idx_categories_tenant
        ON categories(
            tenant_id,
            is_active
        );

        CREATE INDEX IF NOT EXISTS
            idx_products_tenant
        ON products(
            tenant_id,
            is_active
        );

        CREATE INDEX IF NOT EXISTS
            idx_offline_device_credentials_tenant
        ON offline_device_credentials(
            tenant_id,
            user_id,
            installation_uuid,
            revoked_at
        );
        """
    )
