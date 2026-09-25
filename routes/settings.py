import sqlite3

import os
import shutil
import zipfile
from datetime import datetime
from typing import List

from flask import (
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.security import generate_password_hash

from services.business_writes.master_data import (
    create_category,
    create_product,
    set_category_active,
    set_product_active,
    update_category,
    update_product,
)


from services.business_writes.product_barcodes import (
    add_product_barcode,
    generate_product_barcode,
    delete_product_barcode,
    list_product_barcodes,
)


def register_settings_routes(
    app,
    *,
    app_name,
    backup_dir,
    db_path,
    init_db,
    q,
    q1,
    exec_sql,
    parse_int,
    parse_float,
    login_required,
    admin_required,
):
    APP_NAME = app_name
    BACKUP_DIR = backup_dir
    DB_PATH = db_path


    def _current_tenant_id() -> int:
        user_id = parse_int(
            str(
                session.get("user_id")
                or "0"
            )
        )

        if user_id <= 0:
            raise RuntimeError(
                "Login user aniqlanmadi"
            )

        row = q1(
            """
            SELECT
                u.tenant_id
            FROM users u
            JOIN tenants t
              ON t.id=u.tenant_id
            WHERE u.id=?
              AND u.is_active=1
              AND t.is_active=1
            """,
            (user_id,),
        )

        tenant_id = (
            int(row["tenant_id"] or 0)
            if row
            else 0
        )

        if tenant_id <= 0:
            raise RuntimeError(
                "Faol tenant aniqlanmadi"
            )

        return tenant_id

    @app.route("/settings/categories")
    @login_required
    @admin_required
    def settings_categories():
        init_db()
        rows = q("SELECT * FROM categories ORDER BY sort_order, id")
        return render_template("settings_categories.html", rows=rows)

    @app.route("/settings/categories/add", methods=["POST"])
    @login_required
    @admin_required
    def settings_categories_add():
        init_db()
        tenant_id = _current_tenant_id()

        name = (
            request.form.get("name")
            or ""
        ).strip()

        if not name:
            flash(
                "Kategoriya nomi shart",
                "danger",
            )
            return redirect(
                url_for("settings_categories")
            )

        next_sort_row = q1(
            """
            SELECT
                COALESCE(
                    MAX(sort_order),
                    0
                ) + 1 AS next_sort
            FROM categories
            WHERE tenant_id=?
            """,
            (tenant_id,),
        )

        sort_order = int(
            next_sort_row["next_sort"]
        )

        try:
            create_category(
                name=name,
                sort_order=sort_order,
                tenant_id=tenant_id,
            )

            flash(
                "Kategoriya qo‘shildi ✅",
                "success",
            )

        except sqlite3.IntegrityError:
            flash(
                "Bu nomli kategoriya bor",
                "danger",
            )

        return redirect(
            url_for("settings_categories")
        )

    @app.route("/settings/categories/toggle/<int:cat_id>", methods=["POST"])
    @login_required
    @admin_required
    def settings_categories_toggle(cat_id: int):
        init_db()
        row = q1("SELECT is_active FROM categories WHERE id=?", (cat_id,))
        if not row:
            flash("Topilmadi", "danger")
            return redirect(url_for("settings_categories"))
        new_val = 0 if int(row["is_active"]) == 1 else 1
        set_category_active(
            cat_id,
            is_active=new_val,
        )
        flash("O‘zgardi ✅", "success")
        return redirect(url_for("settings_categories"))


    @app.route(
        "/settings/categories/edit/<int:cat_id>",
        methods=["POST"],
    )
    @login_required
    @admin_required
    def settings_categories_edit(cat_id: int):
        row = q1(
            "SELECT id FROM categories WHERE id=?",
            (cat_id,),
        )
        if not row:
            flash("Kategoriya topilmadi", "danger")
            return redirect(url_for("settings_categories"))

        name = (request.form.get("name") or "").strip()
        sort_raw = (request.form.get("sort_order") or "").strip()

        if not name:
            flash("Kategoriya nomi shart", "danger")
            return redirect(url_for("settings_categories"))

        try:
            sort_order = int(sort_raw)
        except (TypeError, ValueError):
            flash("Tartib butun son bo‘lishi kerak", "danger")
            return redirect(url_for("settings_categories"))

        if sort_order < 0:
            flash("Tartib manfiy bo‘lishi mumkin emas", "danger")
            return redirect(url_for("settings_categories"))

        duplicate = q1(
            """
            SELECT id
            FROM categories
            WHERE lower(trim(name))=lower(trim(?))
              AND id<>?
            LIMIT 1
            """,
            (name, cat_id),
        )
        if duplicate:
            flash("Bu nomli kategoriya mavjud", "danger")
            return redirect(url_for("settings_categories"))

        update_category(
            cat_id,
            name=name,
            sort_order=sort_order,
        )

        flash("Kategoriya yangilandi ✅", "success")
        return redirect(url_for("settings_categories"))


    @app.route("/settings/products")
    @login_required
    @admin_required
    def settings_products():
        init_db()
        cats = q("SELECT id, name FROM categories WHERE is_active=1 ORDER BY sort_order, id")
        rows = q("""
          SELECT p.*, c.name AS category_name
          FROM products p
          JOIN categories c ON c.id=p.category_id
          ORDER BY p.id DESC
        """)
        return render_template("settings_products.html", cats=cats, rows=rows)

    @app.route("/settings/products/add", methods=["POST"])
    @login_required
    @admin_required
    def settings_products_add():
        init_db()
        tenant_id = _current_tenant_id()

        name = (
            request.form.get("name")
            or ""
        ).strip()

        category_id = parse_int(
            request.form.get("category_id")
            or "0"
        )

        sell_default = parse_float(
            request.form.get(
                "sell_price_default_uzs"
            )
            or ""
        )

        if (
            not name
            or category_id <= 0
        ):
            flash(
                "Nomi va kategoriya shart",
                "danger",
            )
            return redirect(
                url_for("settings_products")
            )

        if (
            sell_default is None
            or sell_default <= 0
        ):
            flash(
                "Default sotuv narxi shart (so‘m)",
                "danger",
            )
            return redirect(
                url_for("settings_products")
            )

        category = q1(
            """
            SELECT id
            FROM categories
            WHERE id=?
              AND tenant_id=?
              AND is_active=1
            """,
            (
                category_id,
                tenant_id,
            ),
        )

        if not category:
            flash(
                "Faol kategoriya topilmadi",
                "danger",
            )
            return redirect(
                url_for("settings_products")
            )

        try:
            create_product(
                name=name,
                category_id=category_id,
                sell_price_default_uzs=float(
                    sell_default
                ),
            )

            flash(
                "Mahsulot qo‘shildi ✅",
                "success",
            )

        except sqlite3.IntegrityError:
            flash(
                "Bu nom band",
                "danger",
            )

        return redirect(
            url_for("settings_products")
        )

    @app.route(
        "/settings/products/edit/<int:product_id>",
        methods=["POST"],
    )
    @login_required
    @admin_required
    def settings_products_edit(product_id: int):
        init_db()

        product = q1(
            "SELECT id FROM products WHERE id=?",
            (product_id,),
        )
        if not product:
            flash("Mahsulot topilmadi", "danger")
            return redirect(url_for("settings_products"))

        name = (request.form.get("name") or "").strip()
        category_id = parse_int(
            request.form.get("category_id") or "0"
        )
        sell_price = parse_float(
            request.form.get(
                "sell_price_default_uzs"
            ) or ""
        )

        if not name or category_id <= 0:
            flash(
                "Mahsulot nomi va kategoriya shart",
                "danger",
            )
            return redirect(url_for("settings_products"))

        if sell_price is None or sell_price <= 0:
            flash(
                "Sotuv narxi musbat son bo‘lishi kerak",
                "danger",
            )
            return redirect(url_for("settings_products"))

        category = q1(
            """
            SELECT id
            FROM categories
            WHERE id=?
              AND is_active=1
            """,
            (category_id,),
        )
        if not category:
            flash(
                "Faol kategoriya topilmadi",
                "danger",
            )
            return redirect(url_for("settings_products"))

        duplicate = q1(
            """
            SELECT id
            FROM products
            WHERE lower(trim(name))=lower(trim(?))
              AND id<>?
            LIMIT 1
            """,
            (name, product_id),
        )
        if duplicate:
            flash("Bu nomli mahsulot mavjud", "danger")
            return redirect(url_for("settings_products"))

        update_product(
            product_id,
            name=name,
            category_id=category_id,
            sell_price_default_uzs=float(
                sell_price
            ),
        )

        flash("Mahsulot yangilandi ✅", "success")
        return redirect(url_for("settings_products"))


    @app.route("/settings/products/toggle/<int:product_id>", methods=["POST"])
    @login_required
    @admin_required
    def settings_products_toggle(product_id: int):
        init_db()
        row = q1("SELECT is_active FROM products WHERE id=?", (product_id,))
        if not row:
            flash("Topilmadi", "danger")
            return redirect(url_for("settings_products"))
        new_val = 0 if int(row["is_active"]) == 1 else 1
        set_product_active(
            product_id,
            is_active=new_val,
        )
        flash("O‘zgardi ✅", "success")
        return redirect(url_for("settings_products"))



    def _barcode_product(product_id):
        from flask import abort

        product = q1(
            "SELECT id, name, tenant_id FROM products "
            "WHERE id=? AND tenant_id=?",
            (product_id, _current_tenant_id()),
        )
        if product is None:
            abort(404)
        return product

    @app.route(
        "/settings/products/<int:product_id>/barcodes/generate",
        methods=["POST"],
    )
    @login_required
    @admin_required
    def settings_product_barcode_generate(product_id):
        init_db()
        _barcode_product(product_id)
        try:
            generate_product_barcode(product_id)
        except (
            ValueError, LookupError, RuntimeError, sqlite3.IntegrityError
        ) as exc:
            flash(str(exc), "danger")
        else:
            flash("Shtrix-kod tayyor. Uni chop etishingiz mumkin.", "success")
        return redirect(url_for(
            "settings_product_barcodes", product_id=product_id
        ))

    @app.route(
        "/settings/products/<int:product_id>"
        "/barcodes/<int:barcode_id>/print"
    )
    @login_required
    @admin_required
    def settings_product_barcode_print(product_id, barcode_id):
        from flask import abort
        from services.barcode_labels import ean13_bits

        init_db()
        product = _barcode_product(product_id)
        row = q1(
            "SELECT barcode FROM product_barcodes "
            "WHERE id=? AND product_id=? AND tenant_id=?",
            (barcode_id, product_id, product["tenant_id"]),
        )
        if row is None:
            abort(404)

        try:
            copies = int(request.args.get("copies", "1"))
        except (TypeError, ValueError):
            abort(400)
        if not 1 <= copies <= 500:
            abort(400)

        sizes = {
            "58x40": (58, 40),
            "50x30": (50, 30),
            "40x30": (40, 30),
        }
        size = request.args.get("size", "58x40")
        if size not in sizes:
            abort(400)

        try:
            bits = ean13_bits(row["barcode"])
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for(
                "settings_product_barcodes", product_id=product_id
            ))

        width, height = sizes[size]
        return render_template(
            "product_barcode_print.html",
            product=product,
            barcode=row["barcode"],
            bits=bits,
            copies=copies,
            width=width,
            height=height,
        )

    @app.route(
        "/settings/products/<int:product_id>/barcodes"
    )
    @login_required
    @admin_required
    def settings_product_barcodes(
        product_id: int,
    ):
        init_db()
        _barcode_product(product_id)

        product = q1(
            """
            SELECT
                id,
                name,
                tenant_id
            FROM products
            WHERE id=?
            """,
            (product_id,),
        )

        if not product:
            flash(
                "Mahsulot topilmadi",
                "danger",
            )
            return redirect(
                url_for("settings_products")
            )

        barcodes = list_product_barcodes(
            product_id
        )

        return render_template(
            "settings_product_barcodes.html",
            product=product,
            barcodes=barcodes,
        )


    @app.route(
        "/settings/products/<int:product_id>"
        "/barcodes/add",
        methods=["POST"],
    )
    @login_required
    @admin_required
    def settings_product_barcode_add(
        product_id: int,
    ):
        init_db()
        _barcode_product(product_id)

        barcode = (
            request.form.get("barcode")
            or ""
        ).strip()

        try:
            add_product_barcode(
                product_id,
                barcode=barcode,
            )
        except (
            ValueError,
            LookupError,
            RuntimeError,
            sqlite3.IntegrityError,
        ) as exc:
            flash(
                str(exc),
                "danger",
            )
        else:
            flash(
                "Shtrix-kod qo‘shildi ✅",
                "success",
            )

        return redirect(
            url_for(
                "settings_product_barcodes",
                product_id=product_id,
            )
        )


    @app.route(
        "/settings/products/<int:product_id>"
        "/barcodes/<int:barcode_id>/delete",
        methods=["POST"],
    )
    @login_required
    @admin_required
    def settings_product_barcode_delete(
        product_id: int,
        barcode_id: int,
    ):
        init_db()
        _barcode_product(product_id)

        try:
            delete_product_barcode(
                product_id,
                barcode_id,
            )
        except (
            LookupError,
            RuntimeError,
        ) as exc:
            flash(
                str(exc),
                "danger",
            )
        else:
            flash(
                "Shtrix-kod o‘chirildi ✅",
                "success",
            )

        return redirect(
            url_for(
                "settings_product_barcodes",
                product_id=product_id,
            )
        )


    @app.route("/settings/agents")
    @login_required
    def settings_agents_old_redirect():
        return redirect(url_for("settings_agents"))

    @app.route("/settings/xodimlar")
    @login_required
    @admin_required
    def settings_agents():
        init_db()
        rows = q("SELECT id, username, full_name, role, is_active FROM users ORDER BY id DESC")
        return render_template("settings_agents.html", rows=rows)

    @app.route("/settings/xodimlar/add", methods=["POST"])
    @login_required
    @admin_required
    def settings_agents_add():
        init_db()
        username = (request.form.get("username") or "").strip()
        full_name = (request.form.get("full_name") or "").strip()
        role = (request.form.get("role") or "agent").strip().lower()
        password = request.form.get("password") or ""
        if not username or not password:
            flash("Username va parol shart", "danger")
            return redirect(url_for("settings_agents"))
        try:
            exec_sql(
                "INSERT INTO users(username, password_hash, full_name, role, is_active) VALUES(?,?,?,?,1)",
                (username, generate_password_hash(password), full_name, role)
            )
            flash("Xodim qo‘shildi ✅", "success")
        except sqlite3.IntegrityError:
            flash("Bu username band", "danger")
        return redirect(url_for("settings_agents"))

    @app.route("/settings/xodimlar/toggle/<int:user_id>", methods=["POST"])
    @login_required
    @admin_required
    def settings_agents_toggle(user_id: int):
        init_db()
        row = q1("SELECT is_active FROM users WHERE id=?", (user_id,))
        if not row:
            flash("Topilmadi", "danger")
            return redirect(url_for("settings_agents"))
        new_val = 0 if int(row["is_active"]) == 1 else 1
        exec_sql("UPDATE users SET is_active=? WHERE id=?", (new_val, user_id))
        flash("O‘zgardi ✅", "success")
        return redirect(url_for("settings_agents"))

    @app.route("/settings/printer")
    @login_required
    @admin_required
    def settings_printer():
        return render_template(
            "settings_printer.html"
        )


    def list_backups() -> List[str]:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        files = [f for f in os.listdir(BACKUP_DIR) if f.endswith(".zip")]
        files.sort(reverse=True)
        return files

    @app.route("/settings/backup")
    @login_required
    @admin_required
    def settings_backup():
        init_db()
        return render_template("settings_backup.html", backups=list_backups())

    @app.route("/settings/backup/create", methods=["POST"])
    @login_required
    @admin_required
    def backup_create():
        init_db()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"backup_{ts}.zip"
        path = os.path.join(BACKUP_DIR, name)

        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            if os.path.exists(DB_PATH):
                z.write(DB_PATH, arcname="data.db")

        flash(f"Backup yaratildi ✅ ({name})", "success")
        return redirect(url_for("settings_backup"))

    @app.route("/settings/backup/download/<path:filename>")
    @login_required
    @admin_required
    def backup_download(filename: str):
        path = os.path.join(BACKUP_DIR, filename)
        if not os.path.exists(path):
            flash("Backup topilmadi", "danger")
            return redirect(url_for("settings_backup"))
        return send_file(path, as_attachment=True, download_name=filename)

    @app.route("/settings/backup/restore", methods=["POST"])
    @login_required
    @admin_required
    def backup_restore():
        init_db()
        filename = (request.form.get("filename") or "").strip()
        path = os.path.join(BACKUP_DIR, filename)
        if not filename or not os.path.exists(path):
            flash("Backup topilmadi", "danger")
            return redirect(url_for("settings_backup"))

        # current DB safety copy
        if os.path.exists(DB_PATH):
            shutil.copy2(DB_PATH, DB_PATH + ".before_restore")

        try:
            with zipfile.ZipFile(path, "r") as z:
                if "data.db" not in z.namelist():
                    raise ValueError("Zip ichida data.db yo‘q")
                z.extract("data.db", path=BASE_DIR)
            flash("Restore bo‘ldi ✅ Endi Web -> Reload bosing.", "success")
        except Exception as e:
            flash(f"Restore xato: {e}", "danger")

        return redirect(url_for("settings_backup"))
