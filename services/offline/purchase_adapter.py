"""Purchase replication reuses movement UUIDs, never device-local IDs."""

import json

from services.business_writes.purchases import (
    create_supplier,
    save_purchase,
    pay_purchase,
    update_purchase,
    TABLES,
)
from services.offline.remote_applier import (
    register_remote_handler,
    RemoteApplyResult,
    InvalidRemotePayloadError,
)


def apply_purchase_change(context):
    db = context.connection
    tenant_id = context.tenant_id
    if tenant_id is None:
        # A desktop has one local tenant. Never guess in a multi-tenant database.
        tenants = db.execute("SELECT id FROM tenants WHERE is_active=1").fetchall()
        if len(tenants) != 1:
            raise InvalidRemotePayloadError("Sinxronlash uchun firma aniqlanmadi")
        tenant_id = tenants[0][0]
    if context.entity_type != "purchase" and context.remote_version != 1:
        raise InvalidRemotePayloadError("Bu yozuv turi o‘zgarmas")
    if context.entity_type == "purchase" and context.remote_version < 1:
        raise InvalidRemotePayloadError("Kirim versiyasi noto‘g‘ri")
    try:
        if context.entity_type == "supplier":
            local_id = create_supplier(
                db,
                tenant_id=tenant_id,
                entity_uuid=context.entity_uuid,
                name=context.payload.get("name"),
                phone=context.payload.get("phone", ""),
                replicate=False,
            )
        elif context.entity_type == "purchase" and context.operation == "update":
            if context.existing is None:
                raise InvalidRemotePayloadError("Yangilanadigan kirim topilmadi")
            local_id = update_purchase(
                db,
                tenant_id=tenant_id,
                entity_uuid=context.entity_uuid,
                payload=dict(context.payload),
                expected_version=context.remote_version - 1,
                replicate=False,
            )
        else:
            save = save_purchase if context.entity_type == "purchase" else pay_purchase
            local_id = save(
                db,
                tenant_id=tenant_id,
                entity_uuid=context.entity_uuid,
                payload=dict(context.payload),
                replicate=False,
            )
    except (ValueError, TypeError) as exc:
        raise InvalidRemotePayloadError(str(exc)) from exc
    created = context.existing is None
    return RemoteApplyResult(
        context.entity_type,
        context.entity_uuid,
        local_id,
        None if created else context.existing.sync_version,
        context.remote_version,
        created,
        created,
    )


def purchase_changes(db, device_uuid, tenant_id=None):
    from services.offline.pull_service import _wire_change

    changes = []
    for kind, table in TABLES.items():
        for row in db.execute(
            f"SELECT * FROM {table} WHERE (? IS NULL OR tenant_id=?) ORDER BY id",
            (tenant_id, tenant_id),
        ):
            changes.append(
                _wire_change(
                    entity_type=kind,
                    entity_uuid=row["entity_uuid"],
                    payload=json.loads(row["payload_json"]),
                    version=row["sync_version"],
                    device_uuid=device_uuid,
                    occurred_at=row["created_at"],
                )
            )
    return changes


for kind in TABLES:
    register_remote_handler(kind, apply_purchase_change)
