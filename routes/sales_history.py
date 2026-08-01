import sqlite3
from datetime import date, timedelta
from flask import render_template, request, session, redirect, url_for


def register_sales_history(
    app,
    *,
    db_path: str,
):

    @app.route("/sales/history")
    def sales_history():
        if not session.get("user_id"):
            return redirect(url_for("login"))

        today = date.today()
        default_from = (today - timedelta(days=30)).isoformat()
        default_to = today.isoformat()

        from_date = (request.args.get("from") or default_from).strip()
        to_date = (request.args.get("to") or default_to).strip()

        con = sqlite3.connect(db_path)
        cur = con.cursor()

        params = [from_date, to_date]
        agent_filter = ""

        if session.get("role") == "agent":
            agent_filter = " AND s.agent_id = ?"
            params.append(session.get("user_id"))

        sales_sql = f"""
        SELECT s.id,
               s.created_at,
               s.total_sell_uzs
        FROM sales s
        WHERE DATE(s.created_at) BETWEEN ? AND ?
        {agent_filter}
        ORDER BY s.id DESC
        LIMIT 200
        """
        sales_rows = cur.execute(sales_sql, params).fetchall()

        items_sql = """
        SELECT si.sale_id,
               p.name AS product_name,
               si.qty,
               si.sell_price_uzs
        FROM sale_items si
        LEFT JOIN products p ON p.id = si.product_id
        WHERE si.sale_id = ?
        ORDER BY si.id ASC
        """

        sales = []
        for (sid, created_at, total_sell_uzs) in sales_rows:
            its = cur.execute(items_sql, (sid,)).fetchall()

            items = []
            for (_sale_id, product_name, qty, sell_price_uzs) in its:
                qty = qty or 0
                sell_price_uzs = sell_price_uzs or 0
                items.append({
                    "product_name": product_name or "",
                    "qty": qty,
                    "price_uzs": sell_price_uzs,
                    "line_total": qty * sell_price_uzs
                })

            computed_total = sum((it.get("line_total") or 0) for it in items)
            sales.append({
                "id": sid,
                "created_at": created_at,
                "total_uzs": (total_sell_uzs or 0) or computed_total,
                "items": items
            })

        period_total = sum((x.get("total_uzs") or 0) for x in sales)
        sales_count = len(sales)
        con.close()

        return render_template(
            "sales_history.html",
            sales=sales,
            from_date=from_date,
            to_date=to_date,
            period_total=period_total,
            sales_count=sales_count,
        )
