from __future__ import annotations

SYNC_STATUS_PENDING = "pending"
SYNC_STATUS_SYNCING = "syncing"
SYNC_STATUS_SYNCED = "synced"
SYNC_STATUS_FAILED = "failed"
SYNC_STATUS_CONFLICT = "conflict"

SYNC_STATUSES = frozenset(
    {
        SYNC_STATUS_PENDING,
        SYNC_STATUS_SYNCING,
        SYNC_STATUS_SYNCED,
        SYNC_STATUS_FAILED,
        SYNC_STATUS_CONFLICT,
    }
)

OPERATION_CREATE = "create"
OPERATION_UPDATE = "update"
OPERATION_DELETE = "delete"

SYNC_OPERATIONS = frozenset(
    {
        OPERATION_CREATE,
        OPERATION_UPDATE,
        OPERATION_DELETE,
    }
)

DIRECTION_PUSH = "push"
DIRECTION_PULL = "pull"

SYNC_DIRECTIONS = frozenset(
    {
        DIRECTION_PUSH,
        DIRECTION_PULL,
    }
)
