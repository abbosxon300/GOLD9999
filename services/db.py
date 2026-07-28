from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from flask import g


_db_path: str | None = None


def configure_db(db_path: str) -> None:
    global _db_path

    resolved = Path(db_path).expanduser().resolve()
    _db_path = str(resolved)


def _require_db_path() -> str:
    if not _db_path:
        raise RuntimeError(
            "Database path sozlanmagan. "
            "configure_db() chaqirilishi kerak."
        )

    return _db_path


def get_db() -> sqlite3.Connection:
    connection = g.get("db")

    if connection is None:
        connection = sqlite3.connect(
            _require_db_path()
        )
        connection.row_factory = sqlite3.Row

        # Har bir SQLite connection uchun alohida yoqiladi.
        connection.execute(
            "PRAGMA foreign_keys=ON"
        )

        g.db = connection

    return connection


def close_db(exc: BaseException | None = None) -> None:
    del exc

    connection = g.pop("db", None)

    if connection is not None:
        connection.close()


def q1(
    sql: str,
    params: tuple[Any, ...] = (),
) -> sqlite3.Row | None:
    cursor = get_db().execute(
        sql,
        params,
    )

    return cursor.fetchone()


def q(
    sql: str,
    params: tuple[Any, ...] = (),
) -> list[sqlite3.Row]:
    cursor = get_db().execute(
        sql,
        params,
    )

    return cursor.fetchall()


def exec_sql(
    sql: str,
    params: tuple[Any, ...] = (),
) -> int:
    connection = get_db()

    try:
        cursor = connection.execute(
            sql,
            params,
        )
        connection.commit()
        return int(cursor.lastrowid or 0)

    except Exception:
        connection.rollback()
        raise
