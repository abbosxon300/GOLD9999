"""Purchase invariants and HTTP/security checks against disposable SQLite databases."""

import copy
import json
import re
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from services.migrations import run_migrations
from services.business_writes.purchases import (
    create_supplier,
    prepare_purchase,
    save_purchase,
    pay_purchase,
    pay_supplier,
    update_purchase,
    void_purchase,
)
from services.business_writes.transaction import business_transaction


def database():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    run_migrations(db)
    db.execute("INSERT INTO tenants(name,slug) VALUES('Other','other')")
    for tenant in (1, 2):
        db.execute(
            "INSERT INTO categories(id,name,tenant_id,entity_uuid,sync_version) VALUES(?,?,?,?,1)",
            (tenant, f"Category {tenant}", tenant, str(uuid4())),
        )
        for n in (1, 2):
            product_id = tenant * 10 + n
            db.execute(
                "INSERT INTO products(id,name,category_id,tenant_id,entity_uuid,sync_version) VALUES(?,?,?,?,?,1)",
                (product_id, f"Product {product_id}", tenant, tenant, str(uuid4())),
            )
    db.commit()
    return db


@pytest.fixture
def db():
    db = database()
    yield db
    db.close()


def purchase(db, *, tenant=1, items=None):
    supplier = create_supplier(db, tenant_id=tenant, name="Test supplier")
    key = str(uuid4())
    payload = prepare_purchase(
        db,
        tenant_id=tenant,
        supplier_id=supplier,
        purchase_date="2026-09-26",
        reference="R-12",
        note="Test",
        items=items
        or [
            {"product_id": tenant * 10 + 1, "qty": "2", "unit_cost_uzs": "45000"},
            {"product_id": tenant * 10 + 2, "qty": "3", "unit_cost_uzs": "20000"},
        ],
        entity_uuid=key,
    )
    doc = save_purchase(db, tenant_id=tenant, entity_uuid=key, payload=payload)
    return doc, key, payload


def payment(key, amount=50000, method="cash"):
    return dict(
        purchase_uuid=key,
        payment_date="2026-09-26",
        amount_uzs=amount,
        method=method,
        note="Test",
    )


def supplier_payment_payload(db, supplier_id, amount, method="cash", payment_date="2026-09-27"):
    supplier_uuid = db.execute(
        "SELECT entity_uuid FROM suppliers WHERE id=?",
        (supplier_id,),
    ).fetchone()[0]
    return dict(
        supplier_uuid=supplier_uuid,
        payment_date=payment_date,
        amount_uzs=amount,
        method=method,
        note="Supplier test",
    )


def test_purchase_stock_average_and_retry(db):
    doc, key, payload = purchase(db)
    assert (
        db.execute("SELECT total_uzs FROM purchases WHERE id=?", (doc,)).fetchone()[0]
        == 150000
    )
    assert db.execute("SELECT stock_qty FROM products WHERE id=11").fetchone()[0] == 2
    assert save_purchase(db, tenant_id=1, entity_uuid=key, payload=payload) == doc
    assert db.execute("SELECT COUNT(*) FROM inventory_moves").fetchone()[0] == 2
    from services.sales_helpers import product_avg_cost

    assert product_avg_cost(lambda: db, 11) == 45000
    changed = copy.deepcopy(payload)
    changed["items"][0]["qty"] = 10
    with pytest.raises(ValueError):
        save_purchase(db, tenant_id=1, entity_uuid=key, payload=changed)
    assert db.execute("SELECT stock_qty FROM products WHERE id=11").fetchone()[0] == 2


def test_supplier_payment_fifo_one_cash_move_and_retry(db):
    supplier_id = create_supplier(db, tenant_id=1, name="FIFO supplier")

    first_uuid = str(uuid4())
    first_payload = prepare_purchase(
        db,
        tenant_id=1,
        supplier_id=supplier_id,
        purchase_date="2026-09-25",
        reference="F-1",
        note="",
        items=[{"product_id": 11, "qty": 2, "unit_cost_uzs": 50000}],
        entity_uuid=first_uuid,
    )
    first_id = save_purchase(
        db, tenant_id=1, entity_uuid=first_uuid, payload=first_payload
    )

    second_uuid = str(uuid4())
    second_payload = prepare_purchase(
        db,
        tenant_id=1,
        supplier_id=supplier_id,
        purchase_date="2026-09-26",
        reference="F-2",
        note="",
        items=[{"product_id": 12, "qty": 2, "unit_cost_uzs": 100000}],
        entity_uuid=second_uuid,
    )
    second_id = save_purchase(
        db, tenant_id=1, entity_uuid=second_uuid, payload=second_payload
    )

    token = str(uuid4())
    payload = supplier_payment_payload(db, supplier_id, 150000)
    payment_id = pay_supplier(
        db, tenant_id=1, entity_uuid=token, payload=payload
    )
    assert pay_supplier(
        db, tenant_id=1, entity_uuid=token, payload=payload
    ) == payment_id

    assert db.execute(
        "SELECT COUNT(*) FROM supplier_payments"
    ).fetchone()[0] == 1
    assert db.execute(
        "SELECT COUNT(*) FROM cash_moves WHERE direction='OUT'"
    ).fetchone()[0] == 1
    assert db.execute(
        "SELECT SUM(amount_uzs) FROM cash_moves WHERE direction='OUT'"
    ).fetchone()[0] == 150000

    allocations = db.execute(
        """SELECT purchase_id,amount_uzs
        FROM supplier_payment_allocations
        ORDER BY id"""
    ).fetchall()
    assert [(r["purchase_id"], r["amount_uzs"]) for r in allocations] == [
        (first_id, 100000),
        (second_id, 50000),
    ]

    with pytest.raises(ValueError, match="qarzdan oshmasin"):
        pay_supplier(
            db,
            tenant_id=1,
            entity_uuid=str(uuid4()),
            payload=supplier_payment_payload(db, supplier_id, 151000),
        )

    with pytest.raises(ValueError, match="qarzdan oshmasin"):
        pay_purchase(
            db,
            tenant_id=1,
            entity_uuid=str(uuid4()),
            payload=payment(second_uuid, 151000),
        )

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE cash_moves SET amount_uzs=1 "
            "WHERE id=(SELECT cash_move_id FROM supplier_payments WHERE id=?)",
            (payment_id,),
        )
    db.rollback()


def test_supplier_payment_blocks_underpaid_edit_and_void(db):
    doc, key, payload = purchase(db)
    supplier_id = db.execute(
        "SELECT supplier_id FROM purchases WHERE id=?",
        (doc,),
    ).fetchone()[0]
    pay_supplier(
        db,
        tenant_id=1,
        entity_uuid=str(uuid4()),
        payload=supplier_payment_payload(db, supplier_id, 100000),
    )

    too_small = copy.deepcopy(payload)
    too_small["items"] = [
        dict(too_small["items"][0], qty=1, unit_cost_uzs=10000)
    ]
    with pytest.raises(ValueError, match="to‘langan"):
        update_purchase(
            db,
            tenant_id=1,
            entity_uuid=key,
            payload=too_small,
            expected_version=1,
        )

    with pytest.raises(ValueError, match="To‘lov yozilgan"):
        void_purchase(
            db,
            tenant_id=1,
            entity_uuid=key,
            expected_version=1,
        )


def test_payment_retry_overpay_and_cash_guard(db):
    doc, key, _ = purchase(db)
    token = str(uuid4())
    result = pay_purchase(db, tenant_id=1, entity_uuid=token, payload=payment(key))
    assert (
        pay_purchase(db, tenant_id=1, entity_uuid=token, payload=payment(key)) == result
    )
    pay_purchase(
        db, tenant_id=1, entity_uuid=str(uuid4()), payload=payment(key, 100000, "click")
    )
    assert (
        db.execute(
            "SELECT SUM(amount_uzs) FROM cash_moves WHERE direction='OUT'"
        ).fetchone()[0]
        == 50000
    )
    assert db.execute("SELECT SUM(amount_uzs) FROM click_moves").fetchone()[0] == 100000
    with pytest.raises(ValueError):
        pay_purchase(db, tenant_id=1, entity_uuid=str(uuid4()), payload=payment(key, 1))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE cash_moves SET amount_uzs=1")
    db.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM cash_moves")
    db.rollback()


def test_rollback_all_rows_and_initial_payment(db):
    before = db.execute("SELECT COUNT(*) FROM inventory_moves").fetchone()[0]
    with pytest.raises(ValueError):
        with business_transaction(db):
            doc, key, payload = purchase(db)
            pay_purchase(
                db, tenant_id=1, entity_uuid=str(uuid4()), payload=payment(key, 999999)
            )
    assert db.execute("SELECT COUNT(*) FROM purchases").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM inventory_moves").fetchone()[0] == before
    assert db.execute("SELECT SUM(stock_qty) FROM products").fetchone()[0] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("qty", "NaN"),
        ("qty", "inf"),
        ("qty", -1),
        ("qty", 0),
        ("unit_cost_uzs", "-5"),
        ("unit_cost_uzs", "Infinity"),
        ("unit_cost_uzs", 0),
    ],
)
def test_bad_numbers(db, field, value):
    item = {"product_id": 11, "qty": 1, "unit_cost_uzs": 100}
    item[field] = value
    with pytest.raises(ValueError):
        purchase(db, items=[item])
    assert db.execute("SELECT COUNT(*) FROM inventory_moves").fetchone()[0] == 0


def test_tenant_and_duplicate_product_checks(db):
    with pytest.raises(ValueError):
        purchase(db, items=[{"product_id": 21, "qty": 1, "unit_cost_uzs": 10}])
    with pytest.raises(ValueError):
        purchase(db, items=[{"product_id": 11, "qty": 1, "unit_cost_uzs": 10}] * 2)
    doc, key, payload = purchase(db)
    with pytest.raises(ValueError):
        save_purchase(db, tenant_id=2, entity_uuid=str(uuid4()), payload=payload)
    with pytest.raises(ValueError):
        pay_purchase(db, tenant_id=2, entity_uuid=str(uuid4()), payload=payment(key))


def test_migration_preserves_existing_data_and_reruns(db):
    from services.business_writes.inventory import receive_stock

    with business_transaction(db):
        receive_stock(
            db, move_date="2026-09-25", product_id=11, qty=7, unit_cost_uzs=11
        )
    assert run_migrations(db) == []
    assert db.execute("SELECT stock_qty FROM products WHERE id=11").fetchone()[0] == 7
    assert db.execute("SELECT COUNT(*) FROM purchases").fetchone()[0] == 0



def test_sync_two_databases_no_double_stock(db):
    import services.offline.master_data_adapters  # noqa: F401
    import services.offline.purchase_adapter  # noqa: F401
    from services.offline.pull_service import build_pull_response
    from services.offline.models import RemoteChange
    from services.offline.remote_applier import apply_remote_change

    remote = sqlite3.connect(":memory:")
    remote.row_factory = sqlite3.Row
    db.backup(remote)
    doc, key, payload = purchase(db)
    pay_purchase(db, tenant_id=1, entity_uuid=str(uuid4()), payload=payment(key))
    changes = build_pull_response(
        db,
        cursor=None,
        limit=500,
        device_uuid=str(uuid4()),
        include_purchases=True,
        tenant_id=1,
    ).changes
    business = [
        c
        for c in changes
        if c["entity_type"] in ("supplier", "purchase", "purchase_payment")
    ]
    for iteration in range(2):
        for change in business:
            with business_transaction(remote):
                apply_remote_change(
                    remote,
                    RemoteChange(
                        change["entity_type"],
                        change["entity_uuid"],
                        change["operation"],
                        change["payload"],
                        change["version"],
                        str(uuid4()),
                        datetime.now(timezone.utc),
                    ),
                    tenant_id=1,
                )
    assert (
        remote.execute("SELECT stock_qty FROM products WHERE id=11").fetchone()[0] == 2
    )
    assert remote.execute("SELECT COUNT(*) FROM purchases").fetchone()[0] == 1
    assert (
        remote.execute("SELECT SUM(amount_uzs) FROM cash_moves").fetchone()[0] == 50000
    )
    legacy = build_pull_response(
        db, cursor=None, limit=500, device_uuid=str(uuid4()), tenant_id=1
    ).changes
    assert not any(
        c["entity_type"] in ("supplier", "purchase", "purchase_payment", "supplier_payment") for c in legacy
    )
    assert not any(c["entity_type"] == "inventory_move" for c in legacy)
    remote.close()

def test_sync_supplier_payment_keeps_exact_fifo_allocations(db):
    import services.offline.purchase_adapter  # noqa: F401
    from services.offline.pull_service import build_pull_response
    from services.offline.models import RemoteChange
    from services.offline.remote_applier import apply_remote_change

    remote = sqlite3.connect(":memory:")
    remote.row_factory = sqlite3.Row
    db.backup(remote)

    supplier_id = create_supplier(db, tenant_id=1, name="Sync FIFO")
    purchase_uuids = []
    for product_id, day, qty, cost in (
        (11, "2026-09-25", 2, 50000),
        (12, "2026-09-26", 2, 100000),
    ):
        key = str(uuid4())
        payload = prepare_purchase(
            db,
            tenant_id=1,
            supplier_id=supplier_id,
            purchase_date=day,
            reference=day,
            note="",
            items=[{"product_id": product_id, "qty": qty, "unit_cost_uzs": cost}],
            entity_uuid=key,
        )
        save_purchase(db, tenant_id=1, entity_uuid=key, payload=payload)
        purchase_uuids.append(key)

    pay_supplier(
        db,
        tenant_id=1,
        entity_uuid=str(uuid4()),
        payload=supplier_payment_payload(db, supplier_id, 150000),
    )

    changes = build_pull_response(
        db,
        cursor=None,
        limit=500,
        device_uuid=str(uuid4()),
        include_purchases=True,
        tenant_id=1,
    ).changes
    business = [
        c for c in changes
        if c["entity_type"] in (
            "supplier", "purchase", "purchase_payment", "supplier_payment"
        )
    ]
    assert any(c["entity_type"] == "supplier_payment" for c in business)

    for change in business:
        with business_transaction(remote):
            apply_remote_change(
                remote,
                RemoteChange(
                    change["entity_type"],
                    change["entity_uuid"],
                    change["operation"],
                    change["payload"],
                    change["version"],
                    str(uuid4()),
                    datetime.now(timezone.utc),
                ),
                tenant_id=1,
            )

    source_alloc = [
        (r["purchase_id"], r["amount_uzs"])
        for r in db.execute(
            "SELECT purchase_id,amount_uzs FROM supplier_payment_allocations ORDER BY id"
        )
    ]
    remote_alloc = [
        (r["purchase_id"], r["amount_uzs"])
        for r in remote.execute(
            "SELECT purchase_id,amount_uzs FROM supplier_payment_allocations ORDER BY id"
        )
    ]
    assert remote_alloc == source_alloc
    assert remote.execute(
        "SELECT COUNT(*) FROM supplier_payments"
    ).fetchone()[0] == 1
    assert remote.execute(
        "SELECT SUM(amount_uzs) FROM cash_moves WHERE direction='OUT'"
    ).fetchone()[0] == 150000
    remote.close()


def test_pull_isolates_tenants(db):
    from services.offline.pull_service import build_pull_response

    purchase(db)
    purchase(db, tenant=2)
    a = build_pull_response(
        db,
        cursor=None,
        limit=500,
        device_uuid=str(uuid4()),
        include_purchases=True,
        tenant_id=1,
    )
    b = build_pull_response(
        db,
        cursor=None,
        limit=500,
        device_uuid=str(uuid4()),
        include_purchases=True,
        tenant_id=2,
    )
    assert {c["entity_uuid"] for c in a.changes}.isdisjoint(
        {c["entity_uuid"] for c in b.changes}
    )


@pytest.fixture
def web(tmp_path, monkeypatch, db):
    path = tmp_path / "web.db"
    target = sqlite3.connect(path)
    db.backup(target)
    target.close()
    monkeypatch.setenv("GOLD9999_DB_PATH", str(path))
    import app as app_module
    from services.db import configure_db

    configure_db(str(path))
    app = app_module.app
    app.config.update(TESTING=True, SECRET_KEY="isolated-test-key")
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT OR IGNORE INTO users(username,password_hash,role,tenant_id) VALUES('admin','test-only','admin',1)"
    )
    conn.execute(
        "UPDATE users SET tenant_id=1,role='admin',is_active=1 WHERE username='admin'"
    )
    conn.commit()
    user_id = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
    conn.close()
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(user_id=user_id, role="admin", full_name="Test Admin")
    return app, client, path


def token_from(client):
    response = client.get("/kpi/new")
    assert response.status_code == 200, response.text
    return re.search(r'name="csrf_token" value="([^"]+)"', response.text)[1]


def test_http_workflow_and_xss(web):
    app, client, path = web
    csrf = token_from(client)
    response = client.post(
        "/kpi/suppliers",
        data=dict(
            csrf_token=csrf,
            entity_uuid=str(uuid4()),
            name="<script>alert(1)</script>",
            phone="+998",
        ),
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 201
    supplier = response.json["id"]
    form = dict(
        csrf_token=csrf,
        entity_uuid=str(uuid4()),
        supplier_id=supplier,
        purchase_date="2026-09-26",
        reference="Ref",
        note="<img src=x onerror=alert(1)>",
        items=json.dumps([dict(product_id=11, qty=2, unit_cost_uzs=45000)]),
        paid="20000",
        method="cash",
    )
    result = client.post("/kpi/new", data=form)
    assert result.status_code == 302, result.text
    detail = client.get(result.location)
    assert detail.status_code == 200
    assert (
        "&lt;script&gt;" in detail.text
        and "<script>alert(1)</script>" not in detail.text
    )
    assert client.post("/kpi/new", data=form).location == result.location
    for url in (
        "/kpi",
        "/kpi?status=debt",
        "/kpi?status=paid",
        "/kpi?q=Ref",
        "/kpi/stock",
        "/kpi/legacy",
        "/kpi/suppliers",
    ):
        assert client.get(url).status_code == 200, url
    assert client.get("/kpi/1/kirim").status_code == 303
    assert client.get("/kpi/1").status_code == 302
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM purchases").fetchone()[0] == 1
    assert conn.execute("SELECT stock_qty FROM products WHERE id=11").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM purchase_payments").fetchone()[0] == 0
    conn.close()



def test_supplier_cabinet_fifo_payment_without_document_selection(web):
    app, client, path = web
    csrf = token_from(client)

    supplier_response = client.post(
        "/kpi/suppliers",
        data={
            "csrf_token": csrf,
            "entity_uuid": str(uuid4()),
            "name": "Donyor",
            "phone": "+998947289999",
        },
        headers={"Accept": "application/json"},
    )
    assert supplier_response.status_code == 201
    supplier_id = supplier_response.json["id"]

    purchase_response = client.post(
        "/kpi/new",
        data={
            "csrf_token": csrf,
            "entity_uuid": str(uuid4()),
            "supplier_id": supplier_id,
            "purchase_date": "2026-09-27",
            "reference": "SUP-1",
            "note": "",
            "items": json.dumps(
                [{"product_id": 11, "qty": 2, "unit_cost_uzs": 45000}]
            ),
        },
    )
    assert purchase_response.status_code == 302

    cabinet = client.get(f"/kpi/suppliers/{supplier_id}")
    assert cabinet.status_code == 200
    assert "+ Yangi kirim" not in cabinet.text
    assert "Qaysi kirim?" not in cabinet.text
    assert 'name="purchase_id"' not in cabinet.text
    assert 'id="supplier-pay-open"' in cabinet.text
    assert 'id="supplier-pay-dialog"' in cabinet.text
    assert 'data-supplier-tab="turnover"' in cabinet.text
    assert 'data-supplier-tab="purchases"' in cabinet.text
    assert 'data-supplier-tab="payments"' in cabinet.text
    assert "Aylanma" in cabinet.text
    assert "Balans" in cabinet.text
    assert "SUP-1" in cabinet.text
    assert "20260927_supplier_fifo_v1" in cabinet.text

    payment_uuid = re.search(
        r'name="entity_uuid" value="([^"]+)"',
        cabinet.text,
    )[1]
    paid = client.post(
        f"/kpi/suppliers/{supplier_id}/pay",
        data={
            "csrf_token": csrf,
            "entity_uuid": payment_uuid,
            "payment_date": "2026-09-27",
            "amount_uzs": "50000",
            "method": "cash",
            "note": "Umumiy to‘lov",
        },
    )
    assert paid.status_code == 302

    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    assert db.execute(
        "SELECT COUNT(*) FROM supplier_payments"
    ).fetchone()[0] == 1
    assert db.execute(
        "SELECT COUNT(*) FROM supplier_payment_allocations"
    ).fetchone()[0] == 1
    assert db.execute(
        "SELECT amount_uzs FROM supplier_payments"
    ).fetchone()[0] == 50000
    db.close()

    after = client.get(f"/kpi/suppliers/{supplier_id}")
    assert "Umumiy to‘lov" in after.text
    assert "40 000" in after.text

    script = client.get("/static/js/supplier_detail.js")
    assert script.status_code == 200
    body = script.get_data(as_text=True)
    assert "querySelectorAll('[data-supplier-tab]')" in body
    assert "supplier-pay-dialog" in body
    assert "supplier-pay-purchase" not in body
    assert "To‘lov summasini kiriting." in body
    assert "To‘lov yetkazib beruvchi qarzidan oshmasligi kerak." in body

def test_http_csrf_auth_and_cross_tenant(web):
    app, client, path = web
    csrf = token_from(client)
    assert client.post("/kpi/suppliers", data=dict(name="No CSRF")).status_code == 400
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    doc, key, _ = purchase(conn, tenant=2)
    conn.close()
    assert client.get(f"/kpi/documents/{doc}").status_code == 404
    assert (
        client.post(f"/kpi/documents/{doc}/pay", data=dict(csrf_token=csrf)).status_code
        == 404
    )
    with client.session_transaction() as s:
        s["role"] = "agent"
    assert client.get("/kpi").status_code == 302
    with client.session_transaction() as s:
        s.clear()
    assert client.get("/kpi/new").status_code == 302


def test_new_pull_cursor_does_not_skip_new_dependency_groups(db):
    from services.offline.pull_service import build_pull_response

    device = str(uuid4())
    purchase(db)
    first = build_pull_response(
        db,
        cursor=None,
        limit=500,
        device_uuid=device,
        include_purchases=True,
        tenant_id=1,
    )
    assert not first.has_more
    empty = build_pull_response(
        db,
        cursor=first.next_cursor,
        limit=500,
        device_uuid=device,
        include_purchases=True,
        tenant_id=1,
    )
    assert not empty.changes
    _, new_uuid, _ = purchase(db)
    replay = build_pull_response(
        db,
        cursor=first.next_cursor,
        limit=500,
        device_uuid=device,
        include_purchases=True,
        tenant_id=1,
    )
    assert any(c["entity_uuid"] == new_uuid for c in replay.changes)
    cursor = None
    seen = []
    for _ in range(100):
        batch = build_pull_response(
            db,
            cursor=cursor,
            limit=2,
            device_uuid=device,
            include_purchases=True,
            tenant_id=1,
        )
        seen.extend(c["entity_uuid"] for c in batch.changes)
        cursor = batch.next_cursor
        if not batch.has_more:
            break
    assert len(seen) == len(set(seen)) == len(replay.changes)



def test_purchase_aggregate_materializes_owned_stock_without_inventory_replication(db):
    supplier = create_supplier(db, tenant_id=1, name="Aggregate supplier")
    key = str(uuid4())
    payload = prepare_purchase(
        db,
        tenant_id=1,
        supplier_id=supplier,
        purchase_date="2026-09-26",
        reference="AGG-1",
        note="",
        items=[
            {"product_id": 11, "qty": 2, "unit_cost_uzs": 45000},
            {"product_id": 12, "qty": 3, "unit_cost_uzs": 20000},
        ],
        entity_uuid=key,
    )
    doc = save_purchase(
        db,
        tenant_id=1,
        entity_uuid=key,
        payload=payload,
        replicate=False,
    )
    assert doc > 0
    assert db.execute("SELECT stock_qty FROM products WHERE id=11").fetchone()[0] == 2
    assert db.execute("SELECT stock_qty FROM products WHERE id=12").fetchone()[0] == 3
    move_uuids = [
        row[0]
        for row in db.execute(
            "SELECT entity_uuid FROM inventory_moves ORDER BY id"
        ).fetchall()
    ]
    assert move_uuids == [item["move_uuid"] for item in payload["items"]]

def test_fractional_totals_equal_sum_of_displayed_rows(db):
    doc, key, _ = purchase(
        db,
        items=[
            {"product_id": 11, "qty": ".333", "unit_cost_uzs": "1.01"},
            {"product_id": 12, "qty": ".333", "unit_cost_uzs": "1.01"},
        ],
    )
    row = db.execute("SELECT total_uzs FROM purchases WHERE id=?", (doc,)).fetchone()
    assert row[0] == 0.68
    pay_purchase(db, tenant_id=1, entity_uuid=str(uuid4()), payload=payment(key, 0.68))
    with pytest.raises(ValueError):
        pay_purchase(
            db, tenant_id=1, entity_uuid=str(uuid4()), payload=payment(key, 0.01)
        )



def test_desktop_queue_uses_purchase_aggregate_with_stable_movement_ids(db, monkeypatch):
    from services.offline.schema import ensure_offline_sync_schema

    ensure_offline_sync_schema(db)
    db.commit()
    monkeypatch.setenv("GOLD9999_DATA_DIR", "/unused-test-desktop")
    monkeypatch.setenv("OFFLINE_DEVICE_UUID", str(uuid4()))
    doc, key, payload = purchase(db)
    rows = db.execute(
        "SELECT entity_type,entity_uuid FROM sync_queue ORDER BY id"
    ).fetchall()
    assert [r["entity_type"] for r in rows] == ["supplier", "purchase"]
    assert rows[-1]["entity_uuid"] == key
    movement_ids = [
        row["entity_uuid"]
        for row in db.execute(
            "SELECT entity_uuid FROM inventory_moves ORDER BY id"
        ).fetchall()
    ]
    assert movement_ids == [item["move_uuid"] for item in payload["items"]]

def test_release_backup_and_upgrade_from_v12(tmp_path):
    from services.migrations import discover_migrations, ensure_schema_migrations
    from tools.release_purchases import release

    path = tmp_path / "production-like.db"
    db = sqlite3.connect(path)
    ensure_schema_migrations(db)
    for migration in discover_migrations():
        if migration.version >= 13:
            break
        migration.module.upgrade(db)
        db.execute(
            "INSERT INTO schema_migrations VALUES(?,?,?,?)",
            (migration.version, migration.name, migration.checksum, "2026-09-26"),
        )
        db.commit()
    db.execute("INSERT INTO categories(id,name,tenant_id) VALUES(1,'Old category',1)")
    db.execute(
        "INSERT INTO products(id,name,category_id,stock_qty,tenant_id) VALUES(1,'Old product',1,42,1)"
    )
    db.commit()
    db.close()
    backup = release(path, tmp_path / "backups")
    old = sqlite3.connect(backup)
    assert (
        old.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='purchases'"
        ).fetchone()[0]
        == 0
    )
    assert old.execute("SELECT stock_qty FROM products").fetchone()[0] == 42
    old.close()
    updated = sqlite3.connect(path)
    assert updated.execute("SELECT stock_qty FROM products").fetchone()[0] == 42
    assert updated.execute("SELECT COUNT(*) FROM purchases").fetchone()[0] == 0
    assert updated.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='supplier_payments'"
    ).fetchone()[0] == 1
    assert updated.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='supplier_payment_allocations'"
    ).fetchone()[0] == 1
    assert updated.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version=15"
    ).fetchone()[0] == 1
    updated.close()


def test_cash_ledger_hides_other_firms_supplier_payments(web):
    app, client, path = web
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    own_doc, _, _ = purchase(db, tenant=1)
    other_doc, _, _ = purchase(db, tenant=2)
    own_supplier = db.execute(
        "SELECT supplier_id FROM purchases WHERE id=?", (own_doc,)
    ).fetchone()[0]
    other_supplier = db.execute(
        "SELECT supplier_id FROM purchases WHERE id=?", (other_doc,)
    ).fetchone()[0]
    pay_supplier(
        db,
        tenant_id=1,
        entity_uuid=str(uuid4()),
        payload=supplier_payment_payload(db, own_supplier, 12500),
    )
    pay_supplier(
        db,
        tenant_id=2,
        entity_uuid=str(uuid4()),
        payload=supplier_payment_payload(db, other_supplier, 77777),
    )
    db.close()
    response = client.get("/kassa?from=2026-09-01&to=2026-09-30")
    assert response.status_code == 200
    assert "12 500" in response.text
    assert "77 777" not in response.text


def test_purchase_edit_recalculates_stock_and_version(db):
    doc, key, payload = purchase(db)
    changed = copy.deepcopy(payload)
    changed["items"][0]["qty"] = 5
    changed["items"][0]["unit_cost_uzs"] = 47000
    update_purchase(
        db,
        tenant_id=1,
        entity_uuid=key,
        payload=changed,
        expected_version=1,
    )
    row = db.execute(
        "SELECT total_uzs,sync_version FROM purchases WHERE id=?", (doc,)
    ).fetchone()
    assert row["sync_version"] == 2
    assert row["total_uzs"] == 295000
    assert db.execute("SELECT stock_qty FROM products WHERE id=11").fetchone()[0] == 5
    assert db.execute("SELECT stock_qty FROM products WHERE id=12").fetchone()[0] == 3
    with pytest.raises(ValueError, match="boshqa qurilmada"):
        update_purchase(
            db,
            tenant_id=1,
            entity_uuid=key,
            payload=changed,
            expected_version=1,
        )



def test_purchase_edit_never_drops_below_paid_or_negative_stock(db):
    doc, key, payload = purchase(db)
    pay_purchase(
        db,
        tenant_id=1,
        entity_uuid=str(uuid4()),
        payload=payment(key, 100000),
    )
    too_small = copy.deepcopy(payload)
    too_small["items"] = [
        dict(too_small["items"][0], qty=1, unit_cost_uzs=10000)
    ]
    with pytest.raises(ValueError, match="to‘langan"):
        update_purchase(
            db,
            tenant_id=1,
            entity_uuid=key,
            payload=too_small,
            expected_version=1,
        )

    db.execute("UPDATE products SET stock_qty=0 WHERE id=11")
    db.commit()
    reduced = copy.deepcopy(payload)
    reduced["items"][0]["qty"] = 1
    with pytest.raises(ValueError, match="qoldiq"):
        update_purchase(
            db,
            tenant_id=1,
            entity_uuid=key,
            payload=reduced,
            expected_version=1,
        )

def test_purchase_void_reverses_stock_and_keeps_tombstone(db):
    doc, key, _ = purchase(db)
    void_purchase(db, tenant_id=1, entity_uuid=key, expected_version=1)
    row = db.execute(
        "SELECT is_void,sync_version FROM purchases WHERE id=?", (doc,)
    ).fetchone()
    assert row["is_void"] == 1
    assert row["sync_version"] == 2
    assert db.execute("SELECT stock_qty FROM products WHERE id=11").fetchone()[0] == 0
    assert db.execute("SELECT stock_qty FROM products WHERE id=12").fetchone()[0] == 0
    assert db.execute(
        "SELECT COUNT(*) FROM purchase_items WHERE purchase_id=?", (doc,)
    ).fetchone()[0] == 0


def test_purchase_void_blocks_payments(db):
    doc, key, _ = purchase(db)
    pay_purchase(
        db,
        tenant_id=1,
        entity_uuid=str(uuid4()),
        payload=payment(key, 50000),
    )
    with pytest.raises(ValueError, match="To‘lov"):
        void_purchase(db, tenant_id=1, entity_uuid=key, expected_version=1)
    assert db.execute(
        "SELECT is_void FROM purchases WHERE id=?", (doc,)
    ).fetchone()[0] == 0


def test_http_purchase_edit_and_void(web):
    app, client, path = web
    csrf = token_from(client)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    supplier = create_supplier(conn, tenant_id=1, name="HTTP supplier")
    key = str(uuid4())
    payload = prepare_purchase(
        conn,
        tenant_id=1,
        supplier_id=supplier,
        purchase_date="2026-09-26",
        reference="HTTP-1",
        note="",
        items=[{"product_id": 11, "qty": 2, "unit_cost_uzs": 10000}],
        entity_uuid=key,
    )
    doc = save_purchase(conn, tenant_id=1, entity_uuid=key, payload=payload)
    conn.close()

    page = client.get(f"/kpi/documents/{doc}/edit")
    assert page.status_code == 200
    assert "Kirimni tahrirlash" in page.text

    edit = client.post(
        f"/kpi/documents/{doc}/edit",
        data={
            "csrf_token": csrf,
            "expected_version": "1",
            "supplier_id": str(supplier),
            "purchase_date": "2026-09-26",
            "reference": "HTTP-2",
            "note": "edited",
            "items": json.dumps(
                [{"product_id": 11, "qty": 3, "unit_cost_uzs": 10000}]
            ),
        },
    )
    assert edit.status_code == 302
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT reference,sync_version FROM purchases WHERE id=?", (doc,)
    ).fetchone()
    assert row["reference"] == "HTTP-2"
    assert row["sync_version"] == 2
    conn.close()

    deleted = client.post(
        f"/kpi/documents/{doc}/void",
        data={"csrf_token": csrf, "expected_version": "2"},
    )
    assert deleted.status_code == 302
    conn = sqlite3.connect(path)
    assert conn.execute(
        "SELECT is_void FROM purchases WHERE id=?", (doc,)
    ).fetchone()[0] == 1
    conn.close()



def test_purchase_v2_update_and_void_sync_as_single_aggregate(db):
    import services.offline.master_data_adapters  # noqa: F401
    import services.offline.purchase_adapter  # noqa: F401
    from services.offline.models import RemoteChange
    from services.offline.pull_service import build_pull_response
    from services.offline.remote_applier import apply_remote_change

    remote = sqlite3.connect(":memory:")
    remote.row_factory = sqlite3.Row
    db.backup(remote)

    doc, key, payload = purchase(db)
    first = build_pull_response(
        db,
        cursor=None,
        limit=500,
        device_uuid=str(uuid4()),
        include_purchases=True,
        tenant_id=1,
    ).changes
    for change in first:
        if change["entity_type"] not in ("supplier", "purchase"):
            continue
        with business_transaction(remote):
            apply_remote_change(
                remote,
                RemoteChange(
                    change["entity_type"],
                    change["entity_uuid"],
                    change["operation"],
                    change["payload"],
                    change["version"],
                    str(uuid4()),
                    datetime.now(timezone.utc),
                ),
                tenant_id=1,
            )
    assert remote.execute("SELECT stock_qty FROM products WHERE id=11").fetchone()[0] == 2

    changed = copy.deepcopy(payload)
    changed["items"][0]["qty"] = 5
    update_purchase(
        db,
        tenant_id=1,
        entity_uuid=key,
        payload=changed,
        expected_version=1,
    )
    second = build_pull_response(
        db,
        cursor=None,
        limit=500,
        device_uuid=str(uuid4()),
        include_purchases=True,
        tenant_id=1,
    ).changes
    update_change = next(
        c for c in second
        if c["entity_type"] == "purchase" and c["entity_uuid"] == key
    )
    assert update_change["operation"] == "update"
    assert update_change["version"] == 2
    with business_transaction(remote):
        apply_remote_change(
            remote,
            RemoteChange(
                update_change["entity_type"],
                update_change["entity_uuid"],
                update_change["operation"],
                update_change["payload"],
                update_change["version"],
                str(uuid4()),
                datetime.now(timezone.utc),
            ),
            tenant_id=1,
        )
    assert remote.execute("SELECT stock_qty FROM products WHERE id=11").fetchone()[0] == 5

    void_purchase(db, tenant_id=1, entity_uuid=key, expected_version=2)
    third = build_pull_response(
        db,
        cursor=None,
        limit=500,
        device_uuid=str(uuid4()),
        include_purchases=True,
        tenant_id=1,
    ).changes
    void_change = next(
        c for c in third
        if c["entity_type"] == "purchase" and c["entity_uuid"] == key
    )
    assert void_change["operation"] == "update"
    assert void_change["version"] == 3
    assert void_change["payload"]["voided"] is True
    with business_transaction(remote):
        apply_remote_change(
            remote,
            RemoteChange(
                void_change["entity_type"],
                void_change["entity_uuid"],
                void_change["operation"],
                void_change["payload"],
                void_change["version"],
                str(uuid4()),
                datetime.now(timezone.utc),
            ),
            tenant_id=1,
        )
    assert remote.execute("SELECT stock_qty FROM products WHERE id=11").fetchone()[0] == 0
    row = remote.execute(
        "SELECT is_void,sync_version FROM purchases WHERE entity_uuid=?", (key,)
    ).fetchone()
    assert row["is_void"] == 1
    assert row["sync_version"] == 3
    remote.close()


def test_sidebar_module_states_and_warehouse_ui(web):
    app, client, path = web

    kirim = client.get("/kpi")
    assert kirim.status_code == 200
    assert 'class="pw-metrics"' not in kirim.text
    assert "Kirim hujjatlari" in kirim.text

    entry = client.get("/kpi/new")
    assert entry.status_code == 200
    assert "Yangi kirim" in entry.text
    assert 'href="/kpi">Kirim hujjatlari</a>' in entry.text

    warehouse = client.get("/kpi/stock")
    assert warehouse.status_code == 200
    assert "css/warehouse.css" in warehouse.text
    assert "Qoldiq tannarxi" in warehouse.text
    assert "Sotuv qiymati" in warehouse.text

    warehouse_link = re.search(
        r'href="/kpi/stock"\s+class="([^"]+)"',
        warehouse.text,
    )
    kirim_link = re.search(
        r'href="/kpi/new"\s+class="([^"]+)"',
        warehouse.text,
    )
    assert warehouse_link and "active" in warehouse_link.group(1).split()
    assert kirim_link and "active" not in kirim_link.group(1).split()

    suppliers = client.get("/kpi/suppliers")
    assert suppliers.status_code == 200
    supplier_link = re.search(
        r'href="/kpi/suppliers"\s+class="([^"]+)"',
        suppliers.text,
    )
    kirim_link = re.search(
        r'href="/kpi/new"\s+class="([^"]+)"',
        suppliers.text,
    )
    assert supplier_link and "active" in supplier_link.group(1).split()
    assert kirim_link and "active" not in kirim_link.group(1).split()

    assert warehouse.text.count('href="/kpi/new"') >= 2


def test_kirim_uses_uzbek_validation_and_minimal_entry(web):
    app, client, path = web
    page = client.get("/kpi/new")
    assert page.status_code == 200
    assert 'id="purchase-form" method="post" autocomplete="off" novalidate' in page.text
    assert 'id="pw-supplier-select-error"' in page.text
    assert 'id="pw-date-error"' in page.text
    assert 'class="pw-panel pw-simple-entry"' in page.text
    assert 'id="pw-table-wrap" hidden' in page.text
    assert 'id="pw-list-meta" hidden' in page.text
    assert 'id="pw-note-toggle"' in page.text
    assert 'id="pw-note-field"' in page.text
    assert re.search(r'id="pw-note-field"\s+hidden', page.text)
    assert "Mahsulot tanlang" not in page.text
    assert 'class="pw-simple-totalbar is-minimal"' in page.text
    assert 'name="method"' not in page.text
    assert 'id="pw-pay-all"' not in page.text
    assert 'id="pw-debt"' not in page.text
    assert '>To‘lov<' not in page.text
    assert '>Kassa<' not in page.text
    assert '>Qarz<' not in page.text
    assert '20260927_kirim_minimal_v5' in page.text

    script = client.get("/static/js/purchases.js")
    assert script.status_code == 200
    body = script.get_data(as_text=True)
    assert "Yetkazib beruvchini tanlang." in body
    assert "Kirim sanasini kiriting." in body
    assert "Yetkazib beruvchi nomini kiriting." in body
    assert "pw-result-main" in body
    assert "pw-result-meta" in body
    assert "pw-table-wrap" in body
    assert "pw-list-meta" in body
    assert "pw-note-toggle" in body
    assert "setNoteOpen" in body
