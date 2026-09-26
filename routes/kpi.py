"""Purchase workspace: documents, suppliers and stock, scoped to the current firm."""

import json
import secrets
import sqlite3
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from flask import (
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from services.business_writes import business_transaction
from services.business_writes.purchases import (
    create_supplier,
    prepare_purchase,
    save_purchase,
    pay_purchase,
    update_purchase,
    void_purchase,
    number,
)


def register_kpi_routes(
    app,
    *,
    app_name,
    init_db,
    get_db,
    q,
    q1,
    parse_int,
    parse_float,
    login_required,
    admin_required,
):
    def identity():
        row = q1(
            """SELECT u.tenant_id FROM users u JOIN tenants t ON t.id=u.tenant_id
            WHERE u.id=? AND u.is_active=1 AND u.role='admin' AND t.is_active=1""",
            (session.get("user_id"),),
        )
        if not row:
            abort(403)
        return row["tenant_id"]

    def token():
        if not session.get("purchase_csrf"):
            session["purchase_csrf"] = secrets.token_urlsafe(32)
        return session["purchase_csrf"]

    def check_csrf():
        value = request.headers.get("X-CSRF-Token") or request.form.get(
            "csrf_token", ""
        )
        if not value or not secrets.compare_digest(
            value, session.get("purchase_csrf", "")
        ):
            abort(400, "Sahifani yangilang va qayta urinib ko‘ring")

    def today():
        return datetime.now(ZoneInfo("Asia/Tashkent")).date().isoformat()

    def page(template, **context):
        return render_template(
            template, app_name=app_name, csrf_token=token(), today=today(), **context
        )

    def suppliers(tenant):
        return q(
            "SELECT id,name,phone FROM suppliers WHERE tenant_id=? ORDER BY name,id",
            (tenant,),
        )

    def purchase_products(tenant):
        return q(
            """SELECT p.id,p.name,p.stock_qty,c.name category,
            COALESCE((SELECT m.unit_cost_uzs FROM inventory_moves m WHERE m.product_id=p.id AND m.move_type='IN' ORDER BY m.id DESC LIMIT 1),0) last_cost,
            COALESCE((SELECT group_concat(b.barcode,' ') FROM product_barcodes b WHERE b.product_id=p.id AND b.tenant_id=p.tenant_id),'') barcodes
            FROM products p JOIN categories c ON c.id=p.category_id
            WHERE p.tenant_id=? AND c.tenant_id=? AND p.is_active=1 AND c.is_active=1
            ORDER BY p.name""",
            (tenant, tenant),
        )

    @app.route("/kpi")
    @login_required
    @admin_required
    def kpi():
        tenant = identity()
        search = request.args.get("q", "").strip()[:160]
        supplier = parse_int(request.args.get("supplier"))
        start, end = request.args.get("from", ""), request.args.get("to", "")
        status = request.args.get("status", "")
        page_no = max(1, parse_int(request.args.get("page"), 1))
        clauses, params = ["p.tenant_id=?", "COALESCE(p.is_void,0)=0"], [tenant]
        if search:
            clauses.append(
                "(s.name LIKE ? OR p.reference LIKE ? OR CAST(p.id AS TEXT)=?)"
            )
            params += [f"%{search}%", f"%{search}%", search]
        if supplier:
            clauses.append("p.supplier_id=?")
            params.append(supplier)
        if start:
            clauses.append("p.purchase_date>=?")
            params.append(start)
        if end:
            clauses.append("p.purchase_date<=?")
            params.append(end)
        if status == "debt":
            clauses.append("p.total_uzs-COALESCE(pay.paid,0)>0.005")
        elif status == "paid":
            clauses.append("p.total_uzs-COALESCE(pay.paid,0)<=0.005")
        source = """FROM purchases p JOIN suppliers s ON s.id=p.supplier_id
            LEFT JOIN (SELECT purchase_id,SUM(amount_uzs) paid FROM purchase_payments GROUP BY purchase_id) pay ON pay.purchase_id=p.id
            WHERE """ + " AND ".join(clauses)
        totals = q1(
            "SELECT COUNT(*) count,COALESCE(SUM(p.total_uzs),0) total,COALESCE(SUM(pay.paid),0) paid "
            + source,
            tuple(params),
        )
        pages = max(1, (totals["count"] + 24) // 25)
        page_no = min(page_no, pages)
        rows = q(
            """SELECT p.*,s.name supplier_name,COALESCE(pay.paid,0) paid,
            (SELECT COUNT(*) FROM purchase_items i WHERE i.purchase_id=p.id) item_count """
            + source
            + " ORDER BY p.purchase_date DESC,p.id DESC LIMIT 25 OFFSET ?",
            tuple(params + [(page_no - 1) * 25]),
        )
        links = dict(request.args)
        links.pop("page", None)
        return page(
            "purchases/index.html",
            active="documents",
            rows=rows,
            totals=totals,
            suppliers=suppliers(tenant),
            page_no=page_no,
            pages=pages,
            filters=links,
            previous=url_for("kpi", **links, page=page_no - 1),
            next=url_for("kpi", **links, page=page_no + 1),
        )

    @app.route("/kpi/new", methods=["GET", "POST"])
    @login_required
    @admin_required
    def purchase_new():
        tenant = identity()
        initial = {
            "purchase_date": today(),
            "items": [],
            "entity_uuid": str(uuid4()),
            "paid": "0",
        }
        error = None
        if request.method == "POST":
            check_csrf()
            initial.update(request.form.to_dict())
            try:
                items = json.loads(request.form.get("items", "[]"))
                initial["items"] = items
                db = get_db()
                with business_transaction(db):
                    payload = prepare_purchase(
                        db,
                        tenant_id=tenant,
                        supplier_id=parse_int(request.form.get("supplier_id")),
                        purchase_date=request.form.get("purchase_date"),
                        reference=request.form.get("reference", ""),
                        note=request.form.get("note", ""),
                        items=items,
                        entity_uuid=request.form.get("entity_uuid"),
                    )
                    purchase_id = save_purchase(
                        db,
                        tenant_id=tenant,
                        entity_uuid=request.form.get("entity_uuid"),
                        payload=payload,
                    )
                flash(
                    "Kirim saqlandi. Ombor va yetkazuvchi hisobi yangilandi.", "success"
                )
                return redirect(url_for("purchase_detail", purchase_id=purchase_id))
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                error = str(exc)
            except sqlite3.Error:
                app.logger.exception("Purchase save failed")
                error = (
                    "Kirim saqlanmadi. Ma’lumotlarni tekshirib qayta urinib ko‘ring."
                )
        products = purchase_products(tenant)
        if not isinstance(initial.get("items"), list):
            initial["items"] = []
        return page(
            "purchases/new.html",
            active="new",
            suppliers=suppliers(tenant),
            products=[dict(p) for p in products],
            initial=initial,
            error=error,
            supplier_uuid=str(uuid4()),
            draft_key=f"purchase-draft:{tenant}:{session.get('user_id')}",
        ), (422 if error else 200)

    @app.route("/kpi/documents/<int:purchase_id>")
    @login_required
    @admin_required
    def purchase_detail(purchase_id):
        tenant = identity()
        row = q1(
            """SELECT p.*,s.name supplier_name,s.phone FROM purchases p JOIN suppliers s ON s.id=p.supplier_id
            WHERE p.id=? AND p.tenant_id=? AND COALESCE(p.is_void,0)=0""",
            (purchase_id, tenant),
        )
        if not row:
            abort(404)
        items = q(
            "SELECT i.*,p.name FROM purchase_items i JOIN products p ON p.id=i.product_id WHERE i.purchase_id=? AND i.tenant_id=? ORDER BY i.id",
            (purchase_id, tenant),
        )
        payments = q(
            "SELECT * FROM purchase_payments WHERE purchase_id=? AND tenant_id=? ORDER BY payment_date,id",
            (purchase_id, tenant),
        )
        paid = sum(p["amount_uzs"] for p in payments)
        return page(
            "purchases/detail.html",
            active="documents",
            doc=row,
            items=items,
            payments=payments,
            paid=paid,
            debt=round(row["total_uzs"] - paid, 2),
            payment_uuid=str(uuid4()),
            draft_key=f"purchase-draft:{tenant}:{session.get('user_id')}",
            edit_draft_key=f"purchase-edit:{tenant}:{purchase_id}:{session.get('user_id')}",
        )

    @app.route("/kpi/documents/<int:purchase_id>/edit", methods=["GET", "POST"])
    @login_required
    @admin_required
    def purchase_edit(purchase_id):
        tenant = identity()
        doc = q1(
            """SELECT p.*,s.name supplier_name FROM purchases p
            JOIN suppliers s ON s.id=p.supplier_id
            WHERE p.id=? AND p.tenant_id=? AND COALESCE(p.is_void,0)=0""",
            (purchase_id, tenant),
        )
        if not doc:
            abort(404)
        rows = q(
            """SELECT i.product_id,i.qty,i.unit_cost_uzs FROM purchase_items i
            WHERE i.purchase_id=? AND i.tenant_id=? ORDER BY i.id""",
            (purchase_id, tenant),
        )
        paid_row = q1(
            "SELECT COALESCE(SUM(amount_uzs),0) paid FROM purchase_payments WHERE purchase_id=? AND tenant_id=?",
            (purchase_id, tenant),
        )
        paid = float(paid_row["paid"] or 0)
        initial = {
            "entity_uuid": doc["entity_uuid"],
            "supplier_id": doc["supplier_id"],
            "purchase_date": doc["purchase_date"],
            "reference": doc["reference"],
            "note": doc["note"],
            "paid": paid,
            "items": [dict(r) for r in rows],
        }
        error = None
        if request.method == "POST":
            check_csrf()
            initial.update(request.form.to_dict())
            initial["paid"] = paid
            try:
                items = json.loads(request.form.get("items", "[]"))
                initial["items"] = items
                db = get_db()
                payload = prepare_purchase(
                    db,
                    tenant_id=tenant,
                    supplier_id=parse_int(request.form.get("supplier_id")),
                    purchase_date=request.form.get("purchase_date"),
                    reference=request.form.get("reference", ""),
                    note=request.form.get("note", ""),
                    items=items,
                    entity_uuid=doc["entity_uuid"],
                )
                update_purchase(
                    db,
                    tenant_id=tenant,
                    entity_uuid=doc["entity_uuid"],
                    payload=payload,
                    expected_version=request.form.get("expected_version"),
                )
                flash("Kirim yangilandi. Ombor va yetkazuvchi hisobi qayta hisoblandi.", "success")
                return redirect(url_for("purchase_detail", purchase_id=purchase_id))
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                error = str(exc)
            except sqlite3.Error:
                app.logger.exception("Purchase edit failed")
                error = "Kirim yangilanmadi. Ma’lumotlarni tekshirib qayta urinib ko‘ring."
        if not isinstance(initial.get("items"), list):
            initial["items"] = []
        return page(
            "purchases/new.html",
            active="documents",
            suppliers=suppliers(tenant),
            products=[dict(p) for p in purchase_products(tenant)],
            initial=initial,
            error=error,
            supplier_uuid=str(uuid4()),
            draft_key=f"purchase-edit:{tenant}:{purchase_id}:{session.get('user_id')}",
            edit_mode=True,
            expected_version=(
                request.form.get("expected_version")
                if request.method == "POST"
                else doc["sync_version"]
            ),
            purchase_id=purchase_id,
        ), (422 if error else 200)

    @app.post("/kpi/documents/<int:purchase_id>/void")
    @login_required
    @admin_required
    def purchase_void(purchase_id):
        tenant = identity()
        check_csrf()
        doc = q1(
            """SELECT entity_uuid,sync_version FROM purchases
            WHERE id=? AND tenant_id=? AND COALESCE(is_void,0)=0""",
            (purchase_id, tenant),
        )
        if not doc:
            abort(404)
        try:
            void_purchase(
                get_db(),
                tenant_id=tenant,
                entity_uuid=doc["entity_uuid"],
                expected_version=request.form.get("expected_version"),
            )
            flash("Kirim bekor qilindi. Ombor va yetkazuvchi hisobi qayta hisoblandi.", "success")
            return redirect(url_for("kpi"))
        except (ValueError, sqlite3.Error) as exc:
            if isinstance(exc, sqlite3.Error):
                app.logger.exception("Purchase void failed")
            flash(
                str(exc) if isinstance(exc, ValueError) else "Kirim bekor qilinmadi",
                "danger",
            )
            return redirect(url_for("purchase_detail", purchase_id=purchase_id))

    @app.post("/kpi/documents/<int:purchase_id>/pay")
    @login_required
    @admin_required
    def purchase_pay(purchase_id):
        tenant = identity()
        check_csrf()
        doc = q1(
            "SELECT entity_uuid FROM purchases WHERE id=? AND tenant_id=? AND COALESCE(is_void,0)=0",
            (purchase_id, tenant),
        )
        if not doc:
            abort(404)
        try:
            pay_purchase(
                get_db(),
                tenant_id=tenant,
                entity_uuid=request.form.get("entity_uuid"),
                payload={
                    "purchase_uuid": doc["entity_uuid"],
                    "payment_date": request.form.get("payment_date"),
                    "amount_uzs": request.form.get("amount_uzs"),
                    "method": request.form.get("method"),
                    "note": request.form.get("note", ""),
                },
            )
            flash("To‘lov saqlandi", "success")
        except (ValueError, sqlite3.Error) as exc:
            if isinstance(exc, sqlite3.Error):
                app.logger.exception("Purchase payment failed")
            flash(
                str(exc) if isinstance(exc, ValueError) else "To‘lov saqlanmadi",
                "danger",
            )
        return redirect(url_for("purchase_detail", purchase_id=purchase_id))

    @app.route("/kpi/suppliers", methods=["GET", "POST"])
    @login_required
    @admin_required
    def purchase_suppliers():
        tenant = identity()
        if request.method == "POST":
            check_csrf()
            try:
                supplier_id = create_supplier(
                    get_db(),
                    tenant_id=tenant,
                    name=request.form.get("name", ""),
                    phone=request.form.get("phone", ""),
                    entity_uuid=request.form.get("entity_uuid"),
                )
                if request.headers.get("Accept") == "application/json":
                    row = q1(
                        "SELECT id,name,phone FROM suppliers WHERE id=? AND tenant_id=?",
                        (supplier_id, tenant),
                    )
                    return jsonify(**dict(row), next_uuid=str(uuid4())), 201
                flash("Yetkazuvchi qo‘shildi", "success")
            except ValueError as exc:
                if request.headers.get("Accept") == "application/json":
                    return jsonify(error=str(exc)), 422
                flash(str(exc), "danger")
            return redirect(url_for("purchase_suppliers"))
        rows = q(
            """SELECT s.*, COALESCE(d.total,0) total,COALESCE(pay.paid,0) paid,COALESCE(d.count,0) count
            FROM suppliers s LEFT JOIN (
                SELECT supplier_id,SUM(total_uzs) total,COUNT(*) count
                FROM purchases WHERE COALESCE(is_void,0)=0 GROUP BY supplier_id
            ) d ON d.supplier_id=s.id
            LEFT JOIN (
                SELECT p.supplier_id,SUM(pp.amount_uzs) paid
                FROM purchase_payments pp JOIN purchases p ON p.id=pp.purchase_id
                WHERE COALESCE(p.is_void,0)=0 GROUP BY p.supplier_id
            ) pay ON pay.supplier_id=s.id
            WHERE s.tenant_id=? ORDER BY s.name,s.id""",
            (tenant,),
        )
        return page(
            "purchases/suppliers.html",
            active="suppliers",
            rows=rows,
            entity_uuid=str(uuid4()),
        )

    @app.route("/kpi/suppliers/<int:supplier_id>")
    @login_required
    @admin_required
    def purchase_supplier_detail(supplier_id):
        tenant = identity()
        supplier = q1(
            "SELECT id,name,phone FROM suppliers WHERE id=? AND tenant_id=?",
            (supplier_id, tenant),
        )
        if not supplier:
            abort(404)
        documents = q(
            """SELECT p.*,COALESCE(pay.paid,0) paid,
            (SELECT COUNT(*) FROM purchase_items i WHERE i.purchase_id=p.id) item_count
            FROM purchases p
            LEFT JOIN (SELECT purchase_id,SUM(amount_uzs) paid FROM purchase_payments GROUP BY purchase_id) pay ON pay.purchase_id=p.id
            WHERE p.tenant_id=? AND p.supplier_id=? AND COALESCE(p.is_void,0)=0
            ORDER BY p.purchase_date DESC,p.id DESC""",
            (tenant, supplier_id),
        )
        payments = q(
            """SELECT pp.*,p.id purchase_id,p.reference FROM purchase_payments pp
            JOIN purchases p ON p.id=pp.purchase_id
            WHERE pp.tenant_id=? AND p.supplier_id=? AND COALESCE(p.is_void,0)=0
            ORDER BY pp.payment_date DESC,pp.id DESC""",
            (tenant, supplier_id),
        )
        total = round(sum(r["total_uzs"] for r in documents), 2)
        paid = round(sum(r["amount_uzs"] for r in payments), 2)
        return page(
            "purchases/supplier_detail.html",
            active="suppliers",
            supplier=supplier,
            documents=documents,
            payments=payments,
            total=total,
            paid=paid,
            debt=round(total-paid, 2),
            unpaid_documents=[
                r for r in documents if r["total_uzs"] - r["paid"] > 0.005
            ],
            payment_uuid=str(uuid4()),
        )

    @app.post("/kpi/suppliers/<int:supplier_id>/pay")
    @login_required
    @admin_required
    def purchase_supplier_pay(supplier_id):
        tenant = identity()
        check_csrf()
        purchase_id = parse_int(request.form.get("purchase_id"))
        doc = q1(
            """SELECT id,entity_uuid FROM purchases
            WHERE id=? AND supplier_id=? AND tenant_id=? AND COALESCE(is_void,0)=0""",
            (purchase_id, supplier_id, tenant),
        )
        if not doc:
            abort(404)
        try:
            pay_purchase(
                get_db(),
                tenant_id=tenant,
                entity_uuid=request.form.get("entity_uuid"),
                payload={
                    "purchase_uuid": doc["entity_uuid"],
                    "payment_date": request.form.get("payment_date"),
                    "amount_uzs": request.form.get("amount_uzs"),
                    "method": request.form.get("method"),
                    "note": request.form.get("note", ""),
                },
            )
            flash("Yetkazib beruvchiga to‘lov saqlandi", "success")
        except (ValueError, sqlite3.Error) as exc:
            if isinstance(exc, sqlite3.Error):
                app.logger.exception("Supplier payment failed")
            flash(
                str(exc) if isinstance(exc, ValueError) else "To‘lov saqlanmadi",
                "danger",
            )
        return redirect(url_for("purchase_supplier_detail", supplier_id=supplier_id))

    @app.route("/kpi/stock")
    @login_required
    @admin_required
    def purchase_stock():
        tenant = identity()
        search = request.args.get("q", "").strip()[:160]
        category = parse_int(request.args.get("category"))
        stock_status = request.args.get("stock", "all")
        if stock_status not in ("all", "in", "out"):
            stock_status = "all"

        all_rows = q(
            """SELECT p.id,p.name,p.stock_qty,p.sell_price_default_uzs,
            c.id category_id,c.name category,
            COALESCE((
                SELECT SUM(m.qty*m.unit_cost_uzs)/NULLIF(SUM(m.qty),0)
                FROM inventory_moves m
                WHERE m.product_id=p.id AND m.move_type='IN'
            ),0) avg_cost,
            COALESCE((
                SELECT group_concat(b.barcode,' ')
                FROM product_barcodes b
                WHERE b.product_id=p.id AND b.tenant_id=p.tenant_id
            ),'') barcodes
            FROM products p
            JOIN categories c ON c.id=p.category_id
            WHERE p.tenant_id=? AND c.tenant_id=?
              AND p.is_active=1 AND c.is_active=1
            ORDER BY c.sort_order,c.name,p.name""",
            (tenant, tenant),
        )

        needle = search.casefold()
        rows = []
        for row in all_rows:
            stock_qty = float(row["stock_qty"] or 0)
            if category and int(row["category_id"]) != category:
                continue
            if stock_status == "in" and stock_qty <= 0:
                continue
            if stock_status == "out" and stock_qty > 0:
                continue
            if needle and needle not in (
                f"{row['name']} {row['category']} {row['barcodes']}".casefold()
            ):
                continue
            rows.append(row)

        metrics = {
            "product_count": len(all_rows),
            "in_stock_count": sum(
                1 for row in all_rows if float(row["stock_qty"] or 0) > 0
            ),
            "out_stock_count": sum(
                1 for row in all_rows if float(row["stock_qty"] or 0) <= 0
            ),
            "cost_value": round(
                sum(
                    float(row["stock_qty"] or 0) * float(row["avg_cost"] or 0)
                    for row in all_rows
                    if float(row["stock_qty"] or 0) > 0
                ),
                2,
            ),
            "sale_value": round(
                sum(
                    float(row["stock_qty"] or 0)
                    * float(row["sell_price_default_uzs"] or 0)
                    for row in all_rows
                    if float(row["stock_qty"] or 0) > 0
                ),
                2,
            ),
        }

        cats = q(
            "SELECT id,name FROM categories WHERE tenant_id=? AND is_active=1 ORDER BY sort_order,name",
            (tenant,),
        )
        return page(
            "purchases/stock.html",
            rows=rows,
            cats=cats,
            metrics=metrics,
            search=search,
            category=category,
            stock_status=stock_status,
        )

    @app.route("/kpi/legacy")
    @login_required
    @admin_required
    def purchase_legacy():
        tenant = identity()
        page_no = max(1, parse_int(request.args.get("page"), 1))
        sql = """FROM inventory_moves m JOIN products p ON p.id=m.product_id WHERE p.tenant_id=? AND m.move_type='IN'
                 AND NOT EXISTS(SELECT 1 FROM purchase_items i WHERE i.inventory_move_id=m.id)"""
        count = q1("SELECT COUNT(*) count " + sql, (tenant,))["count"]
        pages = max(1, (count + 49) // 50)
        page_no = min(page_no, pages)
        rows = q(
            "SELECT m.*,p.name "
            + sql
            + " ORDER BY m.move_date DESC,m.id DESC LIMIT 50 OFFSET ?",
            (tenant, (page_no - 1) * 50),
        )
        return page(
            "purchases/legacy.html",
            active="documents",
            rows=rows,
            page_no=page_no,
            pages=pages,
        )

    @app.route("/kpi/<int:category_id>")
    @login_required
    @admin_required
    def kpi_category(category_id):
        identity()
        return redirect(url_for("purchase_stock", category=category_id))

    @app.route("/kpi/<int:category_id>/kirim", methods=["GET", "POST"])
    @login_required
    @admin_required
    def kpi_kirim(category_id):
        identity()
        if request.method == "POST":
            flash(
                "Kirim formasi yangilandi. Mahsulotlarni yangi hujjatda kiriting.",
                "warning",
            )
        return redirect(url_for("purchase_new", category=category_id), code=303)
