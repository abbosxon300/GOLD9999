import os
import sqlite3
from datetime import date, timedelta
from flask import render_template, request

def register_sales_history(app):

    @app.route("/sales/history")
    def sales_history():
        today = date.today()
        default_from = (today - timedelta(days=30)).isoformat()
        default_to = today.isoformat()

        from_date = (request.args.get("from") or default_from).strip()
        to_date = (request.args.get("to") or default_to).strip()

        base_dir = os.path.dirname(os.path.dirname(__file__))
        db_path = os.path.join(base_dir, "data.db")

        con = sqlite3.connect(db_path)
        cur = con.cursor()

        sales_sql = """
        SELECT s.id,
               s.created_at,
               s.total_sell_uzs
        FROM sales s
        WHERE DATE(s.created_at) BETWEEN ? AND ?
        ORDER BY s.id DESC
        LIMIT 200
        """
        sales_rows = cur.execute(sales_sql, (from_date, to_date)).fetchall()

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

