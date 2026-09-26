"""Purchase replication owns its stock receipts as one aggregate snapshot."""

import json

from services.business_writes.purchases import (
    TABLES,
    create_supplier,
    encoded,
    pay_purchase,
    save_purchase,
    update_purchase,
    void_purchase,
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
    wire_payload = _clean_payload(context)
    voided = bool(wire_payload.pop("voided", False))
    payload = wire_payload
    existing = db.execute(
        """SELECT id,payload_json,sync_version,is_void FROM purchases
        WHERE entity_uuid=? AND tenant_id=?""",
        (context.entity_uuid, tenant_id),
    ).fetchone()

    # Fresh device: materialize the current snapshot. A voided snapshot is
    # created then reversed inside the same outer sync transaction, net stock 0.
    if existing is None:
        local_id = save_purchase(
            db,
            tenant_id=tenant_id,
            entity_uuid=context.entity_uuid,
            payload=payload,
            replicate=False,
        )
        if voided:
            void_purchase(
                db,
                tenant_id=tenant_id,
                entity_uuid=context.entity_uuid,
                expected_version=1,
                target_version=context.remote_version,
                replicate=False,
            )
        elif context.remote_version > 1:
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
    current_void = bool(existing["is_void"])
    if context.remote_version == current_version:
        same_payload = existing["payload_json"] == encoded(payload)
        if same_payload and current_void == voided:
            return RemoteApplyResult(
                context.entity_type,
                context.entity_uuid,
                int(existing["id"]),
                current_version,
                current_version,
                False,
                False,
            )
        raise StaleRemoteChangeError(
            "Kirim bir xil versiya bilan boshqa ma’lumot yubordi"
        )

    if current_void and not voided:
        raise InvalidRemotePayloadError("Bekor qilingan kirimni qayta faollashtirib bo‘lmaydi")

    if voided:
        if current_void:
            db.execute(
                "UPDATE purchases SET sync_version=? WHERE id=?",
                (context.remote_version, existing["id"]),
            )
            return RemoteApplyResult(
                context.entity_type,
                context.entity_uuid,
                int(existing["id"]),
                current_version,
                context.remote_version,
                False,
                True,
            )
        local_id = void_purchase(
            db,
            tenant_id=tenant_id,
            entity_uuid=context.entity_uuid,
            expected_version=current_version,
            target_version=context.remote_version,
            replicate=False,
        )
    else:
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
            payload = json.loads(row["payload_json"])
            if kind == "purchase" and int(row["is_void"] or 0):
                payload["voided"] = True
            changes.append(
                _wire_change(
                    entity_type=kind,
                    entity_uuid=row["entity_uuid"],
                    payload=payload,
                    version=version,
                    device_uuid=device_uuid,
                    occurred_at=row["created_at"],
                    operation=("update" if kind == "purchase" and version > 1 else "create"),
                )
            )
    return changes


for kind in TABLES:
    register_remote_handler(kind, apply_purchase_change)
