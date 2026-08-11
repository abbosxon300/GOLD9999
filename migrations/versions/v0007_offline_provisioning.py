from __future__ import annotations

import sqlite3


VERSION = 7
NAME = "offline_provisioning"


def upgrade(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS offline_activation_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            used_by_installation_uuid TEXT,
            is_revoked INTEGER NOT NULL DEFAULT 0
                CHECK (is_revoked IN (0, 1))
        );

        CREATE INDEX IF NOT EXISTS
            idx_offline_activation_codes_expires
        ON offline_activation_codes(expires_at);

        CREATE TABLE IF NOT EXISTS offline_device_credentials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            installation_uuid TEXT NOT NULL UNIQUE,
            credential_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            revoked_at TEXT
        );

        CREATE INDEX IF NOT EXISTS
            idx_offline_device_credentials_active
        ON offline_device_credentials(
            installation_uuid,
            revoked_at
        );
        """
    )
