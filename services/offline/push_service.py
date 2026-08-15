from __future__ import annotations

import sqlite3
import services.offline.master_data_adapters  # noqa: F401
import services.offline.sales_aggregate_adapter  # noqa: F401
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from services.offline.models import (
    RemoteChange,
    SyncResult,
)
from services.offline.remote_applier import (
    InvalidRemotePayloadError,
    MissingDependencyError,
    RemoteApplyError,
    StaleRemoteChangeError,
    UnsupportedEntityTypeError,
    UnsupportedRemoteOperationError,
    apply_remote_change,
)


SYNC_STATUS_SYNCED = "synced"
SYNC_STATUS_CONFLICT = "conflict"
SYNC_STATUS_FAILED = "failed"


class InvalidPushRequestError(ValueError):
    """Push HTTP body server kontraktiga mos emas."""


def _required_text(
    value: object,
    *,
    field_name: str,
) -> str:
    if not isinstance(value, str):
        raise InvalidPushRequestError(
            f"{field_name} matn bo‘lishi kerak"
        )

    normalized = value.strip()

    if not normalized:
        raise InvalidPushRequestError(
            f"{field_name} bo‘sh bo‘lishi mumkin emas"
        )

    return normalized


def _required_mapping(
    value: object,
    *,
    field_name: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidPushRequestError(
            f"{field_name} JSON object bo‘lishi kerak"
        )

    return dict(value)


def _positive_integer(
    value: object,
    *,
    field_name: str,
) -> int:
    if isinstance(value, bool):
        raise InvalidPushRequestError(
            f"{field_name} musbat integer bo‘lishi kerak"
        )

    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidPushRequestError(
            f"{field_name} musbat integer bo‘lishi kerak"
        ) from exc

    if normalized <= 0:
        raise InvalidPushRequestError(
            f"{field_name} musbat integer bo‘lishi kerak"
        )

    return normalized


def _parse_datetime(
    value: object,
    *,
    field_name: str,
) -> datetime:
    normalized = _required_text(
        value,
        field_name=field_name,
    )

    candidate = normalized

    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise InvalidPushRequestError(
            f"{field_name} ISO datetime bo‘lishi kerak"
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed.astimezone(timezone.utc)


def _record_to_change(
    raw_record: object,
) -> RemoteChange:
    record = _required_mapping(
        raw_record,
        field_name="record",
    )

    expected_fields = {
        "entity_type",
        "entity_uuid",
        "operation",
        "payload",
        "device_uuid",
        "occurred_at",
    }

    actual_fields = set(record)

    missing = sorted(
        expected_fields - actual_fields
    )
    extra = sorted(
        actual_fields - expected_fields
    )

    if missing or extra:
        details: list[str] = []

        if missing:
            details.append(
                "missing: " + ", ".join(missing)
            )

        if extra:
            details.append(
                "extra: " + ", ".join(extra)
            )

        raise InvalidPushRequestError(
            "record maydonlari noto‘g‘ri: "
            + "; ".join(details)
        )

    payload = _required_mapping(
        record["payload"],
        field_name="record.payload",
    )

    version = _positive_integer(
        payload.get("sync_version"),
        field_name="record.payload.sync_version",
    )

    if _required_text(
        record["entity_type"],
        field_name="record.entity_type",
    ).strip().lower() in {
        "category",
        "product",
    }:
        payload = dict(payload)
        payload.pop(
            "sync_version",
            None,
        )

    return RemoteChange(
        entity_type=_required_text(
            record["entity_type"],
            field_name="record.entity_type",
        ),
        entity_uuid=_required_text(
            record["entity_uuid"],
            field_name="record.entity_uuid",
        ),
        operation=_required_text(
            record["operation"],
            field_name="record.operation",
        ),
        payload=payload,
        version=version,
        device_uuid=_required_text(
            record["device_uuid"],
            field_name="record.device_uuid",
        ),
        occurred_at=_parse_datetime(
            record["occurred_at"],
            field_name="record.occurred_at",
        ),
    )


def _safe_payload(
    change: RemoteChange | None,
) -> dict[str, Any] | None:
    if change is None:
        return None

    return dict(change.payload)


def _failed_result(
    message: str,
    *,
    change: RemoteChange | None = None,
) -> SyncResult:
    local_version = None

    if change is not None:
        try:
            local_version = int(
                change.payload.get("sync_version")
            )
        except (TypeError, ValueError):
            local_version = None

    return SyncResult(
        success=False,
        status=SYNC_STATUS_FAILED,
        message=message,
        remote_version=None,
        remote_payload=None,
        remote_device_uuid=None,
        local_version=local_version,
    )


def _conflict_result(
    message: str,
    *,
    connection: sqlite3.Connection,
    change: RemoteChange,
) -> SyncResult:
    remote_version = None
    remote_payload = None

    try:
        table_by_entity = {
            "category": "categories",
            "product": "products",
            "inventory_move": "inventory_moves",
            "sale": "sales",
            "cash_move": "cash_moves",
        }

        table = table_by_entity.get(
            change.entity_type.strip().lower()
        )

        if table:
            row = connection.execute(
                f"""
                SELECT sync_version
                FROM "{table}"
                WHERE entity_uuid=?
                """,
                (change.entity_uuid,),
            ).fetchone()

            if row is not None:
                remote_version = int(
                    row["sync_version"]
                )
    except (
        sqlite3.Error,
        KeyError,
        TypeError,
        ValueError,
    ):
        remote_version = None

    try:
        remote_payload = _safe_payload(change)
    except Exception:
        remote_payload = None

    return SyncResult(
        success=False,
        status=SYNC_STATUS_CONFLICT,
        message=message,
        remote_version=remote_version,
        remote_payload=remote_payload,
        remote_device_uuid=None,
        local_version=change.version,
    )


def apply_push_record(
    connection: sqlite3.Connection,
    raw_record: object,
    *,
    tenant_id: int | None = None,
) -> SyncResult:
    if not isinstance(
        connection,
        sqlite3.Connection,
    ):
        raise TypeError(
            "connection sqlite3.Connection bo‘lishi kerak"
        )

    change: RemoteChange | None = None

    try:
        change = _record_to_change(raw_record)

        connection.execute(
            "SAVEPOINT offline_push_record"
        )

        try:
            applied = apply_remote_change(
                connection,
                change,
                tenant_id=tenant_id,
            )

        except Exception:
            connection.execute(
                "ROLLBACK TO SAVEPOINT offline_push_record"
            )
            connection.execute(
                "RELEASE SAVEPOINT offline_push_record"
            )
            raise

        connection.execute(
            "RELEASE SAVEPOINT offline_push_record"
        )

        message = (
            "Remote entity yaratildi"
            if applied.created
            else (
                "Remote entity yangilandi"
                if applied.changed
                else "Remote entity allaqachon synced"
            )
        )

        return SyncResult(
            success=True,
            status=SYNC_STATUS_SYNCED,
            message=message,
            remote_version=applied.applied_version,
            remote_payload=None,
            remote_device_uuid=None,
            local_version=change.version,
        )

    except StaleRemoteChangeError as exc:
        return _conflict_result(
            str(exc),
            connection=connection,
            change=change,
        )

    except (
        InvalidPushRequestError,
        InvalidRemotePayloadError,
        MissingDependencyError,
        UnsupportedEntityTypeError,
        UnsupportedRemoteOperationError,
    ) as exc:
        return _failed_result(
            str(exc),
            change=change,
        )

    except RemoteApplyError as exc:
        return _failed_result(
            str(exc),
            change=change,
        )

    except sqlite3.IntegrityError as exc:
        return _failed_result(
            f"Database constraint xatosi: {exc}",
            change=change,
        )

    except sqlite3.Error as exc:
        return _failed_result(
            f"Database xatosi: {exc}",
            change=change,
        )

    except Exception as exc:
        return _failed_result(
            f"Kutilmagan push xatosi: {exc}",
            change=change,
        )


def apply_push_batch(
    connection: sqlite3.Connection,
    records: Sequence[object],
    *,
    tenant_id: int | None = None,
) -> tuple[SyncResult, ...]:
    if not isinstance(
        connection,
        sqlite3.Connection,
    ):
        raise TypeError(
            "connection sqlite3.Connection bo‘lishi kerak"
        )

    if isinstance(
        records,
        (str, bytes, bytearray),
    ) or not isinstance(records, Sequence):
        raise InvalidPushRequestError(
            "records JSON ro‘yxat bo‘lishi kerak"
        )

    if not records:
        raise InvalidPushRequestError(
            "records bo‘sh bo‘lishi mumkin emas"
        )

    if len(records) > 100:
        raise InvalidPushRequestError(
            "Bir push batchda maksimum 100 record"
        )

    results = tuple(
        apply_push_record(
            connection,
            raw_record,
            tenant_id=tenant_id,
        )
        for raw_record in records
    )

    connection.commit()

    return results


def sync_result_to_dict(
    result: SyncResult,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "success": result.success,
        "status": result.status,
        "message": result.message,
        "remote_version": result.remote_version,
        "remote_payload": (
            dict(result.remote_payload)
            if result.remote_payload is not None
            else None
        ),
        "remote_device_uuid": (
            result.remote_device_uuid
        ),
        "local_version": result.local_version,
    }

    return payload


__all__ = [
    "InvalidPushRequestError",
    "SYNC_STATUS_CONFLICT",
    "SYNC_STATUS_FAILED",
    "SYNC_STATUS_SYNCED",
    "apply_push_batch",
    "apply_push_record",
    "sync_result_to_dict",
]
