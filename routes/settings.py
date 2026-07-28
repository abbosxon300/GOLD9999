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
    url_for,
)
from werkzeug.security import generate_password_hash


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
    login_required,
    admin_required,
):
    APP_NAME = app_name
    BACKUP_DIR = backup_dir
    DB_PATH = db_path

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
        name = (request.form.get("name") or "").strip()
        sort_order = parse_int(request.form.get("sort_order") or "100", 100)
        if not name:
            flash("Kategoriya nomi shart", "danger")
            return redirect(url_for("settings_categories"))
        try:
            exec_sql("INSERT INTO categories(name, sort_order, is_active) VALUES(?,?,1)", (name, sort_order))
            flash("Kategoriya qo‘shildi ✅", "success")
        except sqlite3.IntegrityError:
            flash("Bu nomli kategoriya bor", "danger")
        return redirect(url_for("settings_categories"))

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
        exec_sql("UPDATE categories SET is_active=? WHERE id=?", (new_val, cat_id))
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

        exec_sql(
            """
            UPDATE categories
            SET name=?, sort_order=?
            WHERE id=?
            """,
            (name, sort_order, cat_id),
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
        name = (request.form.get("name") or "").strip()
        category_id = parse_int(request.form.get("category_id") or "0")
        sell_default = parse_float(request.form.get("sell_price_default_uzs") or "")
        if not name or category_id <= 0:
            flash("Nomi va kategoriya shart", "danger")
            return redirect(url_for("settings_products"))
        if sell_default is None or sell_default <= 0:
            flash("Default sotuv narxi shart (so‘m)", "danger")
            return redirect(url_for("settings_products"))
        try:
            exec_sql("""
              INSERT INTO products(name, category_id, sell_price_default_uzs, is_active)
              VALUES(?,?,?,1)
            """, (name, category_id, float(sell_default)))
            flash("Mahsulot qo‘shildi ✅", "success")
        except sqlite3.IntegrityError:
            flash("Bu nom band", "danger")
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
        exec_sql("UPDATE products SET is_active=? WHERE id=?", (new_val, product_id))
        flash("O‘zgardi ✅", "success")
        return redirect(url_for("settings_products"))

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
