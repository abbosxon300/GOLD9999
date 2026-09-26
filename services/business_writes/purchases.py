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
    "supplier_payment": "supplier_payments",
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
        if kind == "purchase" and "is_void" in row.keys() and int(row["is_void"] or 0):
            raise ValueError("Bu kirim bekor qilingan")
        if row["tenant_id"] != tenant_id or row["payload_json"] != encoded(payload):
            raise ValueError("Bu identifikator bilan boshqa ma’lumot avval saqlangan")
        return row["id"]
    return None


def _queue(db, kind, entity_uuid, payload, operation="create", sync_version=1):
    if not _desktop_sync_enabled():
        return
    from services.offline.models import SyncRecord
    from services.offline.sqlite_queue import SQLiteSyncQueue

    wire_payload = dict(payload)
    wire_payload["sync_version"] = int(sync_version)
    SQLiteSyncQueue(lambda: db).enqueue(
        SyncRecord(
            entity_type=kind,
            entity_uuid=entity_uuid,
            operation=operation,
            payload=wire_payload,
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
                move = receive_stock(
                    db,
                    move_date=purchase_date,
                    product_id=product["id"],
                    qty=item["qty"],
                    unit_cost_uzs=item["unit_cost_uzs"],
                    note=movement_note,
                    entity_uuid=item["move_uuid"],
                    replicate=False,
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



def update_purchase(db, *, tenant_id, entity_uuid, payload, expected_version, target_version=None, replicate=True):
    """Atomically edit a purchase and apply only the resulting stock delta."""
    entity_uuid = uid(entity_uuid)
    try:
        expected_version = int(expected_version)
    except (TypeError, ValueError):
        raise ValueError("Kirim versiyasi noto‘g‘ri") from None
    if expected_version < 1:
        raise ValueError("Kirim versiyasi noto‘g‘ri")
    if target_version is None:
        target_version = expected_version + 1
    try:
        target_version = int(target_version)
    except (TypeError, ValueError):
        raise ValueError("Kirimning yangi versiyasi noto‘g‘ri") from None
    if target_version <= expected_version:
        raise ValueError("Kirimning yangi versiyasi eski versiyadan katta bo‘lishi kerak")
    if not isinstance(payload, dict):
        raise ValueError("Kirim ma’lumoti noto‘g‘ri")

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

    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 200:
        raise ValueError("1 tadan 200 tagacha mahsulot kiriting")
    clean, seen = [], set()
    for item in raw_items:
        if not isinstance(item, dict):
            raise ValueError("Mahsulot qatori noto‘g‘ri")
        product_uuid = uid(item.get("product_uuid"))
        if product_uuid in seen:
            raise ValueError("Takrorlangan mahsulot")
        seen.add(product_uuid)
        product = db.execute(
            """SELECT p.id FROM products p JOIN categories c ON c.id=p.category_id
            WHERE p.entity_uuid=? AND p.tenant_id=? AND c.tenant_id=?
              AND p.is_active=1 AND c.is_active=1""",
            (product_uuid, tenant_id, tenant_id),
        ).fetchone()
        if not product:
            raise ValueError("Mahsulot topilmadi yoki nofaol")
        qty = number(item.get("qty"), "Miqdor", places=3)
        cost = number(item.get("unit_cost_uzs"), "Kirim narxi")
        line_total = number(
            Decimal(str(qty)) * Decimal(str(cost)), "Qator summasi"
        )
        clean.append(
            {
                "product_id": product["id"],
                "product_uuid": product_uuid,
                "qty": qty,
                "unit_cost_uzs": cost,
                "line_total": line_total,
                "move_uuid": str(uuid5(UUID(entity_uuid), product_uuid)),
            }
        )

    purchase_date = iso_date(payload.get("purchase_date"))
    reference = text_value(payload.get("reference", ""), "Hujjat raqami", 80)
    note = text_value(payload.get("note", ""), "Izoh")
    total = number(
        sum(Decimal(str(i["line_total"])) for i in clean), "Jami"
    )
    payment_info = db.execute(
        """SELECT COALESCE(SUM(amount_uzs),0) paid, MIN(payment_date) first_date
        FROM (
            SELECT amount_uzs,payment_date
            FROM purchase_payments
            WHERE purchase_id=?
            UNION ALL
            SELECT a.amount_uzs,sp.payment_date
            FROM supplier_payment_allocations a
            JOIN supplier_payments sp ON sp.id=a.supplier_payment_id
            WHERE a.purchase_id=?
        )""",
        (purchase["id"], purchase["id"]),
    ).fetchone()
    paid = float(payment_info["paid"] or 0)
    if total + 0.005 < paid:
        raise ValueError("Yangi kirim summasi to‘langan summadan kam bo‘lishi mumkin emas")
    if payment_info["first_date"] and purchase_date > payment_info["first_date"]:
        raise ValueError("Kirim sanasi mavjud to‘lov sanasidan keyin bo‘lishi mumkin emas")

    old_rows = db.execute(
        """SELECT i.*,p.entity_uuid product_uuid FROM purchase_items i
        JOIN products p ON p.id=i.product_id
        WHERE i.purchase_id=? AND i.tenant_id=? ORDER BY i.id""",
        (purchase["id"], tenant_id),
    ).fetchall()
    old_by_product = {int(row["product_id"]): row for row in old_rows}
    new_by_product = {int(item["product_id"]): item for item in clean}
    normalized = {
        "purchase_date": purchase_date,
        "reference": reference,
        "note": note,
        "supplier_uuid": supplier_uuid,
        "items": [
            {
                "product_uuid": item["product_uuid"],
                "qty": item["qty"],
                "unit_cost_uzs": item["unit_cost_uzs"],
                "move_uuid": item["move_uuid"],
            }
            for item in clean
        ],
    }

    with business_transaction(db):
        new_version = target_version

        # Removed products: reduce only the stock contributed by this edit.
        for product_id, old in old_by_product.items():
            if product_id in new_by_product:
                continue
            reduction = float(old["qty"])
            cursor = db.execute(
                """UPDATE products SET stock_qty=COALESCE(stock_qty,0)-?
                WHERE id=? AND COALESCE(stock_qty,0)+1e-9>=?""",
                (reduction, product_id, reduction),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "Bu kirimdagi tovar ishlatilgan. Mahsulotni olib tashlash uchun qoldiq yetarli emas"
                )
            db.execute("DELETE FROM purchase_items WHERE id=?", (old["id"],))
            db.execute("DELETE FROM inventory_moves WHERE id=?", (old["inventory_move_id"],))

        # Existing products: apply qty delta and keep the same deterministic move UUID.
        for product_id, item in new_by_product.items():
            old = old_by_product.get(product_id)
            if old is None:
                continue
            delta = float(item["qty"]) - float(old["qty"])
            if delta < -1e-9:
                reduction = -delta
                cursor = db.execute(
                    """UPDATE products SET stock_qty=COALESCE(stock_qty,0)-?
                    WHERE id=? AND COALESCE(stock_qty,0)+1e-9>=?""",
                    (reduction, product_id, reduction),
                )
                if cursor.rowcount != 1:
                    raise ValueError(
                        "Kirim miqdorini kamaytirish uchun omborda qoldiq yetarli emas"
                    )
            elif delta > 1e-9:
                db.execute(
                    "UPDATE products SET stock_qty=COALESCE(stock_qty,0)+? WHERE id=?",
                    (delta, product_id),
                )
            db.execute(
                """UPDATE inventory_moves SET move_date=?,qty=?,unit_cost_uzs=?,note=?,sync_version=?
                WHERE id=?""",
                (
                    purchase_date,
                    item["qty"],
                    item["unit_cost_uzs"],
                    f"Kirim {entity_uuid}",
                    new_version,
                    old["inventory_move_id"],
                ),
            )
            db.execute(
                """UPDATE purchase_items SET qty=?,unit_cost_uzs=?,total_uzs=?
                WHERE id=?""",
                (item["qty"], item["unit_cost_uzs"], item["line_total"], old["id"]),
            )

        # Added products create their owned IN movement without separate inventory replication.
        for product_id, item in new_by_product.items():
            if product_id in old_by_product:
                continue
            move = receive_stock(
                db,
                move_date=purchase_date,
                product_id=product_id,
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
            db.execute(
                """INSERT INTO purchase_items(
                    tenant_id,purchase_id,product_id,qty,unit_cost_uzs,total_uzs,inventory_move_id
                ) VALUES(?,?,?,?,?,?,?)""",
                (
                    tenant_id,
                    purchase["id"],
                    product_id,
                    item["qty"],
                    item["unit_cost_uzs"],
                    item["line_total"],
                    move.id,
                ),
            )

        db.execute(
            """UPDATE purchases SET supplier_id=?,purchase_date=?,reference=?,note=?,
               total_uzs=?,payload_json=?,sync_version=? WHERE id=?""",
            (
                supplier["id"],
                purchase_date,
                reference,
                note,
                total,
                encoded(normalized),
                new_version,
                purchase["id"],
            ),
        )
        if replicate:
            _queue(
                db,
                "purchase",
                entity_uuid,
                normalized,
                operation="update",
                sync_version=new_version,
            )
        return purchase["id"]




def void_purchase(
    db,
    *,
    tenant_id,
    entity_uuid,
    expected_version,
    target_version=None,
    replicate=True,
):
    """Reverse an unpaid purchase from stock while retaining an audit tombstone."""
    entity_uuid = uid(entity_uuid)
    try:
        expected_version = int(expected_version)
    except (TypeError, ValueError):
        raise ValueError("Kirim versiyasi noto‘g‘ri") from None
    if expected_version < 1:
        raise ValueError("Kirim versiyasi noto‘g‘ri")
    if target_version is None:
        target_version = expected_version + 1
    try:
        target_version = int(target_version)
    except (TypeError, ValueError):
        raise ValueError("Kirimning yangi versiyasi noto‘g‘ri") from None
    if target_version <= expected_version:
        raise ValueError("Kirimning yangi versiyasi eski versiyadan katta bo‘lishi kerak")

    purchase = db.execute(
        "SELECT * FROM purchases WHERE entity_uuid=? AND tenant_id=?",
        (entity_uuid, tenant_id),
    ).fetchone()
    if not purchase:
        raise ValueError("Kirim topilmadi")
    if int(purchase["sync_version"]) != expected_version:
        raise ValueError("Kirim boshqa qurilmada o‘zgargan. Sahifani yangilang")
    if int(purchase["is_void"] or 0):
        raise ValueError("Kirim allaqachon bekor qilingan")

    payment_count = db.execute(
        """SELECT
            (SELECT COUNT(*) FROM purchase_payments WHERE purchase_id=?)
          + (SELECT COUNT(*) FROM supplier_payment_allocations WHERE purchase_id=?)""",
        (purchase["id"], purchase["id"]),
    ).fetchone()[0]
    if payment_count:
        raise ValueError(
            "To‘lov yozilgan kirimni o‘chirib bo‘lmaydi. Avval to‘lovni tuzatish kerak"
        )

    rows = db.execute(
        "SELECT * FROM purchase_items WHERE purchase_id=? AND tenant_id=? ORDER BY id",
        (purchase["id"], tenant_id),
    ).fetchall()
    original_payload = json.loads(purchase["payload_json"])
    wire_payload = dict(original_payload)
    wire_payload["voided"] = True

    with business_transaction(db):
        for row in rows:
            qty = float(row["qty"])
            cursor = db.execute(
                """UPDATE products SET stock_qty=COALESCE(stock_qty,0)-?
                WHERE id=? AND COALESCE(stock_qty,0)+1e-9>=?""",
                (qty, row["product_id"], qty),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "Bu kirimdagi tovar ishlatilgan. Kirimni o‘chirish uchun omborda qoldiq yetarli emas"
                )
            db.execute("DELETE FROM purchase_items WHERE id=?", (row["id"],))
            db.execute(
                "DELETE FROM inventory_moves WHERE id=?",
                (row["inventory_move_id"],),
            )

        db.execute(
            """UPDATE purchases
            SET is_void=1,voided_at=CURRENT_TIMESTAMP,sync_version=?
            WHERE id=?""",
            (target_version, purchase["id"]),
        )
        if replicate:
            _queue(
                db,
                "purchase",
                entity_uuid,
                wire_payload,
                operation="update",
                sync_version=target_version,
            )
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
            """SELECT p.*,
            COALESCE((SELECT SUM(amount_uzs) FROM purchase_payments pp WHERE pp.purchase_id=p.id),0)
          + COALESCE((SELECT SUM(amount_uzs) FROM supplier_payment_allocations a WHERE a.purchase_id=p.id),0) paid
            FROM purchases p
            WHERE entity_uuid=? AND tenant_id=? AND COALESCE(p.is_void,0)=0""",
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


def pay_supplier(db, *, tenant_id, entity_uuid, payload, replicate=True):
    """Create one supplier payment and allocate it to oldest debt first."""
    entity_uuid = uid(entity_uuid)
    if not isinstance(payload, dict):
        raise ValueError("To‘lov ma’lumoti noto‘g‘ri")

    base = dict(
        supplier_uuid=uid(payload.get("supplier_uuid")),
        payment_date=iso_date(payload.get("payment_date")),
        amount_uzs=number(payload.get("amount_uzs"), "To‘lov"),
        method=text_value(payload.get("method", ""), "To‘lov turi", 10, True),
        note=text_value(payload.get("note", ""), "Izoh"),
    )
    if base["method"] not in ("cash", "click"):
        raise ValueError("Naqd yoki Click hisobini tanlang")

    requested_allocations = payload.get("allocations")
    with business_transaction(db):
        existing = db.execute(
            "SELECT * FROM supplier_payments WHERE entity_uuid=?",
            (entity_uuid,),
        ).fetchone()
        if existing:
            if existing["tenant_id"] != tenant_id:
                raise ValueError("Bu identifikator boshqa firmaga tegishli")
            stored = json.loads(existing["payload_json"])
            if any(stored.get(key) != value for key, value in base.items()):
                raise ValueError("Bu identifikator boshqa to‘lovga tegishli")
            if requested_allocations is not None and stored.get("allocations") != requested_allocations:
                raise ValueError("To‘lov taqsimoti mos kelmadi")
            return existing["id"]

        supplier = db.execute(
            "SELECT id,name FROM suppliers WHERE entity_uuid=? AND tenant_id=?",
            (base["supplier_uuid"], tenant_id),
        ).fetchone()
        if not supplier:
            raise ValueError("Yetkazib beruvchi topilmadi")

        rows = db.execute(
            """SELECT p.id,p.entity_uuid,p.purchase_date,p.total_uzs,
            COALESCE((SELECT SUM(amount_uzs) FROM purchase_payments pp WHERE pp.purchase_id=p.id),0)
          + COALESCE((SELECT SUM(amount_uzs) FROM supplier_payment_allocations a WHERE a.purchase_id=p.id),0) paid
            FROM purchases p
            WHERE p.supplier_id=? AND p.tenant_id=? AND COALESCE(p.is_void,0)=0
              AND p.purchase_date<=?
            ORDER BY p.purchase_date,p.id""",
            (supplier["id"], tenant_id, base["payment_date"]),
        ).fetchall()
        by_uuid = {str(row["entity_uuid"]): row for row in rows}

        allocations = []
        if requested_allocations is not None:
            if not isinstance(requested_allocations, list) or not requested_allocations:
                raise ValueError("To‘lov taqsimoti noto‘g‘ri")
            seen = set()
            allocated_total = Decimal("0")
            for item in requested_allocations:
                if not isinstance(item, dict):
                    raise ValueError("To‘lov taqsimoti noto‘g‘ri")
                purchase_uuid = uid(item.get("purchase_uuid"))
                if purchase_uuid in seen:
                    raise ValueError("Bir kirim ikki marta taqsimlangan")
                seen.add(purchase_uuid)
                row = by_uuid.get(purchase_uuid)
                if not row:
                    raise ValueError("Taqsimlangan kirim topilmadi")
                amount = number(item.get("amount_uzs"), "Taqsimlangan to‘lov")
                remaining = round(float(row["total_uzs"]) - float(row["paid"]), 2)
                if amount > remaining + 0.005:
                    raise ValueError("Taqsimlangan to‘lov kirim qarzidan oshdi")
                allocations.append(
                    {"purchase_uuid": purchase_uuid, "amount_uzs": amount}
                )
                allocated_total += Decimal(str(amount))
            if abs(allocated_total - Decimal(str(base["amount_uzs"]))) > Decimal("0.005"):
                raise ValueError("To‘lov taqsimoti jami summaga mos emas")
        else:
            remaining_payment = Decimal(str(base["amount_uzs"]))
            for row in rows:
                debt = Decimal(str(round(float(row["total_uzs"]) - float(row["paid"]), 2)))
                if debt <= Decimal("0"):
                    continue
                amount = min(debt, remaining_payment)
                if amount > 0:
                    allocations.append(
                        {
                            "purchase_uuid": str(row["entity_uuid"]),
                            "amount_uzs": float(amount),
                        }
                    )
                    remaining_payment -= amount
                if remaining_payment <= Decimal("0.005"):
                    remaining_payment = Decimal("0")
                    break
            if remaining_payment > Decimal("0.005"):
                raise ValueError("To‘lov sanasigacha bo‘lgan qarzdan oshmasin")

        final_payload = dict(base)
        final_payload["allocations"] = allocations

        table = "cash_moves" if base["method"] == "cash" else "click_moves"
        movement = db.execute(
            f"INSERT INTO {table}(move_date,direction,amount_uzs,note,entity_uuid,sync_version) VALUES(?,'OUT',?,?,?,1)",
            (
                base["payment_date"],
                base["amount_uzs"],
                f"Yetkazuvchi {supplier['name']} · {base['note']}".rstrip(" ·"),
                entity_uuid,
            ),
        )
        cash_id = movement.lastrowid if base["method"] == "cash" else None
        click_id = movement.lastrowid if base["method"] == "click" else None
        cursor = db.execute(
            """INSERT INTO supplier_payments(
                tenant_id,supplier_id,payment_date,amount_uzs,method,note,
                cash_move_id,click_move_id,entity_uuid,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                tenant_id,
                supplier["id"],
                base["payment_date"],
                base["amount_uzs"],
                base["method"],
                base["note"],
                cash_id,
                click_id,
                entity_uuid,
                encoded(final_payload),
            ),
        )
        payment_id = cursor.lastrowid
        for item in allocations:
            purchase = by_uuid[item["purchase_uuid"]]
            db.execute(
                """INSERT INTO supplier_payment_allocations(
                    tenant_id,supplier_payment_id,purchase_id,amount_uzs
                ) VALUES(?,?,?,?)""",
                (
                    tenant_id,
                    payment_id,
                    purchase["id"],
                    item["amount_uzs"],
                ),
            )
        if replicate:
            _queue(db, "supplier_payment", entity_uuid, final_payload)
        return payment_id
