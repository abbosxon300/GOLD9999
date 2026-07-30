from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from services.db import get_db


@contextmanager
def business_transaction(
    connection: sqlite3.Connection | None = None,
) -> Iterator[sqlite3.Connection]:
    """
    Provide one explicit SQLite business transaction.

    Rules:
    - Uses the Flask-scoped connection when none is supplied.
    - Starts a transaction only when the connection is not already
      inside a caller-owned transaction.
    - Commits or rolls back only the transaction started here.
    - Never commits or rolls back a caller-owned transaction.
    """
    db = connection or get_db()
    owns_transaction = not db.in_transaction

    if owns_transaction:
        db.execute("BEGIN")

    try:
        yield db

    except Exception:
        if owns_transaction and db.in_transaction:
            db.rollback()
        raise

    else:
        if owns_transaction and db.in_transaction:
            db.commit()
