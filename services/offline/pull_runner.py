from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone

from services.offline.api import SyncApi
from services.offline.models import PullBatch
from services.offline.remote_applier import apply_remote_change
from services.offline.sqlite_cursor import SQLiteSyncCursorStore

import services.offline.master_data_adapters
import services.offline.sales_aggregate_adapter


ConnectionFactory = Callable[[], sqlite3.Connection]

DEFAULT_PULL_SCOPE = "business_data"
DEFAULT_MAX_BATCHES = 1000


def _positive_integer(
    value: object,
    *,
    field_name: str,
) -> int:
    if isinstance(value, bool):
        raise TypeError(
            f"{field_name} integer bo‘lishi kerak"
        )

    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"{field_name} integer bo‘lishi kerak"
        ) from exc

    if normalized <= 0:
        raise ValueError(
            f"{field_name} musbat bo‘lishi kerak"
        )

    return normalized


def _required_text(
    value: object,
    *,
    field_name: str,
) -> str:
    if not isinstance(value, str):
        raise TypeError(
            f"{field_name} matn bo‘lishi kerak"
        )

    normalized = value.strip()

    if not normalized:
        raise ValueError(
            f"{field_name} bo‘sh bo‘lishi mumkin emas"
        )

    return normalized


def _validate_batch(batch: PullBatch) -> None:
    if not isinstance(batch, PullBatch):
        raise TypeError(
            "Pull API PullBatch qaytarishi kerak"
        )

    _required_text(
        batch.batch_id,
        field_name="batch_id",
    )

    if not isinstance(batch.has_more, bool):
        raise TypeError(
            "has_more boolean bo‘lishi kerak"
        )

    if batch.has_more and batch.next_cursor is None:
        raise RuntimeError(
            "has_more=True bo‘lsa next_cursor kerak"
        )


def run_remote_pull(
    *,
    api: SyncApi,
    cursor_store: SQLiteSyncCursorStore,
    connection_factory: ConnectionFactory,
    limit: int = 100,
    scope: str = DEFAULT_PULL_SCOPE,
    max_batches: int = DEFAULT_MAX_BATCHES,
) -> int:
    normalized_limit = _positive_integer(
        limit,
        field_name="limit",
    )
    normalized_max_batches = _positive_integer(
        max_batches,
        field_name="max_batches",
    )
    normalized_scope = _required_text(
        scope,
        field_name="scope",
    )

    if not callable(connection_factory):
        raise TypeError(
            "connection_factory callable bo‘lishi kerak"
        )

    state = cursor_store.get(normalized_scope)

    cursor = (
        state.cursor_value
        if state is not None
        else None
    )

    applied_count = 0
    previous_cursor = cursor

    for _ in range(normalized_max_batches):
        batch = api.pull(
            cursor=cursor,
            limit=normalized_limit,
        )

        _validate_batch(batch)

        connection = connection_factory()
        previous_row_factory = connection.row_factory
        connection.row_factory = sqlite3.Row

        try:
            for change in batch.changes:
                apply_remote_change(
                    connection,
                    change,
                )

            cursor_store.save(
                normalized_scope,
                batch.next_cursor,
                last_batch_id=batch.batch_id,
                last_pulled_at=datetime.now(
                    timezone.utc
                ),
                connection=connection,
            )

            connection.commit()

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.row_factory = previous_row_factory
            connection.close()

        applied_count += len(batch.changes)
        cursor = batch.next_cursor

        if not batch.has_more:
            return applied_count

        if cursor == previous_cursor:
            raise RuntimeError(
                "Pull cursor oldinga siljimadi"
            )

        previous_cursor = cursor

    raise RuntimeError(
        "Pull batch limiti tugadi"
    )


__all__ = [
    "DEFAULT_MAX_BATCHES",
    "DEFAULT_PULL_SCOPE",
    "run_remote_pull",
]
