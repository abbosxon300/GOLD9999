from __future__ import annotations

import sqlite3


VERSION = 6
NAME = "remember_login_tokens"


def upgrade(
    connection: sqlite3.Connection,
) -> None:
    connection.executescript(
        """
        CREATE TABLE remember_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            device_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            last_used_at TEXT,
            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        );

        CREATE INDEX
        idx_remember_tokens_user_id
        ON remember_tokens(user_id);

        CREATE INDEX
        idx_remember_tokens_device_id
        ON remember_tokens(device_id);

        CREATE INDEX
        idx_remember_tokens_expires_at
        ON remember_tokens(expires_at);
        """
    )
