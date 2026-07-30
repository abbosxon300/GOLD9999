from __future__ import annotations

VERSION = 3
NAME = "device_identity_foundation"


def upgrade(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS app_metadata (
            id INTEGER PRIMARY KEY
                CHECK (id = 1),
            database_uuid TEXT NOT NULL
                UNIQUE,
            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS app_installations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            installation_uuid TEXT NOT NULL
                UNIQUE,
            database_uuid TEXT NOT NULL,
            hostname TEXT,
            platform TEXT,
            machine TEXT,
            python_version TEXT,
            app_version TEXT,
            is_active INTEGER NOT NULL
                DEFAULT 1
                CHECK (is_active IN (0, 1)),
            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
            idx_app_installations_database_uuid
        ON app_installations(database_uuid)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
            idx_app_installations_active_seen
        ON app_installations(
            is_active,
            last_seen_at
        )
        """
    )
