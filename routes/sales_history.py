import sqlite3
from datetime import date, datetime, timedelta

from flask import (
    redirect,
    render_template,
    request,
    session,
    url_for,
)


def _money(value):
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0

    return f"{amount:,.0f}".replace(",", " ")


def _qty(value):
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return "0"

    if amount.is_integer():
        return str(int(amount))

    return (
        f"{amount:,.3f}"
        .rstrip("0")
        .rstrip(".")
        .replace(",", " ")
    )


def _datetime_display(value):
    if not value:
        return "-"

    raw = str(value).strip()

    try:
        dt = datetime.fromisoformat(raw)
        return dt.strftime("%d.%m.%Y • %H:%M")
    except ValueError:
        return raw


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
        default_from = (
            today - timedelta(days=30)
        ).isoformat()
        default_to = today.isoformat()

        from_date = (
            request.args.get("from")
            or default_from
        ).strip()

        to_date = (
            request.args.get("to")
            or default_to
        ).strip()

        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row

        params = [from_date, to_date]
        agent_filter = ""

        if session.get("role") == "agent":
            agent_filter = " AND s.agent_id = ?"
            params.append(session.get("user_id"))

        sales_rows = con.execute(
            f"""
            SELECT
                s.id,
                s.created_at,
                s.total_sell_uzs,
                COALESCE(
                    SUM(
                        CASE
                            WHEN sp.payment_method='CASH'
                            THEN sp.amount_uzs
                            ELSE 0
                        END
                    ),
                    0
                ) AS cash_uzs,
                COALESCE(
                    SUM(
                        CASE
                            WHEN sp.payment_method='CLICK'
                            THEN sp.amount_uzs
                            ELSE 0
                        END
                    ),
                    0
                ) AS click_uzs,
                COUNT(sp.id) AS payment_rows
            FROM sales s
            LEFT JOIN sale_payments sp
              ON sp.sale_id = s.id
            WHERE DATE(s.created_at)
                  BETWEEN ? AND ?
            {agent_filter}
            GROUP BY
                s.id,
                s.created_at,
                s.total_sell_uzs
            ORDER BY s.id DESC
            LIMIT 200
            """,
            params,
        ).fetchall()

        items_sql = """
            SELECT
                si.sale_id,
                p.name AS product_name,
                si.qty,
                si.sell_price_uzs,
                si.sell_total_uzs
            FROM sale_items si
            LEFT JOIN products p
              ON p.id = si.product_id
            WHERE si.sale_id = ?
            ORDER BY si.id ASC
        """

        sales = []

        period_total = 0.0
        period_cash = 0.0
        period_click = 0.0

        for row in sales_rows:
            sid = row["id"]

            item_rows = con.execute(
                items_sql,
                (sid,),
            ).fetchall()

            items = []

            for item in item_rows:
                qty_value = float(
                    item["qty"] or 0
                )
                price_value = float(
                    item["sell_price_uzs"] or 0
                )

                stored_line_total = float(
                    item["sell_total_uzs"] or 0
                )

                line_total = (
                    stored_line_total
                    if stored_line_total
                    else qty_value * price_value
                )

                items.append({
                    "product_name": (
                        item["product_name"] or ""
                    ),
                    "qty": qty_value,
                    "qty_fmt": _qty(qty_value),
                    "price_uzs": price_value,
                    "price_fmt": _money(price_value),
                    "line_total": line_total,
                    "line_total_fmt": _money(
                        line_total
                    ),
                })

            computed_total = sum(
                item["line_total"]
                for item in items
            )

            total_uzs = float(
                row["total_sell_uzs"] or 0
            )

            if not total_uzs:
                total_uzs = computed_total

            cash_uzs = float(
                row["cash_uzs"] or 0
            )
            click_uzs = float(
                row["click_uzs"] or 0
            )
            payment_rows = int(
                row["payment_rows"] or 0
            )

            if payment_rows == 0:
                payment_type = "LEGACY"
                payment_label = "Eski sotuv"
            elif cash_uzs > 0 and click_uzs > 0:
                payment_type = "MIXED"
                payment_label = "Aralash"
            elif click_uzs > 0:
                payment_type = "CLICK"
                payment_label = "Click"
            else:
                payment_type = "CASH"
                payment_label = "Naqd"

            period_total += total_uzs

            if payment_rows:
                period_cash += cash_uzs
                period_click += click_uzs

            sales.append({
                "id": sid,
                "created_at": row["created_at"],
                "created_at_fmt": (
                    _datetime_display(
                        row["created_at"]
                    )
                ),
                "total_uzs": total_uzs,
                "total_fmt": _money(total_uzs),
                "cash_uzs": cash_uzs,
                "cash_fmt": _money(cash_uzs),
                "click_uzs": click_uzs,
                "click_fmt": _money(click_uzs),
                "payment_rows": payment_rows,
                "payment_type": payment_type,
                "payment_label": payment_label,
                "items": items,
            })

        con.close()

        return render_template(
            "sales_history.html",
            sales=sales,
            from_date=from_date,
            to_date=to_date,
            sales_count=len(sales),
            period_total=period_total,
            period_total_fmt=_money(
                period_total
            ),
            period_cash_fmt=_money(
                period_cash
            ),
            period_click_fmt=_money(
                period_click
            ),
        )
