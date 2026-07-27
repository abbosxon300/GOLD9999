from __future__ import annotations
import sys

# STARTUP_MARKER: 2026-02-22T19:32:14
import os, sqlite3, zipfile, shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
from datetime import datetime, date
from functools import wraps
from typing import Optional, Dict, Any, List, Tuple

from flask import Flask, g, render_template, request, redirect, url_for, flash, session, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from services.sales_helpers import (
    cart_add,
    cart_clear,
    cart_get,
    cart_remove,
    cart_set,
    cart_total,
    product_avg_cost as _product_avg_cost,
    product_qty as _product_qty,
)
# =========================
# Inventory helpers
# =========================

APP_NAME = "Gold 9999"

# --- routes registration ---
try:
    from routes.sales_history import register_sales_history
except Exception as e:
    register_sales_history = None

try:
    from routes.auth import register_auth_routes
except Exception:
    register_auth_routes = None

try:
    from routes.kirim import register_kirim_routes
except Exception:
    register_kirim_routes = None

try:
    from routes.kassa import register_kassa_routes
except Exception:
    register_kassa_routes = None

try:
    from routes.kpi import register_kpi_routes
except Exception:
    register_kpi_routes = None

try:
    from routes.sales import register_sales_routes
except Exception:
    register_sales_routes = None
# --- /routes registration ---
DB_PATH = os.path.join(BASE_DIR, "data.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")


# === DASHBOARD HELPERS ===
import os, sqlite3

def _db_path():
    # project folderda data.db bor
    return os.path.join(os.path.dirname(__file__), "data.db")

def _tables(conn):
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

def _cols(conn, table):
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    except Exception:
        return []

def _sum_if(conn, table, col):
    try:
        return float(conn.execute(f"SELECT COALESCE(SUM({col}),0) FROM {table}").fetchone()[0] or 0)
    except Exception:
        return 0.0

def _sum_first_match(conn, table_names, col_candidates):
    # table_names: ["sales", "orders", ...]
    # col_candidates: ["total_uzs", "jami_uzs", ...]
    existing_tables = set(_tables(conn))
    for t in table_names:
        if t in existing_tables:
            cols = set(_cols(conn, t))
            for c in col_candidates:
                if c in cols:
                    return _sum_if(conn, t, c)
    return 0.0

def _sum_in_out(conn, table, amount_cols=("amount","summa","amount_uzs","summa_uzs","uzs"), type_cols=("type","move_type","io","direction")):
    # Umumiy kassa hisoblash: IN - OUT
    cols = set(_cols(conn, table))
    amt = next((c for c in amount_cols if c in cols), None)
    typ = next((c for c in type_cols if c in cols), None)
    if not amt:
        return 0.0
    if not typ:
        # type yo'q bo'lsa, oddiy SUM
        return _sum_if(conn, table, amt)

    # type bo'lsa: "IN"/"OUT" yoki "kirim"/"chiqim" ehtimoli
    try:
        rows = conn.execute(f"SELECT {typ}, {amt} FROM {table}").fetchall()
        total = 0.0
        for t, a in rows:
            t = (t or "").strip().upper()
            a = float(a or 0)
            if t in ("IN", "+", "KIRIM", "KIRIMI", "COME", "DEBIT"):
                total += a
            elif t in ("OUT", "-", "CHIQIM", "EXPENSE", "CREDIT"):
                total -= a
            else:
                # noma'lum bo'lsa qo'shib yuboramiz
                total += a
        return total
    except Exception:
        return 0.0
# === END DASHBOARD HELPERS ===

app = Flask(__name__, template_folder="templates", static_folder="static")

@app.template_filter("fmt0")
def fmt0_filter(v):
    try:
        return f"{float(v or 0):,.0f}".replace(",", " ")
    except Exception:
        return "0"

# Register extra routes
register_sales_history(app)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "GOLD9999_CHANGE_ME_2026")


# ---------------- DB helpers ----------------


def _ensure_cash_move_for_sale(conn, sale_id: int):
    """
    Sotuv yakunlanganda cash_moves ga avtomatik IN yozish (dublikat yo‘q).
    cash_moves.sale_id unique bo‘lgani uchun bir sotuv uchun 1 marta yoziladi.
    """
    try:
        cur = conn.cursor()

        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cash_moves'")
        if not cur.fetchone():
            return

        # sale_id ustuni (eski DBlar uchun)
        try:
            cols = [r[1] for r in cur.execute("PRAGMA table_info(cash_moves)").fetchall()]
            if "sale_id" not in cols:
                cur.execute("ALTER TABLE cash_moves ADD COLUMN sale_id INTEGER")
        except Exception:
            pass

        # unique index (oddiy index ham dublikatni ushlaydi, NULL bo‘lsa ham)
        try:
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_cash_moves_sale_id ON cash_moves(sale_id)")
        except Exception:
            pass

        # dublikat tekshiruv
        try:
            cur.execute("SELECT 1 FROM cash_moves WHERE sale_id=? LIMIT 1", (sale_id,))
            if cur.fetchone():
                return
        except Exception:
            return

        # sales jadvalidan summani topamiz
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sales'")
        if not cur.fetchone():
            return

        sales_cols = [r[1] for r in cur.execute("PRAGMA table_info(sales)").fetchall()]
        amount_col = None
        for cand in ["total_sell_uzs","total_uzs","jami_uzs","total","jami","sum_uzs","summa_uzs","amount_uzs","amount"]:
            if cand in sales_cols:
                amount_col = cand
                break
        if not amount_col:
            return

        row = cur.execute(f"SELECT {amount_col} FROM sales WHERE id=?", (sale_id,)).fetchone()
        if not row:
            return

        try:
            amount = float(row[0] or 0)
        except Exception:
            amount = 0.0
        if amount <= 0:
            return

        try:
            from datetime import date
            move_date = date.today().isoformat()
        except Exception:
            move_date = None

        cash_cols = [r[1] for r in cur.execute("PRAGMA table_info(cash_moves)").fetchall()]
        has_move_date = "move_date" in cash_cols
        has_sale_id = "sale_id" in cash_cols
        note = f"Auto sale #{sale_id}"

        if has_move_date and has_sale_id:
            cur.execute(
                "INSERT INTO cash_moves(move_date, direction, amount_uzs, note, sale_id) VALUES (?,?,?,?,?)",
                (move_date, "IN", amount, note, sale_id)
            )
        elif has_move_date:
            cur.execute(
                "INSERT INTO cash_moves(move_date, direction, amount_uzs, note) VALUES (?,?,?,?)",
                (move_date, "IN", amount, note)
            )
        elif has_sale_id:
            cur.execute(
                "INSERT INTO cash_moves(direction, amount_uzs, note, sale_id) VALUES (?,?,?,?)",
                ("IN", amount, note, sale_id)
            )
        else:
            cur.execute(
                "INSERT INTO cash_moves(direction, amount_uzs, note) VALUES (?,?,?)",
                ("IN", amount, note)
            )

        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return
def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA temp_store = MEMORY;")
        conn.execute("PRAGMA cache_size = -20000;")

        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        g.db = conn
    return g.db

@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def q1(sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
    cur = get_db().execute(sql, params)
    row = cur.fetchone()
    cur.close()
    return row

def q(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    cur = get_db().execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return rows

def exec_sql(sql: str, params: tuple = ()) -> int:
    db = get_db()
    cur = db.execute(sql, params)
    db.commit()
    last_id = cur.lastrowid
    # Auto: sotuv yakunlanganda kassaga IN yozish
    # Auto: sotuv yakunlanganda kassaga IN yozish (faqat sales INSERT bo‘lsa)
    try:
        import re
        if re.search(r"\binsert\s+into\s+sales\b", sql, re.IGNORECASE):
            _ensure_cash_move_for_sale(db, last_id)
    except Exception:
        pass

    cur.close()
    return last_id


def init_db() -> None:
    os.makedirs(BACKUP_DIR, exist_ok=True)

    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      full_name TEXT,
      role TEXT NOT NULL DEFAULT 'admin', -- admin / agent
      is_active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS categories(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT UNIQUE NOT NULL,
      sort_order INTEGER NOT NULL DEFAULT 100,
      is_active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS products(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT UNIQUE NOT NULL,
      category_id INTEGER NOT NULL,
      sell_price_default_uzs REAL NOT NULL DEFAULT 0,
      stock_qty REAL NOT NULL DEFAULT 0,
      is_active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE RESTRICT
    );

    -- Kirim: batch (FIFO)
    CREATE TABLE IF NOT EXISTS batches(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      product_id INTEGER NOT NULL,
      batch_date TEXT NOT NULL,
      qty_in REAL NOT NULL,
      qty_left REAL NOT NULL,
      unit_cost_uzs REAL NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT
    );

    CREATE INDEX IF NOT EXISTS idx_batches_product ON batches(product_id);

    -- Sotuv (faqat so'm)
    CREATE TABLE IF NOT EXISTS sales(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      sale_date TEXT NOT NULL,
      agent_id INTEGER,
      total_sell_uzs REAL NOT NULL DEFAULT 0,
      total_cost_uzs REAL NOT NULL DEFAULT 0,
      total_profit_uzs REAL NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(agent_id) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS sale_items(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      sale_id INTEGER NOT NULL,
      product_id INTEGER NOT NULL,
      qty REAL NOT NULL,
      sell_price_uzs REAL NOT NULL,
      sell_total_uzs REAL NOT NULL,
      cost_total_uzs REAL NOT NULL,
      profit_uzs REAL NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(sale_id) REFERENCES sales(id) ON DELETE CASCADE,
      FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT
    );

    CREATE TABLE IF NOT EXISTS sale_batch_consumptions(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      sale_item_id INTEGER NOT NULL,
      batch_id INTEGER NOT NULL,
      qty_used REAL NOT NULL,
      unit_cost_uzs REAL NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(sale_item_id) REFERENCES sale_items(id) ON DELETE CASCADE,
      FOREIGN KEY(batch_id) REFERENCES batches(id) ON DELETE RESTRICT
    );
    -- Inventory moves (NO FIFO): IN/OUT movements
    CREATE TABLE IF NOT EXISTS inventory_moves(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      move_date TEXT NOT NULL,
      move_type TEXT NOT NULL, -- IN / OUT
      product_id INTEGER NOT NULL,
      qty REAL NOT NULL,
      unit_cost_uzs REAL NOT NULL DEFAULT 0,
      note TEXT,
      source_type TEXT,
      source_id INTEGER,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT
    );

    CREATE INDEX IF NOT EXISTS idx_inv_moves_prod_date
      ON inventory_moves(product_id, move_date);

    CREATE INDEX IF NOT EXISTS idx_inv_moves_type_date
      ON inventory_moves(move_type, move_date);


    """)

    # --- cash_moves: sale_id + unique index (auto kassa IN uchun) ---
    try:
        cur = db.cursor()
        try:
            cols = [r[1] for r in cur.execute("PRAGMA table_info(cash_moves)").fetchall()]
            if "sale_id" not in cols:
                cur.execute("ALTER TABLE cash_moves ADD COLUMN sale_id INTEGER")
        except Exception:
            pass
        try:
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_cash_moves_sale_id ON cash_moves(sale_id)")
        except Exception:
            pass
    except Exception:
        pass
    db.commit()

    # Ensure products.stock_qty exists for older DBs
    try:
        db.execute(
            "ALTER TABLE products "
            "ADD COLUMN stock_qty REAL NOT NULL DEFAULT 0"
        )
        db.commit()
    except Exception:
        # column already exists (or older sqlite limitations)
        pass

    # inventory_moves source identity migration
    inventory_move_columns = {
        row[1]
        for row in db.execute(
            "PRAGMA table_info(inventory_moves)"
        ).fetchall()
    }

    if "source_type" not in inventory_move_columns:
        db.execute(
            "ALTER TABLE inventory_moves "
            "ADD COLUMN source_type TEXT"
        )

    if "source_id" not in inventory_move_columns:
        db.execute(
            "ALTER TABLE inventory_moves "
            "ADD COLUMN source_id INTEGER"
        )

    db.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_inv_moves_source
        ON inventory_moves(source_type, source_id)
        WHERE source_type IS NOT NULL
          AND source_id IS NOT NULL
    """)
    db.commit()

    # default admin
    admin = q1("SELECT id FROM users WHERE username='admin'")
    if not admin:
        exec_sql(
            "INSERT INTO users(username, password_hash, full_name, role) VALUES(?,?,?,?)",
            ("admin", generate_password_hash("admin123"), "Administrator", "admin")
        )


def parse_float(val: str) -> Optional[float]:
    s = (val or "").strip().replace(" ", "").replace(",", ".")
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None

def parse_int(val: str, default: int = 0) -> int:
    try:
        return int((val or "").strip())
    except Exception:
        return default


def product_qty(product_id: int) -> float:
    return _product_qty(get_db, product_id)


def product_avg_cost(product_id: int) -> float:
    return _product_avg_cost(get_db, product_id)


# ---------------- Auth ----------------
def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


# === CART HELPERS ===





# === END CART HELPERS ===


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Bu bo‘lim faqat admin uchun", "danger")
            return redirect(url_for("home"))
        return fn(*args, **kwargs)
    return wrapper


def cash_in(conn, amount_uzs, note=""):
    try:
        a = float(amount_uzs or 0)
    except Exception:
        a = 0.0
    if a == 0:
        return
    conn.execute(
        "INSERT INTO cash_moves(direction, amount_uzs, note) VALUES (?,?,?)",
        ("IN", a, note or "")
    )




def _fmt_uzs(x):
    try:
        return f"{float(x or 0):,.0f}".replace(",", " ")
    except Exception:
        return str(x)
def build_home_context():
    if session.get("role") == "agent":
        return redirect(url_for("sales"))
    # Bosh panel: Kassa / Umumiy sotuv / Umumiy to‘lov
    init_db()
    import sqlite3
    conn = sqlite3.connect(_db_path())
    try:
        # 1) Umumiy sotuv (jadval/ustun nomlari turlicha bo‘lishi mumkin)
        sales_total_uzs = _sum_first_match(
            conn,
            table_names=["sales","sale_orders","orders","sales_history","sales_log"],
            col_candidates=["total_sell_uzs","total_uzs","jami_uzs","total","jami","sum_uzs","summa_uzs","amount_uzs","amount"]
        )

        # 2) Umumiy to‘lov
        payments_total_uzs = _sum_first_match(
            conn,
            table_names=["payments","client_payments","payment_moves","cash_payments","ledger","money_moves"],
            col_candidates=["total_sell_uzs","amount_uzs","summa_uzs","amount","summa","paid_uzs","tolov_uzs"]
        )

        # 3) Kassa (professional): faqat cash_moves IN-OUT saldosi

        kassa_uzs = 0.0

        if "cash_moves" in set(_tables(conn)):

            kassa_uzs = _sum_in_out(conn, "cash_moves")

    finally:
        conn.close()

    # === formats for dashboard cards ===

    kassa_fmt = _fmt_uzs(kassa_uzs)

    sales_total_fmt = _fmt_uzs(sales_total_uzs)

    paid_total_fmt = _fmt_uzs(payments_total_uzs)

    return {
        "kassa_fmt": kassa_fmt,
        "sales_total_fmt": sales_total_fmt,
        "paid_total_fmt": paid_total_fmt,
    }

if register_auth_routes:
    register_auth_routes(
        app,
        app_name=APP_NAME,
        init_db=init_db,
        q1=q1,
        login_required=login_required,
        build_home_context=build_home_context,
    )







if register_kpi_routes:
    register_kpi_routes(
        app,
        app_name=APP_NAME,
        init_db=init_db,
        get_db=get_db,
        q=q,
        q1=q1,
        parse_int=parse_int,
        parse_float=parse_float,
        login_required=login_required,
        admin_required=admin_required,
    )


if register_kassa_routes:
    register_kassa_routes(
        app,
        init_db=init_db,
        get_db=get_db,
        login_required=login_required,
        admin_required=admin_required,
        fmt_uzs=_fmt_uzs,
    )


if register_kirim_routes:
    register_kirim_routes(
        app,
        init_db=init_db,
        get_db=get_db,
        q=q,
        q1=q1,
        parse_int=parse_int,
        parse_float=parse_float,
        login_required=login_required,
        admin_required=admin_required,
    )


if register_sales_routes:
    register_sales_routes(
        app,
        init_db=init_db,
        get_db=get_db,
        q=q,
        q1=q1,
        parse_int=parse_int,
        parse_float=parse_float,
        fmt0_filter=fmt0_filter,
        login_required=login_required,
        cart_get=cart_get,
        cart_total=cart_total,
        product_qty=product_qty,
        product_avg_cost=product_avg_cost,
    )


# ---- Sozlamalar: Kategoriya ----
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


# ---- Sozlamalar: Mahsulot ----
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


# ---- Sozlamalar: Xodimlar ----
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


# ---- Sozlamalar: Backup / Restore ----
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


# =========================
# Kassa: Edit / Delete
# =========================


# =========================
# /Kassa: Edit / Delete
# =========================


# Auto DB init on import (init sahifa yo'q, methods=["GET", "POST"])
with app.app_context():
    init_db()









# --- KPI -> Category -> Kirim (no FIFO) ---
# --- /KPI -> Kirim ---




# =========================
# Sales History (sold list)
# =========================


# (sales_history moved to routes/sales_history.py)
