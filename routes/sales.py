from datetime import date, datetime, timezone
import uuid

from services.business_writes import (
    business_transaction,
    consume_stock,
    record_sale_payments,
)

from flask import (
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from services.device_identity import get_device_identity
from services.offline.constants import OPERATION_CREATE
from services.offline.models import SyncRecord
from services.offline.sales_aggregate import (
    SALE_AGGREGATE_SCHEMA_VERSION,
    SaleAggregatePayload,
)
from services.offline.sqlite_queue import SQLiteSyncQueue
from services.sale_item_pricing import (
    calculate_sale_item_pricing,
)


def register_sales_routes(
    app,
    *,
    init_db,
    get_db,
    q,
    q1,
    parse_int,
    parse_float,
    fmt0_filter,
    login_required,
    cart_get,
    cart_total,
    product_qty,
    product_avg_cost,
):
    @app.route("/sales", methods=["GET", "POST"])
    @login_required
    def sales():
        init_db()

        legacy_product_id = parse_int(
            request.args.get("product_id") or "0"
        )
        legacy_action = (
            request.args.get("action") or ""
        ).strip()

        if (
            legacy_product_id > 0
            and legacy_action
            in ("inc", "dec", "del", "remove")
        ):
            return sales_qty(
                legacy_product_id,
                legacy_action,
            )

        cart = cart_get()

        cats = q("""
            SELECT id, name
            FROM categories
            WHERE is_active=1
            ORDER BY sort_order, id
        """)

        cat_id = parse_int(
            request.args.get("category_id") or "0"
        )

        if cat_id <= 0 and cats:
            cat_id = int(cats[0]["id"])

        products = []

        if cat_id > 0:
            products = q("""
                SELECT
                    p.id,
                    p.name,
                    p.sell_price_default_uzs
                        AS sell_default,
                    COALESCE(p.stock_qty, 0) AS qty
                FROM products p
                WHERE p.is_active=1
                  AND p.category_id=?
                ORDER BY p.name
            """, (cat_id,))

        cart_items = []

        for product_id, item in cart["items"].items():
            cart_items.append({
                "product_id": int(product_id),
                "name": item["name"],
                "qty": float(item["qty"]),
                "price": float(item["price"]),
                "line_total": (
                    float(item["qty"])
                    * float(item["price"])
                ),
            })

        total = cart_total(cart)
        today = date.today().isoformat()

        if session.get("role") == "agent":
            sum_row = q1("""
                SELECT
                    COALESCE(
                        SUM(total_sell_uzs),
                        0
                    ) AS sell,
                    COALESCE(
                        SUM(total_cost_uzs),
                        0
                    ) AS cost,
                    COALESCE(
                        SUM(total_profit_uzs),
                        0
                    ) AS profit
                FROM sales
                WHERE sale_date=?
                  AND agent_id=?
            """, (
                today,
                session.get("user_id"),
            ))
        else:
            sum_row = q1("""
                SELECT
                    COALESCE(
                        SUM(total_sell_uzs),
                        0
                    ) AS sell,
                    COALESCE(
                        SUM(total_cost_uzs),
                        0
                    ) AS cost,
                    COALESCE(
                        SUM(total_profit_uzs),
                        0
                    ) AS profit
                FROM sales
                WHERE sale_date=?
            """, (today,))

        sum_sell = (
            float(sum_row["sell"])
            if sum_row else 0.0
        )
        sum_cost = (
            float(sum_row["cost"])
            if sum_row else 0.0
        )
        sum_profit = (
            float(sum_row["profit"])
            if sum_row else 0.0
        )

        template = (
            "agent_sales/index.html"
            if session.get("role") == "agent"
            else "sales.html"
        )

        return render_template(
            template,
            cats=cats,
            selected_cat_id=cat_id,
            products=products,
            cart_items=cart_items,
            cart_total=total,
            today=today,
            sum_sell=sum_sell,
            sum_cost=sum_cost,
            sum_profit=sum_profit,
        )

    @app.route("/sales/products", methods=["GET"])
    @login_required
    def sales_products():
        init_db()

        if session.get("role") != "agent":
            return redirect(url_for("sales"))

        cat_id = parse_int(
            request.args.get("category_id") or "0"
        )

        products = []

        if cat_id > 0:
            products = q("""
                SELECT
                    p.id,
                    p.name,
                    p.sell_price_default_uzs
                        AS sell_default,
                    COALESCE(p.stock_qty, 0) AS qty
                FROM products p
                WHERE p.is_active=1
                  AND p.category_id=?
                ORDER BY p.name
            """, (cat_id,))

        view = (
            request.args.get("view") or "mobile"
        ).strip()

        template = (
            "agent_sales/products_desktop.html"
            if view == "desktop"
            else "agent_sales/products_mobile.html"
        )

        return render_template(
            template,
            products=products,
            selected_cat_id=cat_id,
        )

    @app.route("/sales/add", methods=["POST"])
    @login_required
    def sales_add():
        init_db()

        category_id = parse_int(
            request.form.get("category_id") or "0"
        )
        product_id = parse_int(
            request.form.get("product_id") or "0"
        )
        qty = parse_float(
            request.form.get("qty") or ""
        )
        price = parse_float(
            request.form.get("price_uzs") or ""
        )

        list_price = parse_float(
            request.form.get("list_price_uzs") or ""
        )

        discount_type = (
            request.form.get("discount_type")
            or "none"
        ).strip().lower()

        discount_value = parse_float(
            request.form.get("discount_value") or "0"
        )

        if product_id <= 0:
            flash(
                "Mahsulot tanlanmadi",
                "danger",
            )
            return redirect(
                url_for(
                    "sales",
                    category_id=category_id,
                )
            )

        if qty is None or qty <= 0:
            flash("Miqdor noto‘g‘ri", "danger")
            return redirect(
                url_for(
                    "sales",
                    category_id=category_id,
                )
            )

        if price is None or price <= 0:
            flash("Narx noto‘g‘ri", "danger")
            return redirect(
                url_for(
                    "sales",
                    category_id=category_id,
                )
            )

        if list_price is None or list_price <= 0:
            list_price = float(price)

        if discount_value is None:
            discount_value = 0.0

        try:
            pricing = calculate_sale_item_pricing(
                qty=float(qty),
                list_price_uzs=float(list_price),
                discount_type=discount_type,
                discount_value=float(discount_value),
            )
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(
                url_for(
                    "sales",
                    category_id=category_id,
                )
            )

        price = pricing.sell_price_uzs
        list_price = pricing.list_price_uzs
        discount_type = pricing.discount_type
        discount_value = pricing.discount_value

        product = q1("""
            SELECT
                p.id,
                p.name,
                p.sell_price_default_uzs
            FROM products p
            WHERE p.id=?
              AND p.is_active=1
        """, (product_id,))

        if not product:
            flash(
                "Mahsulot topilmadi yoki nofaol",
                "danger",
            )
            return redirect(
                url_for(
                    "sales",
                    category_id=category_id,
                )
            )

        if session.get("role") == "agent":
            default_price = float(
                product[
                    "sell_price_default_uzs"
                ] or 0
            )

            if float(price) + 1e-9 < default_price:
                flash(
                    "Narx defaultdan past "
                    "bo‘lmasin. Minimal: "
                    f"{fmt0_filter(default_price)} "
                    "so‘m",
                    "danger",
                )
                return redirect(
                    url_for(
                        "sales",
                        category_id=category_id,
                    )
                )

        available = product_qty(product_id)
        cart = cart_get()

        existing_qty = float(
            cart["items"]
            .get(str(product_id), {})
            .get("qty", 0)
        )

        if (
            available is not None
            and available + 1e-9
            < existing_qty + float(qty)
        ):
            flash(
                "Qoldiq yetarli emas. "
                f"Bor: {available:.2f}",
                "danger",
            )
            return redirect(
                url_for(
                    "sales",
                    category_id=category_id,
                )
            )

        product_key = str(product_id)

        if product_key in cart["items"]:
            cart["items"][product_key]["qty"] = (
                existing_qty + float(qty)
            )
            cart["items"][product_key]["price"] = (
                float(price)
            )
            cart["items"][product_key]["list_price"] = (
                float(list_price)
            )
            cart["items"][product_key]["discount_type"] = (
                discount_type
            )
            cart["items"][product_key]["discount_value"] = (
                float(discount_value)
            )
        else:
            cart["items"][product_key] = {
                "name": product["name"],
                "qty": float(qty),
                "price": float(price),
                "list_price": float(list_price),
                "discount_type": discount_type,
                "discount_value": float(discount_value),
            }

        session["cart"] = cart

        flash(
            "Savatga qo‘shildi ✅",
            "success",
        )

        return redirect(
            url_for(
                "sales",
                category_id=category_id,
            )
        )

    @app.route(
        "/sales/remove/<int:product_id>",
        methods=["POST"],
    )
    @login_required
    def sales_remove(product_id: int):
        cart = cart_get()
        cart["items"].pop(str(product_id), None)
        session["cart"] = cart
        return redirect(url_for("sales"))

    @app.route("/sales/clear", methods=["POST"])
    @login_required
    def sales_clear():
        session["cart"] = {"items": {}}
        flash("Savat tozalandi", "success")
        return redirect(url_for("sales"))

    @app.route(
        "/sales/checkout",
        methods=["POST"],
    )
    @login_required
    def sales_checkout():
        init_db()

        cart = cart_get()

        if not cart["items"]:
            flash(
                "Savat bo‘sh",
                "danger",
            )

            return redirect(
                url_for("sales")
            )

        global_discount_type = (
            request.form.get("global_discount_type")
            or "none"
        ).strip().lower()

        global_discount_value = parse_float(
            request.form.get("global_discount_value")
            or "0"
        )

        if global_discount_value is None:
            global_discount_value = 0.0

        cart_base_total = 0.0

        try:
            for item in cart["items"].values():
                qty = float(item.get("qty") or 0)
                base_price = float(
                    item.get("price") or 0
                )

                if qty <= 0 or base_price <= 0:
                    raise ValueError(
                        "Savatda noto‘g‘ri qiymat bor"
                    )

                cart_base_total += qty * base_price

            global_pricing = calculate_sale_item_pricing(
                qty=1.0,
                list_price_uzs=cart_base_total,
                discount_type=global_discount_type,
                discount_value=float(global_discount_value),
            )

        except (TypeError, ValueError) as exc:
            flash(str(exc), "danger")
            return redirect(url_for("sales"))

        global_discount_total = float(
            global_pricing.discount_total_uzs
        )

        payment_method = (
            request.form.get("payment_method")
            or "CASH"
        ).strip().upper()

        if payment_method not in (
            "CASH",
            "CLICK",
            "MIXED",
        ):
            flash(
                "To‘lov turi noto‘g‘ri",
                "danger",
            )
            return redirect(url_for("sales"))

        requested_cash_uzs = parse_float(
            request.form.get("cash_uzs")
            or "0"
        )

        requested_click_uzs = parse_float(
            request.form.get("click_uzs")
            or "0"
        )

        if requested_cash_uzs is None:
            requested_cash_uzs = 0.0

        if requested_click_uzs is None:
            requested_click_uzs = 0.0

        db = get_db()

        try:
            with business_transaction(db) as tx:
                sale_date = date.today().isoformat()

                sale_uuid = str(uuid.uuid4())
                sale_sync_version = 1

                sale_id = tx.execute(
                    """
                    INSERT INTO sales(
                        sale_date,
                        agent_id,
                        total_sell_uzs,
                        total_cost_uzs,
                        total_profit_uzs,
                        entity_uuid,
                        sync_version
                    )
                    VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        sale_date,
                        session.get("user_id"),
                        0,
                        0,
                        0,
                        sale_uuid,
                        sale_sync_version,
                    ),
                ).lastrowid

                total_sell = 0.0
                total_cost = 0.0
                total_profit = 0.0
                aggregate_items = []

                cart_entries = list(
                    cart["items"].items()
                )

                allocated_discount = 0.0

                for item_index, (
                    product_id,
                    item,
                ) in enumerate(cart_entries):
                    pid = int(
                        product_id
                    )

                    qty = float(
                        item["qty"]
                    )

                    base_price = float(
                        item["price"]
                    )

                    base_line_total = (
                        qty * base_price
                    )

                    item_discount_type = "none"
                    item_discount_value = 0.0

                    if global_discount_total > 0:
                        if (
                            global_discount_type
                            == "percent"
                        ):
                            item_discount_type = "percent"
                            item_discount_value = float(
                                global_discount_value
                            )

                        elif (
                            global_discount_type
                            == "amount"
                        ):
                            item_discount_type = "amount"

                            is_last = (
                                item_index
                                == len(cart_entries) - 1
                            )

                            if is_last:
                                line_discount = max(
                                    0.0,
                                    global_discount_total
                                    - allocated_discount,
                                )
                            else:
                                line_discount = (
                                    global_discount_total
                                    * base_line_total
                                    / cart_base_total
                                )

                            line_discount = min(
                                base_line_total,
                                line_discount,
                            )

                            allocated_discount += (
                                line_discount
                            )

                            item_discount_value = (
                                line_discount / qty
                            )

                    pricing = calculate_sale_item_pricing(
                        qty=qty,
                        list_price_uzs=base_price,
                        discount_type=item_discount_type,
                        discount_value=item_discount_value,
                    )

                    price = float(
                        pricing.sell_price_uzs
                    )

                    if qty <= 0 or price <= 0:
                        raise ValueError(
                            "Savatda noto‘g‘ri "
                            "qiymat bor"
                        )

                    available = product_qty(
                        pid
                    )

                    if available + 1e-9 < qty:
                        raise ValueError(
                            "Qoldiq yetarli emas: "
                            f"{item['name']} "
                            f"(Bor: {available:.2f})"
                        )

                    sell_total = pricing.sell_total_uzs
                    discount_total = (
                        pricing.discount_total_uzs
                    )

                    unit_cost = product_avg_cost(
                        pid
                    )
                    cost_total = qty * unit_cost
                    profit = sell_total - cost_total

                    total_sell += sell_total
                    total_cost += cost_total
                    total_profit += profit

                    product_row = tx.execute(
                        """
                        SELECT
                            entity_uuid,
                            sell_price_default_uzs
                        FROM products
                        WHERE id=?
                          AND is_active=1
                        """,
                        (pid,),
                    ).fetchone()

                    if (
                        product_row is None
                        or not str(
                            product_row["entity_uuid"] or ""
                        ).strip()
                    ):
                        raise ValueError(
                            "Mahsulot offline UUID topilmadi: "
                            f"{item['name']}"
                        )

                    if session.get("role") == "agent":
                        default_price = float(
                            product_row[
                                "sell_price_default_uzs"
                            ] or 0
                        )

                        if (
                            price + 1e-9
                            < default_price
                        ):
                            raise ValueError(
                                "Chegirmadan keyingi narx "
                                "default narxdan past "
                                "bo‘lmasin: "
                                f"{item['name']}"
                            )

                    item_uuid = str(uuid.uuid4())
                    item_sync_version = 1

                    sale_item_id = tx.execute(
                        """
                        INSERT INTO sale_items(
                            sale_id,
                            product_id,
                            qty,
                            sell_price_uzs,
                            sell_total_uzs,
                            cost_total_uzs,
                            profit_uzs,
                            entity_uuid,
                            sync_version,
                            list_price_uzs,
                            discount_type,
                            discount_value,
                            discount_total_uzs
                        )
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            sale_id,
                            pid,
                            qty,
                            price,
                            sell_total,
                            cost_total,
                            profit,
                            item_uuid,
                            item_sync_version,
                            pricing.list_price_uzs,
                            pricing.discount_type,
                            pricing.discount_value,
                            discount_total,
                        ),
                    ).lastrowid

                    aggregate_items.append({
                        "entity_uuid": item_uuid,
                        "sync_version": item_sync_version,
                        "product_uuid": str(
                            product_row["entity_uuid"]
                        ),
                        "qty": qty,
                        "sell_price_uzs": price,
                        "unit_cost_uzs": unit_cost,
                        "list_price_uzs": (
                            pricing.list_price_uzs
                        ),
                        "discount_type": (
                            pricing.discount_type
                        ),
                        "discount_value": (
                            pricing.discount_value
                        ),
                        "discount_total_uzs": (
                            pricing.discount_total_uzs
                        ),
                    })

                    consume_stock(
                        tx,
                        move_date=sale_date,
                        product_id=pid,
                        qty=qty,
                        unit_cost_uzs=unit_cost,
                        note=f"Sotuv #{sale_id}",
                        source_type="sale_item",
                        source_id=sale_item_id,
                    )

                tx.execute(
                    """
                    UPDATE sales
                    SET
                        total_sell_uzs=?,
                        total_cost_uzs=?,
                        total_profit_uzs=?
                    WHERE id=?
                    """,
                    (
                        total_sell,
                        total_cost,
                        total_profit,
                        sale_id,
                    ),
                )

                if payment_method == "CASH":
                    cash_uzs = total_sell
                    click_uzs = 0.0

                elif payment_method == "CLICK":
                    cash_uzs = 0.0
                    click_uzs = total_sell

                else:
                    cash_uzs = float(
                        requested_cash_uzs
                    )
                    click_uzs = float(
                        requested_click_uzs
                    )

                payment_summary = record_sale_payments(
                    tx,
                    sale_id=sale_id,
                    cash_uzs=cash_uzs,
                    click_uzs=click_uzs,
                    move_date=sale_date,
                )

                aggregate = SaleAggregatePayload.from_payload({
                    "schema_version": (
                        SALE_AGGREGATE_SCHEMA_VERSION
                    ),
                    "entity_uuid": sale_uuid,
                    "sync_version": sale_sync_version,
                    "sale_date": sale_date,
                    "agent_username": (
                        session.get("username")
                    ),
                    "items": aggregate_items,
                    "payments": [
                        {
                            "payment_method": (
                                payment.payment_method
                            ),
                            "amount_uzs": (
                                payment.amount_uzs
                            ),
                        }
                        for payment
                        in payment_summary.payments
                    ],
                })

                identity = get_device_identity(tx)

                device_uuid = (
                    getattr(
                        identity,
                        "installation_uuid",
                        None,
                    )
                    or getattr(
                        identity,
                        "device_uuid",
                        None,
                    )
                    or getattr(
                        identity,
                        "database_uuid",
                        None,
                    )
                )

                if not str(device_uuid or "").strip():
                    raise RuntimeError(
                        "Offline device UUID topilmadi"
                    )

                sync_record = SyncRecord(
                    entity_type="sales_aggregate",
                    entity_uuid=sale_uuid,
                    operation=OPERATION_CREATE,
                    payload=aggregate.to_payload(),
                    device_uuid=str(device_uuid),
                    occurred_at=datetime.now(
                        timezone.utc
                    ),
                )

                sync_queue = SQLiteSyncQueue(
                    lambda: get_db()
                )

                sync_queue.enqueue(
                    sync_record,
                    connection=tx,
                )

            session["cart"] = {
                "items": {},
            }

            flash(
                "Sotuv yakunlandi ✅",
                "success",
            )

        except Exception as exc:
            if (
                request.headers.get("X-Requested-With")
                == "XMLHttpRequest"
            ):
                from flask import jsonify

                return jsonify({
                    "ok": False,
                    "error": str(exc),
                })

            flash(
                str(exc),
                "danger",
            )

        if (
            request.headers.get("X-Requested-With")
            == "XMLHttpRequest"
        ):
            from flask import jsonify

            return jsonify({
                "ok": True,
                "sale_id": sale_id,
            })

        return redirect(
            url_for("sales")
        )

    @app.route(
        "/sales/receipt/<int:sale_id>",
        methods=["GET"],
    )
    @login_required
    def sales_receipt(sale_id: int):
        init_db()

        if session.get("role") == "agent":
            sale = q1("""
                SELECT
                    id,
                    sale_date,
                    total_sell_uzs
                FROM sales
                WHERE id=?
                  AND agent_id=?
            """, (
                sale_id,
                session.get("user_id"),
            ))
        else:
            sale = q1("""
                SELECT
                    id,
                    sale_date,
                    total_sell_uzs
                FROM sales
                WHERE id=?
            """, (sale_id,))

        if not sale:
            return "Chek topilmadi", 404

        items = q("""
            SELECT
                p.name,
                si.qty,
                si.sell_price_uzs,
                si.sell_total_uzs
            FROM sale_items si
            JOIN products p
              ON p.id=si.product_id
            WHERE si.sale_id=?
            ORDER BY si.id
        """, (sale_id,))

        if request.args.get("format") == "json":
            from flask import jsonify

            return jsonify({
                "business_name": "GOLD 9999",
                "sale_id": sale["id"],
                "sale_date": sale["sale_date"],
                "total_uzs": sale["total_sell_uzs"],
                "items": [
                    {
                        "name": item["name"],
                        "qty": item["qty"],
                        "unit_price_uzs": (
                            item["sell_price_uzs"]
                        ),
                        "line_total_uzs": (
                            item["sell_total_uzs"]
                        ),
                    }
                    for item in items
                ],
            })

        return render_template(
            "sales_receipt.html",
            sale=sale,
            items=items,
        )

    @app.route(
        "/sales/qty/<int:product_id>/<action>",
        methods=["GET", "POST"],
    )
    @login_required
    def sales_qty(
        product_id: int,
        action: str,
    ):
        cart = cart_get()
        product_key = str(product_id)

        item = cart["items"].get(
            product_key,
            {"qty": 0},
        )

        try:
            qty = float(
                item.get("qty", 0)
                if isinstance(item, dict)
                else item
            )
        except (TypeError, ValueError):
            qty = 0.0

        if action == "inc":
            qty += 1.0
        elif action == "dec":
            qty = max(0.0, qty - 1.0)
        elif action in ("del", "remove"):
            qty = 0.0

        if qty <= 0:
            cart["items"].pop(
                product_key,
                None,
            )
        else:
            existing = cart["items"].get(
                product_key,
                {},
            )

            name = (
                item.get("name")
                if isinstance(item, dict)
                else ""
            ) or (
                existing.get("name", "")
                if isinstance(existing, dict)
                else ""
            )

            price = (
                item.get("price")
                if isinstance(item, dict)
                else None
            )

            try:
                if price is None:
                    price = (
                        existing.get("price", 0)
                        if isinstance(
                            existing,
                            dict,
                        )
                        else 0
                    )

                price = float(price)
            except (TypeError, ValueError):
                price = 0.0

            cart["items"][product_key] = {
                "name": name,
                "qty": qty,
                "price": price,
                "list_price": float(
                    item.get(
                        "list_price",
                        existing.get(
                            "list_price",
                            price,
                        ),
                    )
                    if isinstance(item, dict)
                    else existing.get(
                        "list_price",
                        price,
                    )
                ),
                "discount_type": str(
                    item.get(
                        "discount_type",
                        existing.get(
                            "discount_type",
                            "none",
                        ),
                    )
                    if isinstance(item, dict)
                    else existing.get(
                        "discount_type",
                        "none",
                    )
                ),
                "discount_value": float(
                    item.get(
                        "discount_value",
                        existing.get(
                            "discount_value",
                            0,
                        ),
                    )
                    if isinstance(item, dict)
                    else existing.get(
                        "discount_value",
                        0,
                    )
                ),
            }

        session["cart"] = cart

        return redirect(
            request.referrer
            or url_for("sales")
        )

    # ===== SALES POS API START =====

    def _sales_pos_cart_payload():
        cart = cart_get()
        items = []

        for product_id, item in cart.get("items", {}).items():
            qty = float(item.get("qty") or 0)
            price = float(item.get("price") or 0)

            list_price = float(
                item.get(
                    "list_price",
                    price,
                )
            )

            discount_type = str(
                item.get(
                    "discount_type",
                    "none",
                )
            )

            discount_value = float(
                item.get(
                    "discount_value",
                    0,
                )
            )

            items.append({
                "product_id": int(product_id),
                "name": str(item.get("name") or ""),
                "qty": qty,
                "price": price,
                "list_price": list_price,
                "discount_type": discount_type,
                "discount_value": discount_value,
                "discount_total": (
                    qty
                    * max(
                        0.0,
                        list_price - price,
                    )
                ),
                "line_total": qty * price,
            })

        return {
            "ok": True,
            "items": items,
            "item_count": len(items),
            "qty_total": sum(
                float(item["qty"])
                for item in items
            ),
            "cart_total": cart_total(cart),
        }

    @app.route("/sales/api/cart", methods=["GET"])
    @login_required
    def sales_api_cart():
        from flask import jsonify

        return jsonify(_sales_pos_cart_payload())

    @app.route("/sales/api/products", methods=["GET"])
    @login_required
    def sales_api_products():
        from flask import jsonify

        init_db()

        barcode = (
            request.args.get("barcode")
            or ""
        ).strip()

        if barcode:
            if len(barcode) > 128:
                return jsonify({
                    "ok": False,
                    "error": "Shtrix-kod juda uzun",
                    "products": [],
                }), 400

            user_id = parse_int(
                str(
                    session.get("user_id")
                    or "0"
                )
            )

            user = q1(
                """
                SELECT tenant_id
                FROM users
                WHERE id=?
                """,
                (user_id,),
            )

            tenant_id = (
                int(user["tenant_id"] or 0)
                if user
                else 0
            )

            if tenant_id <= 0:
                return jsonify({
                    "ok": False,
                    "error": (
                        "Foydalanuvchi tenant "
                        "aniqlanmadi"
                    ),
                    "products": [],
                }), 403

            product = q1(
                """
                SELECT
                    p.id,
                    p.name,
                    p.category_id,
                    p.sell_price_default_uzs
                        AS sell_default,
                    COALESCE(
                        p.stock_qty,
                        0
                    ) AS qty
                FROM product_barcodes pb
                JOIN products p
                  ON p.id=pb.product_id
                 AND p.tenant_id=pb.tenant_id
                WHERE pb.tenant_id=?
                  AND pb.barcode=?
                  AND p.is_active=1
                LIMIT 1
                """,
                (
                    tenant_id,
                    barcode,
                ),
            )

            products = []

            if product:
                products.append({
                    "id": int(
                        product["id"]
                    ),
                    "name": str(
                        product["name"]
                    ),
                    "category_id": int(
                        product["category_id"]
                    ),
                    "sell_default": float(
                        product["sell_default"]
                        or 0
                    ),
                    "qty": float(
                        product["qty"]
                        or 0
                    ),
                })

            return jsonify({
                "ok": True,
                "products": products,
            })

        category_id = parse_int(
            request.args.get("category_id") or "0"
        )

        if category_id <= 0:
            return jsonify({
                "ok": True,
                "products": [],
            })

        products = q("""
            SELECT
                p.id,
                p.name,
                p.sell_price_default_uzs AS sell_default,
                COALESCE(p.stock_qty, 0) AS qty
            FROM products p
            WHERE p.is_active=1
              AND p.category_id=?
            ORDER BY p.name
        """, (category_id,))

        return jsonify({
            "ok": True,
            "products": [
                {
                    "id": int(product["id"]),
                    "name": str(product["name"]),
                    "sell_default": float(
                        product["sell_default"] or 0
                    ),
                    "qty": float(product["qty"] or 0),
                }
                for product in products
            ],
        })

    # ===== SALES POS API END =====
