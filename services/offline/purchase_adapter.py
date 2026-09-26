"""Purchase replication owns its stock receipts as one aggregate snapshot."""

import json

from services.business_writes.purchases import (
    TABLES,
    create_supplier,
    encoded,
    pay_purchase,
    save_purchase,
    update_purchase,
)
from services.offline.remote_applier import (
    InvalidRemotePayloadError,
    RemoteApplyResult,
    StaleRemoteChangeError,
    register_remote_handler,
)


def _tenant(context):
    if context.tenant_id is not None:
        return context.tenant_id
    tenants = context.connection.execute(
        "SELECT id FROM tenants WHERE is_active=1"
    ).fetchall()
    if len(tenants) != 1:
        raise InvalidRemotePayloadError("Sinxronlash uchun firma aniqlanmadi")
    return tenants[0][0]


def _clean_payload(context):
    payload = dict(context.payload)
    payload.pop("sync_version", None)
    return payload


def _purchase_snapshot(context, tenant_id):
    db = context.connection
    payload = _clean_payload(context)
    existing = db.execute(
        "SELECT id,payload_json,sync_version FROM purchases WHERE entity_uuid=? AND tenant_id=?",
        (context.entity_uuid, tenant_id),
    ).fetchone()

    # A fresh device can receive the current v2/v3 snapshot directly.
    if existing is None:
        local_id = save_purchase(
            db,
            tenant_id=tenant_id,
            entity_uuid=context.entity_uuid,
            payload=payload,
            replicate=False,
        )
        if context.remote_version > 1:
            db.execute(
                "UPDATE purchases SET sync_version=? WHERE id=?",
                (context.remote_version, local_id),
            )
            db.execute(
                """UPDATE inventory_moves SET sync_version=?
                WHERE id IN (
                    SELECT inventory_move_id FROM purchase_items WHERE purchase_id=?
                )""",
                (context.remote_version, local_id),
            )
        return RemoteApplyResult(
            context.entity_type,
            context.entity_uuid,
            local_id,
            None,
            context.remote_version,
            True,
            True,
        )

    current_version = int(existing["sync_version"])
    if context.remote_version == current_version:
        if existing["payload_json"] != encoded(payload):
            raise StaleRemoteChangeError(
                "Kirim bir xil versiya bilan boshqa ma’lumot yubordi"
            )
        return RemoteApplyResult(
            context.entity_type,
            context.entity_uuid,
            int(existing["id"]),
            current_version,
            current_version,
            False,
            False,
        )

    local_id = update_purchase(
        db,
        tenant_id=tenant_id,
        entity_uuid=context.entity_uuid,
        payload=payload,
        expected_version=current_version,
        target_version=context.remote_version,
        replicate=False,
    )
    return RemoteApplyResult(
        context.entity_type,
        context.entity_uuid,
        local_id,
        current_version,
        context.remote_version,
        False,
        True,
    )


def apply_purchase_change(context):
    db = context.connection
    tenant_id = _tenant(context)

    if context.entity_type == "purchase":
        try:
            return _purchase_snapshot(context, tenant_id)
        except (ValueError, TypeError) as exc:
            raise InvalidRemotePayloadError(str(exc)) from exc

    if context.remote_version != 1:
        raise InvalidRemotePayloadError("Bu yozuv turi o‘zgarmas")

    payload = _clean_payload(context)
    try:
        if context.entity_type == "supplier":
            local_id = create_supplier(
                db,
                tenant_id=tenant_id,
                entity_uuid=context.entity_uuid,
                name=payload.get("name"),
                phone=payload.get("phone", ""),
                replicate=False,
            )
        else:
            local_id = pay_purchase(
                db,
                tenant_id=tenant_id,
                entity_uuid=context.entity_uuid,
                payload=payload,
                replicate=False,
            )
    except (ValueError, TypeError) as exc:
        raise InvalidRemotePayloadError(str(exc)) from exc

    created = context.existing is None
    return RemoteApplyResult(
        context.entity_type,
        context.entity_uuid,
        local_id,
        None if created else 1,
        1,
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
            version = int(row["sync_version"])
            changes.append(
                _wire_change(
                    entity_type=kind,
                    entity_uuid=row["entity_uuid"],
                    payload=json.loads(row["payload_json"]),
                    version=version,
                    device_uuid=device_uuid,
                    occurred_at=row["created_at"],
                    operation=("update" if kind == "purchase" and version > 1 else "create"),
                )
            )
    return changes


for kind in TABLES:
    register_remote_handler(kind, apply_purchase_change)
