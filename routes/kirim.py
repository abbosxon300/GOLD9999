from datetime import date

from flask import (
    flash,
    redirect,
    render_template,
    request,
    url_for,
)


def register_kirim_routes(
    app,
    *,
    init_db,
    get_db,
    q,
    q1,
    parse_int,
    parse_float,
    login_required,
    admin_required,
):
    @app.route("/kirim")
    @login_required
    @admin_required
    def kirim():
        init_db()

        categories = q("""
            SELECT *
            FROM categories
            WHERE is_active=1
            ORDER BY sort_order, id
        """)

        rows = []

        for category in categories:
            row = q1("""
                SELECT
                    COALESCE(
                        SUM(p.stock_qty),
                        0
                    ) AS qty
                FROM products p
                WHERE p.category_id=?
                  AND p.is_active=1
            """, (category["id"],))

            rows.append({
                **dict(category),
                "qty": (
                    float(row["qty"])
                    if row else 0.0
                ),
            })

        return render_template(
            "kirim.html",
            kpis=rows,
        )

    @app.route("/kirim/<int:category_id>")
    @login_required
    @admin_required
    def kirim_detail(category_id: int):
        init_db()

        category = q1("""
            SELECT *
            FROM categories
            WHERE id=?
        """, (category_id,))

        if not category:
            flash(
                "Kategoriya topilmadi",
                "danger",
            )
            return redirect(url_for("kirim"))

        rows = q("""
            SELECT
                p.id AS product_id,
                p.name AS product_name,
                p.sell_price_default_uzs
                    AS sell_default,
                COALESCE(p.stock_qty, 0)
                    AS qty
            FROM products p
            WHERE p.category_id=?
              AND p.is_active=1
            ORDER BY p.name
        """, (category_id,))

        return render_template(
            "kirim_detail.html",
            category=category,
            rows=rows,
        )

    @app.route(
        "/kirim/add",
        methods=["POST"],
    )
    @login_required
    @admin_required
    def kirim_add():
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
        unit_cost = parse_float(
            request.form.get(
                "unit_cost_uzs"
            ) or ""
        )

        if product_id <= 0:
            flash(
                "Mahsulot tanlanmadi",
                "danger",
            )
            return redirect(
                url_for(
                    "kirim_detail",
                    category_id=category_id,
                )
            )

        if qty is None or qty <= 0:
            flash(
                "Miqdor noto‘g‘ri",
                "danger",
            )
            return redirect(
                url_for(
                    "kirim_detail",
                    category_id=category_id,
                )
            )

        if unit_cost is None or unit_cost <= 0:
            flash(
                "Tannarx noto‘g‘ri",
                "danger",
            )
            return redirect(
                url_for(
                    "kirim_detail",
                    category_id=category_id,
                )
            )

        db = get_db()

        try:
            db.execute("BEGIN")

            product = db.execute("""
                SELECT id
                FROM products
                WHERE id=?
                  AND category_id=?
                  AND is_active=1
            """, (
                product_id,
                category_id,
            )).fetchone()

            if not product:
                raise ValueError(
                    "Mahsulot topilmadi "
                    "yoki nofaol"
                )

            move_date = date.today().isoformat()

            db.execute("""
                INSERT INTO inventory_moves(
                    move_date,
                    move_type,
                    product_id,
                    qty,
                    unit_cost_uzs,
                    note,
                    source_type,
                    source_id
                )
                VALUES(
                    ?, ?, ?, ?, ?, ?,
                    NULL, NULL
                )
            """, (
                move_date,
                "IN",
                int(product_id),
                float(qty),
                float(unit_cost),
                "Oddiy kirim",
            ))

            db.execute("""
                UPDATE products
                SET stock_qty=
                    COALESCE(stock_qty, 0) + ?
                WHERE id=?
            """, (
                float(qty),
                int(product_id),
            ))

            db.commit()

            flash(
                "Kirim saqlandi ✅",
                "success",
            )

        except Exception as exc:
            db.rollback()
            flash(str(exc), "danger")

        return redirect(
            url_for(
                "kirim_detail",
                category_id=category_id,
            )
        )
