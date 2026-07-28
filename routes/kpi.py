from datetime import date

from flask import (
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from datetime import datetime


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
    @app.route("/kpi")
    @login_required
    @admin_required
    def kpi():
        init_db()
        cats = q("""
            SELECT id, name, sort_order
            FROM categories
            WHERE is_active=1
            ORDER BY sort_order, name
        """)
        rows = q("""
            SELECT
              c.id AS category_id,
              COALESCE(SUM(CASE WHEN m.move_type='IN' THEN m.qty ELSE 0 END),0) -
              COALESCE(SUM(CASE WHEN m.move_type='OUT' THEN m.qty ELSE 0 END),0) AS stock_qty
            FROM categories c
            JOIN products p ON p.category_id=c.id AND p.is_active=1
            LEFT JOIN inventory_moves m ON m.product_id=p.id
            WHERE c.is_active=1
            GROUP BY c.id
            ORDER BY c.sort_order, c.name
        """)
        stock_map = {int(r["category_id"]): float(r["stock_qty"] or 0) for r in rows}
        return render_template("kpi.html", cats=cats, stock_map=stock_map, app_name=app_name)

    @app.route("/kpi/<int:category_id>")
    @login_required
    @admin_required
    def kpi_category(category_id: int):
        init_db()
        cat = q1("SELECT * FROM categories WHERE id=? AND is_active=1", (category_id,))
        if not cat:
            flash("Kategoriya topilmadi", "danger")
            return redirect(url_for("kpi"))

        prod_rows = q("""
            SELECT
              p.id AS product_id,
              p.name AS product_name,
              COALESCE(SUM(CASE WHEN m.move_type='IN' THEN m.qty ELSE 0 END),0) -
              COALESCE(SUM(CASE WHEN m.move_type='OUT' THEN m.qty ELSE 0 END),0) AS stock_qty
            FROM products p
            LEFT JOIN inventory_moves m ON m.product_id=p.id
            WHERE p.category_id=? AND p.is_active=1
            GROUP BY p.id
            ORDER BY p.name
        """, (category_id,))
        return render_template("kpi_detail.html", cat=cat, prod_rows=prod_rows, app_name=app_name)

    @app.route("/kpi/<int:category_id>/kirim", methods=["GET", "POST"])
    @login_required
    @admin_required
    def kpi_kirim(category_id: int):
        init_db()

        cat = q1("SELECT * FROM categories WHERE id=? AND is_active=1", (category_id,))
        if not cat:
            flash("Kategoriya topilmadi", "danger")
            return redirect(url_for("kpi"))

        products = q("""
            SELECT id, name,
                   COALESCE(stock_qty,0) AS stock_qty,
                   COALESCE(sell_price_default_uzs,0) AS sell_price_default_uzs
            FROM products
            WHERE is_active=1 AND category_id=?
            ORDER BY name
        """, (category_id,))

        if request.method == "POST":

            product_id = parse_int(request.form.get("product_id"))

            qty = parse_float(request.form.get("qty")) or 0.0

            unit_cost_uzs = (parse_float(request.form.get("cost_uzs")) or parse_float(request.form.get("unit_cost_uzs")) or 0.0)

            move_date = (request.form.get("move_date") or "").strip() or datetime.now().strftime("%Y-%m-%d")

            note = (request.form.get("note") or "").strip()


            if product_id <= 0 or qty <= 0:
                flash(
                    "Mahsulot va miqdorni to‘g‘ri kiriting",
                    "danger",
                )
                return redirect(
                    url_for(
                        "kpi_kirim",
                        category_id=category_id,
                    )
                )

            if unit_cost_uzs <= 0:
                flash(
                    "Tannarx musbat son bo‘lishi kerak",
                    "danger",
                )
                return redirect(
                    url_for(
                        "kpi_kirim",
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
                    int(product_id),
                    int(category_id),
                )).fetchone()

                if not product:
                    raise ValueError(
                        "Mahsulot topilmadi yoki nofaol"
                    )

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
                    VALUES(?,?,?,?,?,?,NULL,NULL)
                """, (
                    move_date,
                    "IN",
                    int(product_id),
                    float(qty),
                    float(unit_cost_uzs),
                    note or "KPI kirim",
                ))

                db.execute("""
                    UPDATE products
                    SET stock_qty=COALESCE(stock_qty, 0) + ?
                    WHERE id=?
                """, (
                    float(qty),
                    int(product_id),
                ))

                db.commit()
                flash("Kirim qo‘shildi ✅", "success")

            except Exception as exc:
                db.rollback()
                flash(str(exc), "danger")

            return redirect(url_for("kpi"))
        recent_moves = q(
            """
            SELECT
                m.id,
                m.move_date,
                m.qty,
                m.unit_cost_uzs,
                m.note,
                p.name AS product_name
            FROM inventory_moves m
            JOIN products p
              ON p.id=m.product_id
            WHERE m.move_type='IN'
              AND p.category_id=?
            ORDER BY m.id DESC
            LIMIT 10
            """,
            (category_id,),
        )

        return render_template(
            "kpi_kirim.html",
            category=cat,
            products=products,
            recent_moves=recent_moves,
            today=datetime.now().strftime("%Y-%m-%d"),
            app_name=app_name,
        )
