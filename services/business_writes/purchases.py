"""Immutable, atomic purchase documents with portable UUID references."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import UUID, uuid4, uuid5

from services.business_writes.inventory import (
    receive_stock,
    _desktop_sync_enabled,
    _device_uuid,
)
from services.business_writes.transaction import business_transaction

TABLES = {
    "supplier": "suppliers",
    "purchase": "purchases",
    "purchase_payment": "purchase_payments",
}


def text_value(value, label, limit=500, required=False):
    if not isinstance(value, str):
        raise ValueError(f"{label} noto‘g‘ri")
    value = value.strip()
    if len(value) > limit or (required and not value):
        raise ValueError(f"{label}: 1–{limit} belgi kiriting")
    return value


def number(value, label, *, zero=False, places=2):
    try:
        if isinstance(value, bool):
            raise ValueError
        value = Decimal(str(value).replace(" ", "").replace(",", "."))
        if not value.is_finite() or value < 0 or value > Decimal("1000000000000"):
            raise ValueError
        value = value.quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP)
        if not zero and value <= 0:
            raise ValueError
        return float(value)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{label} noto‘g‘ri") from None


def iso_date(value):
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise ValueError("Sana noto‘g‘ri") from None


def uid(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Hujjat identifikatori noto‘g‘ri") from None


def encoded(payload):
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _existing(db, kind, tenant_id, entity_uuid, payload):
    row = db.execute(
        f"SELECT * FROM {TABLES[kind]} WHERE entity_uuid=?", (entity_uuid,)
    ).fetchone()
    if row:
        if row["tenant_id"] != tenant_id or row["payload_json"] != encoded(payload):
            raise ValueError("Bu identifikator bilan boshqa ma’lumot avval saqlangan")
        return row["id"]
    return None


def _queue(db, kind, entity_uuid, payload, operation="create"):
    if not _desktop_sync_enabled():
        return
    from services.offline.models import SyncRecord
    from services.offline.sqlite_queue import SQLiteSyncQueue

    SQLiteSyncQueue(lambda: db).enqueue(
        SyncRecord(
            entity_type=kind,
            entity_uuid=entity_uuid,
            operation=operation,
            payload=payload,
            device_uuid=_device_uuid(db),
            occurred_at=datetime.now(timezone.utc),
        ),
        connection=db,
    )


def create_supplier(db, *, tenant_id, name, phone="", entity_uuid=None, replicate=True):
    entity_uuid = uid(entity_uuid or uuid4())
    payload = {
        "name": text_value(name, "Yetkazuvchi nomi", 160, True),
        "phone": text_value(phone, "Telefon", 40),
    }
    with business_transaction(db):
        existing = _existing(db, "supplier", tenant_id, entity_uuid, payload)
        if existing:
            return existing
        cursor = db.execute(
            """INSERT INTO suppliers(tenant_id,name,phone,entity_uuid,payload_json)
            VALUES(?,?,?,?,?)""",
            (
                tenant_id,
                payload["name"],
                payload["phone"],
                entity_uuid,
                encoded(payload),
            ),
        )
        if replicate:
            _queue(db, "supplier", entity_uuid, payload)
        return cursor.lastrowid


def prepare_purchase(
    db, *, tenant_id, supplier_id, purchase_date, reference, note, items, entity_uuid
):
    supplier = db.execute(
        "SELECT * FROM suppliers WHERE id=? AND tenant_id=?", (supplier_id, tenant_id)
    ).fetchone()
    if not supplier:
        raise ValueError("Yetkazuvchini tanlang")
    if not isinstance(items, list) or not 1 <= len(items) <= 200:
        raise ValueError("1 tadan 200 tagacha mahsulot kiriting")
    purchase_uuid = uid(entity_uuid)
    normalized, seen = [], set()
    # Deterministic movement UUIDs make a repeated form submission identical.
    from uuid import uuid5

    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Mahsulot qatori noto‘g‘ri")
        product = db.execute(
            """SELECT p.* FROM products p JOIN categories c ON c.id=p.category_id
            WHERE p.id=? AND p.tenant_id=? AND c.tenant_id=? AND p.is_active=1 AND c.is_active=1""",
            (item.get("product_id"), tenant_id, tenant_id),
        ).fetchone()
        if not product or product["id"] in seen:
            raise ValueError("Mahsulot topilmadi, nofaol yoki takrorlangan")
        seen.add(product["id"])
        qty = number(item.get("qty"), "Miqdor", places=3)
        cost = number(item.get("unit_cost_uzs"), "Kirim narxi")
        number(Decimal(str(qty)) * Decimal(str(cost)), "Qator summasi")
        normalized.append(
            {
                "product_uuid": uid(product["entity_uuid"]),
                "qty": qty,
                "unit_cost_uzs": cost,
                "move_uuid": str(
                    uuid5(UUID(purchase_uuid), str(product["entity_uuid"]))
                ),
            }
        )
    return {
        "purchase_date": iso_date(purchase_date),
        "reference": text_value(reference, "Hujjat raqami", 80),
        "note": text_value(note, "Izoh"),
        "supplier_uuid": supplier["entity_uuid"],
        "items": normalized,
    }


def save_purchase(db, *, tenant_id, entity_uuid, payload, replicate=True):
    """Can attach already replicated inventory rows without incrementing stock twice."""
    entity_uuid = uid(entity_uuid)
    if not isinstance(payload, dict):
        raise ValueError("Kirim ma’lumoti noto‘g‘ri")
    purchase_date = iso_date(payload.get("purchase_date"))
    reference = text_value(payload.get("reference", ""), "Hujjat raqami", 80)
    note = text_value(payload.get("note", ""), "Izoh")
    supplier_uuid = uid(payload.get("supplier_uuid"))
    items = payload.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 200:
        raise ValueError("Mahsulotlar soni noto‘g‘ri")
    clean, seen, moves = [], set(), set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Mahsulot qatori noto‘g‘ri")
        product_uuid, move_uuid = (
            uid(item.get("product_uuid")),
            uid(item.get("move_uuid")),
        )
        if product_uuid in seen or move_uuid in moves:
            raise ValueError("Takrorlangan mahsulot yoki ombor harakati")
        seen.add(product_uuid)
        moves.add(move_uuid)
        qty = number(item.get("qty"), "Miqdor", places=3)
        cost = number(item.get("unit_cost_uzs"), "Kirim narxi")
        clean.append(
            dict(
                product_uuid=product_uuid,
                move_uuid=move_uuid,
                qty=qty,
                unit_cost_uzs=cost,
            )
        )
    payload = dict(
        purchase_date=purchase_date,
        reference=reference,
        note=note,
        supplier_uuid=supplier_uuid,
        items=clean,
    )
    total = number(
        sum(Decimal(str(i["qty"])) * Decimal(str(i["unit_cost_uzs"])) for i in clean),
        "Jami",
    )
    with business_transaction(db):
        existing = _existing(db, "purchase", tenant_id, entity_uuid, payload)
        if existing:
            return existing
        supplier = db.execute(
            "SELECT id FROM suppliers WHERE entity_uuid=? AND tenant_id=?",
            (supplier_uuid, tenant_id),
        ).fetchone()
        if not supplier:
            raise ValueError("Yetkazuvchi topilmadi")
        cursor = db.execute(
            """INSERT INTO purchases(tenant_id,supplier_id,purchase_date,reference,note,total_uzs,entity_uuid,payload_json)
            VALUES(?,?,?,?,?,?,?,?)""",
            (
                tenant_id,
                supplier["id"],
                purchase_date,
                reference,
                note,
                total,
                entity_uuid,
                encoded(payload),
            ),
        )
        purchase_id = cursor.lastrowid
        for item in clean:
            product = db.execute(
                "SELECT id FROM products WHERE entity_uuid=? AND tenant_id=?",
                (item["product_uuid"], tenant_id),
            ).fetchone()
            if not product:
                raise ValueError("Mahsulot topilmadi")
            movement = db.execute(
                "SELECT * FROM inventory_moves WHERE entity_uuid=?",
                (item["move_uuid"],),
            ).fetchone()
            movement_note = f"Kirim {entity_uuid}"
            if movement:
                if (
                    movement["product_id"] != product["id"]
                    or movement["move_type"] != "IN"
                    or movement["move_date"] != purchase_date
                    or movement["note"] != movement_note
                    or abs(movement["qty"] - item["qty"]) > 1e-9
                    or abs(movement["unit_cost_uzs"] - item["unit_cost_uzs"]) > 1e-9
                    or movement["source_type"] is not None
                ):
                    raise ValueError("Kirim va ombor harakati mos kelmadi")
                move_id = movement["id"]
            else:
                if not replicate:
                    raise ValueError("Kirimning ombor harakati hali sinxronlanmagan")
                move = receive_stock(
                    db,
                    move_date=purchase_date,
                    product_id=product["id"],
                    qty=item["qty"],
                    unit_cost_uzs=item["unit_cost_uzs"],
                    note=movement_note,
                    entity_uuid=item["move_uuid"],
                    replicate=replicate,
                )
                move_id = move.id
            line_total = number(
                Decimal(str(item["qty"])) * Decimal(str(item["unit_cost_uzs"])),
                "Qator summasi",
            )
            db.execute(
                """INSERT INTO purchase_items(tenant_id,purchase_id,product_id,qty,unit_cost_uzs,total_uzs,inventory_move_id)
                VALUES(?,?,?,?,?,?,?)""",
                (
                    tenant_id,
                    purchase_id,
                    product["id"],
                    item["qty"],
                    item["unit_cost_uzs"],
                    line_total,
                    move_id,
                ),
            )
        # Sum rounded lines: the displayed total always equals the sum of visible rows.
        db.execute(
            "UPDATE purchases SET total_uzs=(SELECT SUM(total_uzs) FROM purchase_items WHERE purchase_id=?) WHERE id=?",
            (purchase_id, purchase_id),
        )
        if replicate:
            _queue(db, "purchase", entity_uuid, payload)
        return purchase_id



def update_purchase(db, *, tenant_id, entity_uuid, payload, expected_version, replicate=True):
    """Atomically replace a purchase and its stock receipts."""
    entity_uuid = uid(entity_uuid)
    try:
        expected_version = int(expected_version)
    except (TypeError, ValueError):
        raise ValueError("Kirim versiyasi noto‘g‘ri") from None
    purchase = db.execute(
        "SELECT * FROM purchases WHERE entity_uuid=? AND tenant_id=?",
        (entity_uuid, tenant_id),
    ).fetchone()
    if not purchase:
        raise ValueError("Kirim topilmadi")
    if int(purchase["sync_version"]) != expected_version:
        raise ValueError("Kirim boshqa qurilmada o‘zgargan. Sahifani yangilang")

    supplier_uuid = uid(payload.get("supplier_uuid"))
    supplier = db.execute(
        "SELECT id FROM suppliers WHERE entity_uuid=? AND tenant_id=?",
        (supplier_uuid, tenant_id),
    ).fetchone()
    if not supplier:
        raise ValueError("Yetkazuvchi topilmadi")
    items = payload.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 200:
        raise ValueError("Mahsulotlar soni noto‘g‘ri")
    clean, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Mahsulot qatori noto‘g‘ri")
        product_uuid = uid(item.get("product_uuid"))
        if product_uuid in seen:
            raise ValueError("Takrorlangan mahsulot")
        seen.add(product_uuid)
        product = db.execute(
            "SELECT id FROM products WHERE entity_uuid=? AND tenant_id=? AND is_active=1",
            (product_uuid, tenant_id),
        ).fetchone()
        if not product:
            raise ValueError("Mahsulot topilmadi yoki nofaol")
        clean.append({
            "product_id": product["id"],
            "product_uuid": product_uuid,
            "qty": number(item.get("qty"), "Miqdor", places=3),
            "unit_cost_uzs": number(item.get("unit_cost_uzs"), "Kirim narxi"),
            "move_uuid": str(uuid5(UUID(entity_uuid), product_uuid)),
        })
    purchase_date = iso_date(payload.get("purchase_date"))
    reference = text_value(payload.get("reference", ""), "Hujjat raqami", 80)
    note = text_value(payload.get("note", ""), "Izoh")
    total = round(sum(round(i["qty"] * i["unit_cost_uzs"], 2) for i in clean), 2)
    paid = float(db.execute(
        "SELECT COALESCE(SUM(amount_uzs),0) FROM purchase_payments WHERE purchase_id=?",
        (purchase["id"],),
    ).fetchone()[0] or 0)
    if total + 0.005 < paid:
        raise ValueError("Yangi kirim summasi to‘langan summadan kam bo‘lishi mumkin emas")

    old = db.execute(
        "SELECT * FROM purchase_items WHERE purchase_id=? ORDER BY id",
        (purchase["id"],),
    ).fetchall()
    normalized = {
        "purchase_date": purchase_date,
        "reference": reference,
        "note": note,
        "supplier_uuid": supplier_uuid,
        "items": [
            {k: i[k] for k in ("product_uuid", "qty", "unit_cost_uzs", "move_uuid")}
            for i in clean
        ],
    }
    with business_transaction(db):
        for row in old:
            stock = db.execute(
                "SELECT stock_qty FROM products WHERE id=?", (row["product_id"],)
            ).fetchone()
            if not stock or float(stock[0] or 0) + 1e-9 < float(row["qty"]):
                raise ValueError(
                    "Bu kirimdagi tovarning bir qismi ishlatilgan. "
                    "Eski kirimni qaytarish uchun omborda qoldiq yetarli emas"
                )
            db.execute(
                "UPDATE products SET stock_qty=stock_qty-? WHERE id=?",
                (row["qty"], row["product_id"]),
            )
            db.execute("DELETE FROM inventory_moves WHERE id=?", (row["inventory_move_id"],))
        db.execute("DELETE FROM purchase_items WHERE purchase_id=?", (purchase["id"],))

        new_version = expected_version + 1
        for item in clean:
            move = receive_stock(
                db,
                move_date=purchase_date,
                product_id=item["product_id"],
                qty=item["qty"],
                unit_cost_uzs=item["unit_cost_uzs"],
                note=f"Kirim {entity_uuid}",
                entity_uuid=item["move_uuid"],
                replicate=False,
            )
            db.execute(
                "UPDATE inventory_moves SET sync_version=? WHERE id=?",
                (new_version, move.id),
            )
            line_total = round(item["qty"] * item["unit_cost_uzs"], 2)
            db.execute(
                """INSERT INTO purchase_items(
                    tenant_id,purchase_id,product_id,qty,unit_cost_uzs,total_uzs,inventory_move_id
                ) VALUES(?,?,?,?,?,?,?)""",
                (
                    tenant_id, purchase["id"], item["product_id"], item["qty"],
                    item["unit_cost_uzs"], line_total, move.id,
                ),
            )
        db.execute(
            """UPDATE purchases SET supplier_id=?,purchase_date=?,reference=?,note=?,
               total_uzs=?,payload_json=?,sync_version=? WHERE id=?""",
            (
                supplier["id"], purchase_date, reference, note, total,
                encoded(normalized), new_version, purchase["id"],
            ),
        )
        if replicate:
            _queue(db, "purchase", entity_uuid, normalized, operation="update")
        return purchase["id"]

def pay_purchase(db, *, tenant_id, entity_uuid, payload, replicate=True):
    entity_uuid = uid(entity_uuid)
    if not isinstance(payload, dict):
        raise ValueError("To‘lov ma’lumoti noto‘g‘ri")
    payload = dict(
        purchase_uuid=uid(payload.get("purchase_uuid")),
        payment_date=iso_date(payload.get("payment_date")),
        amount_uzs=number(payload.get("amount_uzs"), "To‘lov"),
        method=text_value(payload.get("method", ""), "To‘lov turi", 10, True),
        note=text_value(payload.get("note", ""), "Izoh"),
    )
    if payload["method"] not in ("cash", "click"):
        raise ValueError("Naqd yoki Click hisobini tanlang")
    with business_transaction(db):
        existing = _existing(db, "purchase_payment", tenant_id, entity_uuid, payload)
        if existing:
            return existing
        purchase = db.execute(
            """SELECT p.*, COALESCE((SELECT SUM(amount_uzs) FROM purchase_payments pp WHERE pp.purchase_id=p.id),0) paid
            FROM purchases p WHERE entity_uuid=? AND tenant_id=?""",
            (payload["purchase_uuid"], tenant_id),
        ).fetchone()
        if not purchase:
            raise ValueError("Kirim topilmadi")
        if payload["payment_date"] < purchase["purchase_date"]:
            raise ValueError("To‘lov sanasi kirim sanasidan oldin bo‘lmasin")
        if payload["amount_uzs"] > round(purchase["total_uzs"] - purchase["paid"], 2):
            raise ValueError("To‘lov qolgan qarzdan oshmasin")
        table = "cash_moves" if payload["method"] == "cash" else "click_moves"
        movement = db.execute(
            f"INSERT INTO {table}(move_date,direction,amount_uzs,note,entity_uuid,sync_version) VALUES(?,'OUT',?,?,?,1)",
            (
                payload["payment_date"],
                payload["amount_uzs"],
                f"Kirim #{purchase['id']} · {payload['note']}",
                entity_uuid,
            ),
        )
        cash_id = movement.lastrowid if payload["method"] == "cash" else None
        click_id = movement.lastrowid if payload["method"] == "click" else None
        cursor = db.execute(
            """INSERT INTO purchase_payments(tenant_id,purchase_id,payment_date,amount_uzs,method,note,cash_move_id,click_move_id,entity_uuid,payload_json)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                tenant_id,
                purchase["id"],
                payload["payment_date"],
                payload["amount_uzs"],
                payload["method"],
                payload["note"],
                cash_id,
                click_id,
                entity_uuid,
                encoded(payload),
            ),
        )
        if replicate:
            _queue(db, "purchase_payment", entity_uuid, payload)
        return cursor.lastrowid
