from datetime import date
from services.business_writes import (
    business_transaction,
    create_cash_move,
    delete_cash_move,
    get_cash_move,
    update_cash_move,
    update_cash_move_note,
)

from flask import (
    flash,
    redirect,
    render_template,
    request,
    url_for,
)


def register_kassa_routes(
    app,
    *,
    init_db,
    get_db,
    login_required,
    admin_required,
    fmt_uzs,
):
    @app.route("/kassa", methods=["GET", "POST"])
    @login_required
    @admin_required
    def kassa():
        init_db()
        db = get_db()

        if request.method == "POST":
            direction = (
                request.form.get("direction") or "IN"
            ).strip().upper()

            amount_raw = (
                request.form.get("amount_uzs") or ""
            ).replace(" ", "").replace(",", "").strip()

            note = (
                request.form.get("note") or ""
            ).strip()

            if direction not in ("IN", "OUT"):
                flash(
                    "Direction xato (IN/OUT)",
                    "danger",
                )
                return redirect(url_for("kassa"))

            try:
                amount = float(amount_raw)
            except (TypeError, ValueError):
                amount = 0.0

            if amount <= 0:
                flash(
                    "Summa noto‘g‘ri",
                    "danger",
                )
                return redirect(url_for("kassa"))

            try:
                with business_transaction(db) as tx:
                    create_cash_move(
                        tx,
                        move_date=date.today().isoformat(),
                        direction=direction,
                        amount_uzs=amount,
                        note=note,
                    )

                flash(
                    "Kassa harakati saqlandi ✅",
                    "success",
                )

            except Exception as exc:
                flash(str(exc), "danger")

            return redirect(url_for("kassa"))

        from_date = (
            request.args.get("from") or ""
        ).strip()

        to_date = (
            request.args.get("to") or ""
        ).strip()

        conditions = []
        params = []

        if from_date:
            conditions.append("move_date >= ?")
            params.append(from_date)

        if to_date:
            conditions.append("move_date <= ?")
            params.append(to_date)

        where_sql = (
            " WHERE " + " AND ".join(conditions)
            if conditions
            else ""
        )

        balance = db.execute(f"""
            SELECT
                COALESCE(SUM(
                    CASE
                        WHEN direction='IN'
                        THEN amount_uzs
                        ELSE 0
                    END
                ), 0)
                -
                COALESCE(SUM(
                    CASE
                        WHEN direction='OUT'
                        THEN amount_uzs
                        ELSE 0
                    END
                ), 0)
            FROM cash_moves
            {where_sql}
        """, params).fetchone()[0] or 0

        rows = db.execute(f"""
            SELECT
                id,
                move_date,
                direction,
                amount_uzs,
                note,
                sale_id
            FROM cash_moves
            {where_sql}
            ORDER BY id DESC
            LIMIT 50
        """, params).fetchall()

        return render_template(
            "kassa.html",
            kassa_fmt=fmt_uzs(balance),
            rows=rows,
            from_date=from_date,
            to_date=to_date,
        )

    @app.route(
        "/kassa/delete/<int:move_id>",
        methods=["POST"],
    )
    @login_required
    @admin_required
    def kassa_delete(move_id: int):
        init_db()
        db = get_db()

        row = get_cash_move(
            db,
            move_id,
        )

        if row is None:
            flash("Topilmadi", "danger")
            return redirect(url_for("kassa"))

        if row.sale_id is not None:
            flash(
                "Auto sale yozuvini "
                "o‘chirib bo‘lmaydi",
                "danger",
            )
            return redirect(url_for("kassa"))

        try:
            with business_transaction(db) as tx:
                delete_cash_move(
                    tx,
                    move_id=move_id,
                )

            flash(
                "O‘chirildi ✅",
                "success",
            )

        except Exception as exc:
            flash(str(exc), "danger")

        return redirect(url_for("kassa"))

    @app.route(
        "/kassa/edit/<int:move_id>",
        methods=["GET", "POST"],
    )
    @login_required
    @admin_required
    def kassa_edit(move_id: int):
        init_db()
        db = get_db()

        row = get_cash_move(
            db,
            move_id,
        )

        if row is None:
            flash("Topilmadi", "danger")
            return redirect(url_for("kassa"))

        is_auto_sale = row.sale_id is not None

        if request.method == "POST":
            note = (
                request.form.get("note") or ""
            ).strip()

            try:
                if is_auto_sale:
                    with business_transaction(db) as tx:
                        update_cash_move_note(
                            tx,
                            move_id=move_id,
                            note=note,
                        )

                    flash(
                        "Saqlandi ✅ "
                        "(Auto sale: faqat izoh)",
                        "success",
                    )

                    return redirect(url_for("kassa"))

                move_date = (
                    request.form.get("move_date") or ""
                ).strip() or row.move_date

                direction = (
                    request.form.get("direction")
                    or row.direction
                    or "IN"
                ).strip().upper()

                amount_raw = (
                    request.form.get("amount_uzs") or ""
                ).replace(" ", "").replace(",", "").strip()

                if direction not in ("IN", "OUT"):
                    flash(
                        "Direction xato (IN/OUT)",
                        "danger",
                    )

                    return redirect(
                        url_for(
                            "kassa_edit",
                            move_id=move_id,
                        )
                    )

                try:
                    amount = float(amount_raw)
                except (TypeError, ValueError):
                    amount = 0.0

                if amount <= 0:
                    flash(
                        "Summa noto‘g‘ri",
                        "danger",
                    )

                    return redirect(
                        url_for(
                            "kassa_edit",
                            move_id=move_id,
                        )
                    )

                with business_transaction(db) as tx:
                    update_cash_move(
                        tx,
                        move_id=move_id,
                        move_date=move_date,
                        direction=direction,
                        amount_uzs=amount,
                        note=note,
                    )

                flash(
                    "Saqlandi ✅",
                    "success",
                )

                return redirect(url_for("kassa"))

            except Exception as exc:
                flash(str(exc), "danger")

                return redirect(
                    url_for(
                        "kassa_edit",
                        move_id=move_id,
                    )
                )

        return render_template(
            "kassa_edit.html",
            r=row,
            is_auto_sale=is_auto_sale,
        )
