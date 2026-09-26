from datetime import date, timedelta

from flask import (
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from services.business_writes import (
    business_transaction,
    create_cash_move,
    delete_cash_move,
    get_cash_move,
    update_cash_move,
    update_cash_move_note,
)


def _money(value):
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0

    return f"{amount:,.0f}".replace(",", " ")


def _date_range():
    today = date.today()
    default_from = today - timedelta(days=30)

    from_date = (
        request.args.get("from")
        or default_from.isoformat()
    ).strip()

    to_date = (
        request.args.get("to")
        or today.isoformat()
    ).strip()

    return from_date, to_date


def _ledger_context(
    db,
    *,
    table,
    from_date,
    to_date,
):
    # New supplier payments are visible only to the owner's business.
    owner = db.execute("SELECT tenant_id FROM users WHERE id=?", (session.get("user_id"),)).fetchone()
    tenant_id = owner[0] if owner else None
    link_column = "cash_move_id" if table == "cash_moves" else "click_move_id"
    conditions = [
        f"NOT EXISTS(SELECT 1 FROM purchase_payments pp WHERE pp.{link_column}={table}.id AND (? IS NULL OR pp.tenant_id<>?))",
        f"NOT EXISTS(SELECT 1 FROM supplier_payments sp WHERE sp.{link_column}={table}.id AND (? IS NULL OR sp.tenant_id<>?))",
    ]
    params = [tenant_id, tenant_id, tenant_id, tenant_id]

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

    totals = db.execute(
        f"""
        SELECT
            COUNT(*) AS moves_count,
            COALESCE(SUM(
                CASE
                    WHEN direction='IN'
                    THEN amount_uzs
                    ELSE 0
                END
            ), 0) AS total_in,
            COALESCE(SUM(
                CASE
                    WHEN direction='OUT'
                    THEN amount_uzs
                    ELSE 0
                END
            ), 0) AS total_out
        FROM {table}
        {where_sql}
        """,
        params,
    ).fetchone()

    rows = db.execute(
        f"""
        SELECT
            id,
            move_date,
            direction,
            amount_uzs,
            note,
            sale_id,
            created_at
        FROM {table}
        {where_sql}
        ORDER BY
            move_date DESC,
            id DESC
        LIMIT 200
        """,
        params,
    ).fetchall()

    total_in = float(totals["total_in"] or 0)
    total_out = float(totals["total_out"] or 0)

    return {
        "rows": rows,
        "moves_count": int(
            totals["moves_count"] or 0
        ),
        "total_in": total_in,
        "total_out": total_out,
        "balance": total_in - total_out,
    }


def register_kassa_routes(
    app,
    *,
    init_db,
    get_db,
    login_required,
    admin_required,
    fmt_uzs,
):
    @app.route(
        "/kassa",
        methods=["GET", "POST"],
    )
    @login_required
    @admin_required
    def kassa():
        init_db()
        db = get_db()

        if request.method == "POST":
            direction = (
                request.form.get("direction")
                or "IN"
            ).strip().upper()

            amount_raw = (
                request.form.get("amount_uzs")
                or ""
            ).replace(" ", "").replace(",", "").strip()

            note = (
                request.form.get("note")
                or ""
            ).strip()

            if direction not in ("IN", "OUT"):
                flash(
                    "Direction xato (IN/OUT)",
                    "danger",
                )
                return redirect(
                    url_for("kassa")
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
                    url_for("kassa")
                )

            try:
                with business_transaction(db) as tx:
                    create_cash_move(
                        tx,
                        move_date=(
                            date.today().isoformat()
                        ),
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

            return redirect(
                url_for("kassa")
            )

        from_date, to_date = _date_range()

        context = _ledger_context(
            db,
            table="cash_moves",
            from_date=from_date,
            to_date=to_date,
        )

        return render_template(
            "kassa.html",
            page_title="Naqd kassa",
            page_subtitle=(
                "Naqd pul tushumlari va chiqimlari"
            ),
            ledger_type="cash",
            allow_manual=True,
            from_date=from_date,
            to_date=to_date,
            money=_money,
            **context,
        )

    @app.route(
        "/click-kassa",
        methods=["GET"],
    )
    @login_required
    @admin_required
    def click_kassa():
        init_db()
        db = get_db()

        from_date, to_date = _date_range()

        context = _ledger_context(
            db,
            table="click_moves",
            from_date=from_date,
            to_date=to_date,
        )

        return render_template(
            "kassa.html",
            page_title="Click kassa",
            page_subtitle=(
                "Click orqali tushgan "
                "to‘lovlar tarixi"
            ),
            ledger_type="click",
            allow_manual=False,
            from_date=from_date,
            to_date=to_date,
            money=_money,
            **context,
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
            flash(
                "Topilmadi",
                "danger",
            )
            return redirect(
                url_for("kassa")
            )

        purchase_payment = db.execute(
            "SELECT purchase_id,tenant_id FROM purchase_payments WHERE cash_move_id=?", (move_id,)
        ).fetchone()
        if purchase_payment:
            owner = db.execute("SELECT tenant_id FROM users WHERE id=?", (session.get("user_id"),)).fetchone()
            if not owner or owner[0] != purchase_payment["tenant_id"]:
                flash("Topilmadi", "danger")
                return redirect(url_for("kassa"))
            flash("Bu to‘lov kirim hujjatiga bog‘langan.", "warning")
            return redirect(url_for("purchase_detail", purchase_id=purchase_payment["purchase_id"]))

        supplier_payment = db.execute(
            "SELECT supplier_id,tenant_id FROM supplier_payments WHERE cash_move_id=?",
            (move_id,),
        ).fetchone()
        if supplier_payment:
            owner = db.execute(
                "SELECT tenant_id FROM users WHERE id=?",
                (session.get("user_id"),),
            ).fetchone()
            if not owner or owner[0] != supplier_payment["tenant_id"]:
                flash("Topilmadi", "danger")
                return redirect(url_for("kassa"))
            flash("Bu to‘lov yetkazib beruvchi hisobiga bog‘langan.", "warning")
            return redirect(
                url_for(
                    "purchase_supplier_detail",
                    supplier_id=supplier_payment["supplier_id"],
                )
            )

        if row.sale_id is not None:
            flash(
                "Auto sale yozuvini "
                "o‘chirib bo‘lmaydi",
                "danger",
            )
            return redirect(
                url_for("kassa")
            )

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

        return redirect(
            url_for("kassa")
        )

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
            flash(
                "Topilmadi",
                "danger",
            )
            return redirect(
                url_for("kassa")
            )

        purchase_payment = db.execute(
            "SELECT purchase_id,tenant_id FROM purchase_payments WHERE cash_move_id=?", (move_id,)
        ).fetchone()
        if purchase_payment:
            owner = db.execute("SELECT tenant_id FROM users WHERE id=?", (session.get("user_id"),)).fetchone()
            if not owner or owner[0] != purchase_payment["tenant_id"]:
                flash("Topilmadi", "danger")
                return redirect(url_for("kassa"))
            flash("Bu to‘lov kirim hujjatiga bog‘langan.", "warning")
            return redirect(url_for("purchase_detail", purchase_id=purchase_payment["purchase_id"]))

        supplier_payment = db.execute(
            "SELECT supplier_id,tenant_id FROM supplier_payments WHERE cash_move_id=?",
            (move_id,),
        ).fetchone()
        if supplier_payment:
            owner = db.execute(
                "SELECT tenant_id FROM users WHERE id=?",
                (session.get("user_id"),),
            ).fetchone()
            if not owner or owner[0] != supplier_payment["tenant_id"]:
                flash("Topilmadi", "danger")
                return redirect(url_for("kassa"))
            flash("Bu to‘lov yetkazib beruvchi hisobiga bog‘langan.", "warning")
            return redirect(
                url_for(
                    "purchase_supplier_detail",
                    supplier_id=supplier_payment["supplier_id"],
                )
            )

        is_auto_sale = (
            row.sale_id is not None
        )

        if request.method == "POST":
            note = (
                request.form.get("note")
                or ""
            ).strip()

            try:
                if is_auto_sale:
                    with business_transaction(
                        db
                    ) as tx:
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

                    return redirect(
                        url_for("kassa")
                    )

                move_date = (
                    request.form.get(
                        "move_date"
                    )
                    or ""
                ).strip() or row.move_date

                direction = (
                    request.form.get(
                        "direction"
                    )
                    or row.direction
                    or "IN"
                ).strip().upper()

                amount_raw = (
                    request.form.get(
                        "amount_uzs"
                    )
                    or ""
                ).replace(
                    " ",
                    "",
                ).replace(
                    ",",
                    "",
                ).strip()

                if direction not in (
                    "IN",
                    "OUT",
                ):
                    flash(
                        "Direction xato "
                        "(IN/OUT)",
                        "danger",
                    )
                    return redirect(
                        url_for(
                            "kassa_edit",
                            move_id=move_id,
                        )
                    )

                try:
                    amount = float(
                        amount_raw
                    )
                except (
                    TypeError,
                    ValueError,
                ):
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

                with business_transaction(
                    db
                ) as tx:
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

                return redirect(
                    url_for("kassa")
                )

            except Exception as exc:
                flash(
                    str(exc),
                    "danger",
                )
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
