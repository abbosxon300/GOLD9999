from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from services.offline.constants import (
    OPERATION_CREATE,
    OPERATION_DELETE,
    OPERATION_UPDATE,
)
from services.offline.entity_lookup import (
    EntityIdentity,
    find_local_entity,
    normalize_entity_type,
    normalize_entity_uuid,
)
from services.offline.models import RemoteChange


SUPPORTED_REMOTE_OPERATIONS = frozenset(
    {
        OPERATION_CREATE,
        OPERATION_UPDATE,
    }
)


class RemoteApplyError(RuntimeError):
    """Base error for remote business change application."""


class UnsupportedEntityTypeError(RemoteApplyError):
    """Raised when no replication adapter exists."""


class UnsupportedRemoteOperationError(RemoteApplyError):
    """Raised when the operation is not supported yet."""


class InvalidRemotePayloadError(RemoteApplyError):
    """Raised when a remote payload violates its contract."""


class MissingDependencyError(RemoteApplyError):
    """Raised when a referenced remote entity is missing locally."""


class StaleRemoteChangeError(RemoteApplyError):
    """Raised when remote and local versions cannot be reconciled."""


@dataclass(frozen=True, slots=True)
class RemoteApplyResult:
    entity_type: str
    entity_uuid: str
    local_id: int
    previous_version: int | None
    applied_version: int
    created: bool
    changed: bool


@dataclass(frozen=True, slots=True)
class RemoteApplyContext:
    connection: sqlite3.Connection
    change: RemoteChange
    entity_type: str
    entity_uuid: str
    operation: str
    payload: Mapping[str, Any]
    remote_version: int
    existing: EntityIdentity | None
    tenant_id: int | None = None


RemoteEntityHandler = Callable[
    [RemoteApplyContext],
    RemoteApplyResult,
]


_REMOTE_HANDLERS: dict[
    str,
    RemoteEntityHandler,
] = {}


def _normalize_operation(operation: Any) -> str:
    value = str(
        operation or ""
    ).strip().lower()

    if value == OPERATION_DELETE:
        raise UnsupportedRemoteOperationError(
            "Remote delete uchun tombstone "
            "protokoli hali aniqlanmagan"
        )

    if value not in SUPPORTED_REMOTE_OPERATIONS:
        raise UnsupportedRemoteOperationError(
            f"Remote operation qo‘llab-quvvatlanmaydi: "
            f"{operation}"
        )

    return value


def _normalize_remote_version(version: Any) -> int:
    if isinstance(version, bool):
        raise InvalidRemotePayloadError(
            "Remote version musbat integer "
            "bo‘lishi kerak"
        )

    try:
        normalized = int(version)

    except (TypeError, ValueError) as exc:
        raise InvalidRemotePayloadError(
            "Remote version musbat integer "
            "bo‘lishi kerak"
        ) from exc

    if normalized <= 0:
        raise InvalidRemotePayloadError(
            "Remote version musbat integer "
            "bo‘lishi kerak"
        )

    return normalized


def _normalize_payload(
    payload: Any,
) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise InvalidRemotePayloadError(
            "Remote payload Mapping bo‘lishi kerak"
        )

    return dict(payload)


def _validate_version_gate(
    existing: EntityIdentity | None,
    remote_version: int,
) -> None:
    if existing is None:
        return

    if remote_version < existing.sync_version:
        raise StaleRemoteChangeError(
            "Remote version lokal versiyadan eski: "
            f"remote={remote_version}, "
            f"local={existing.sync_version}"
        )


def register_remote_handler(
    entity_type: str,
    handler: RemoteEntityHandler,
) -> None:
    normalized_type = normalize_entity_type(
        entity_type
    )

    if not callable(handler):
        raise TypeError(
            "Remote handler callable bo‘lishi kerak"
        )

    if normalized_type in _REMOTE_HANDLERS:
        raise RuntimeError(
            "Remote handler allaqachon "
            f"ro‘yxatdan o‘tgan: {normalized_type}"
        )

    _REMOTE_HANDLERS[
        normalized_type
    ] = handler


def get_remote_handler(
    entity_type: str,
) -> RemoteEntityHandler:
    try:
        normalized_type = normalize_entity_type(
            entity_type
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise UnsupportedEntityTypeError(
            f"Remote entity type noto‘g‘ri: "
            f"{entity_type}"
        ) from exc

    handler = _REMOTE_HANDLERS.get(
        normalized_type
    )

    if handler is None:
        raise UnsupportedEntityTypeError(
            "Remote replication adapter hali "
            f"mavjud emas: {normalized_type}"
        )

    return handler


def apply_remote_change(
    connection: sqlite3.Connection,
    change: RemoteChange,
    *,
    tenant_id: int | None = None,
) -> RemoteApplyResult:
    if not isinstance(
        connection,
        sqlite3.Connection,
    ):
        raise TypeError(
            "connection sqlite3.Connection "
            "bo‘lishi kerak"
        )

    if not isinstance(change, RemoteChange):
        raise TypeError(
            "change RemoteChange bo‘lishi kerak"
        )

    try:
        entity_type = normalize_entity_type(
            change.entity_type
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise UnsupportedEntityTypeError(
            f"Remote entity type noto‘g‘ri: "
            f"{change.entity_type}"
        ) from exc

    try:
        entity_uuid = normalize_entity_uuid(
            change.entity_uuid
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise InvalidRemotePayloadError(
            "Remote entity UUID noto‘g‘ri"
        ) from exc

    operation = _normalize_operation(
        change.operation
    )

    payload = _normalize_payload(
        change.payload
    )

    remote_version = _normalize_remote_version(
        change.version
    )

    existing = find_local_entity(
        connection,
        entity_type,
        entity_uuid,
    )

    _validate_version_gate(
        existing,
        remote_version,
    )

    handler = get_remote_handler(
        entity_type
    )

    context = RemoteApplyContext(
        connection=connection,
        change=change,
        entity_type=entity_type,
        entity_uuid=entity_uuid,
        operation=operation,
        payload=payload,
        remote_version=remote_version,
        existing=existing,
        tenant_id=tenant_id,
    )

    result = handler(context)

    if not isinstance(
        result,
        RemoteApplyResult,
    ):
        raise TypeError(
            "Remote handler RemoteApplyResult "
            "qaytarishi kerak"
        )

    return result


__all__ = [
    "InvalidRemotePayloadError",
    "MissingDependencyError",
    "RemoteApplyContext",
    "RemoteApplyError",
    "RemoteApplyResult",
    "RemoteEntityHandler",
    "StaleRemoteChangeError",
    "SUPPORTED_REMOTE_OPERATIONS",
    "UnsupportedEntityTypeError",
    "UnsupportedRemoteOperationError",
    "apply_remote_change",
    "get_remote_handler",
    "register_remote_handler",
]
