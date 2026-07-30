from __future__ import annotations

import os

from werkzeug.security import generate_password_hash

from services.db import exec_sql, get_db, q1
from services.migrations import run_migrations
from services.device_identity import ensure_installation_identity


def init_db(backup_dir: str) -> None:
    """
    Initialize the GOLD9999 database.

    Schema ownership belongs exclusively to versioned migrations.
    Bootstrap only:
    1. prepares the backup directory;
    2. runs pending migrations;
    3. seeds the initial administrator when required.
    """
    os.makedirs(
        backup_dir,
        exist_ok=True,
    )

    connection = get_db()

    run_migrations(connection)
    ensure_installation_identity(connection)

    admin = q1(
        """
        SELECT id
        FROM users
        WHERE username=?
        """,
        ("admin",),
    )

    if admin is None:
        exec_sql(
            """
            INSERT INTO users(
                username,
                password_hash,
                full_name,
                role
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                "admin",
                generate_password_hash(
                    "admin123"
                ),
                "Administrator",
                "admin",
            ),
        )
