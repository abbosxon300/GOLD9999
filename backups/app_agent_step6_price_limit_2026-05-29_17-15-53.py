from __future__ import annotations
import sys

# STARTUP_MARKER: 2026-02-22T19:32:14
import os, sqlite3, zipfile, shutil
from datetime import datetime, date
from functools import wraps
from typing import Optional, Dict, Any, List, Tuple

from flask import Flask, g, render_template, request, redirect, url_for, flash, session, send_file
from werkzeug.security import generate_password_hash, check_password_hash
# =========================
# Inventory helpers
# =========================
def product_qty(product_id: int) -> float:
    """
    Current stock for product_id from products.stock_qty (simple model).
    """
    con = get_db() if "get_db" in globals() else db()

    # products.stock_qty ustuni bo'lmasa ham (eski DB), 0 qaytaramiz
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(products)").fetchall()]
        if "stock_qty" not in cols:
            return 0.0
        row = con.execute("SELECT COALESCE(stock_qty,0) FROM products WHERE id=?", (product_id,)).fetchone()
        return float(row[0] if row else 0.0)
    except Exception:
        return 0.0

APP_NAME = "Gold 9999"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# --- routes registration ---
try:
    from routes.sales_history import register_sales_history
except Exception as e:
    register_sales_history = None
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
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT
    );

    CREATE INDEX IF NOT EXISTS idx_inv_moves_prod_date ON inventory_moves(product_id, move_date);
    CREATE INDEX IF NOT EXISTS idx_inv_moves_type_date ON inventory_moves(move_type, move_date);

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
        db.execute("ALTER TABLE products ADD COLUMN stock_qty REAL NOT NULL DEFAULT 0")
        db.commit()
    except Exception:
        # column already exists (or older sqlite limitations)
        pass

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


# ---------------- Auth ----------------
def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


# === CART HELPERS ===
def cart_get():
    """Cart format: {'items': {pid_str: {'qty': float, 'price': float(optional)}}}. Stored in session."""
    cart = session.get("cart")
    if not isinstance(cart, dict):
        cart = {"items": {}}
        session["cart"] = cart
        return cart

    if "items" not in cart or not isinstance(cart.get("items"), dict):
        # convert old format {pid: qty} -> {'items': {pid:{'qty':qty}}}
        items = {}
        for k, v in list(cart.items()):
            if k == "items":
                continue
            try:
                items[str(k)] = {"qty": float(v)}
            except Exception:
                pass
        cart = {"items": items}
        session["cart"] = cart
        return cart

    # normalize items
    cleaned = {}
    for pid, it in cart["items"].items():
        pid = str(pid)
        if isinstance(it, dict):
            try:
                qty = float(it.get("qty", 0))
            except Exception:
                qty = 0.0
            if qty > 0:
                cleaned[pid] = dict(it)
                cleaned[pid]["qty"] = qty
        else:
            try:
                qty = float(it)
                if qty > 0:
                    cleaned[pid] = {"qty": qty}
            except Exception:
                pass

    cart["items"] = cleaned
    session["cart"] = cart
    return cart

def cart_set(cart: dict):
    if not isinstance(cart, dict):
        cart = {"items": {}}
    if "items" not in cart or not isinstance(cart.get("items"), dict):
        cart = {"items": {}}
    session["cart"] = cart

def cart_clear():
    session["cart"] = {"items": {}}

def cart_add(product_id: int, qty: float = 1, price: float | None = None):
    cart = cart_get()
    pid = str(product_id)
    it = cart["items"].get(pid, {"qty": 0})
    try:
        it_qty = float(it.get("qty", 0)) if isinstance(it, dict) else float(it)
    except Exception:
        it_qty = 0.0
    it_qty += float(qty or 0)
    new_it = dict(it) if isinstance(it, dict) else {}
    new_it["qty"] = it_qty
    if price is not None:
        try:
            new_it["price"] = float(price)
        except Exception:
            pass
    if it_qty > 0:
        cart["items"][pid] = new_it
    else:
        cart["items"].pop(pid, None)
    cart_set(cart)
    return cart

def cart_remove(product_id: int):
    cart = cart_get()
    pid = str(product_id)
    cart["items"].pop(pid, None)
    cart_set(cart)
    return cart

def cart_total(cart: dict | None = None):
    """Return numeric total (sum qty*price if price exists, else 0)."""
    if cart is None:
        cart = cart_get()
    items = cart.get("items", {}) if isinstance(cart, dict) else {}
    total = 0.0
    for pid, it in items.items():
        if not isinstance(it, dict):
            continue
        try:
            qty = float(it.get("qty", 0))
        except Exception:
            qty = 0.0
        try:
            price = float(it.get("price", 0))
        except Exception:
            price = 0.0
        total += qty * price
    return total
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
@app.route("/login", methods=["GET","POST"], endpoint="login")

def login():
    init_db()
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        u = q1("SELECT * FROM users WHERE username=? AND is_active=1", (username,))
        if not u or not check_password_hash(u["password_hash"], password):
            flash("Login yoki parol xato", "danger")
            return redirect(url_for("login"))

        session["user_id"] = u["id"]
        session["username"] = u["username"]
        session["role"] = u["role"]
        session["full_name"] = u["full_name"] or u["username"]
        return redirect(url_for("home"))

    return render_template("login.html", app_name=APP_NAME)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))
@app.route("/")
@app.route("/home")
@login_required
def home():
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

    return render_template(

        "home.html",

        kassa_fmt=kassa_fmt,

        sales_total_fmt=sales_total_fmt,

        paid_total_fmt=paid_total_fmt,

    )


@app.route("/kassa", methods=["GET", "POST"])
@login_required
@admin_required
def kassa():
    init_db()
    import sqlite3
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        if request.method == "POST":
            direction = (request.form.get("direction") or "IN").strip().upper()
            amount_raw = (request.form.get("amount_uzs") or "").replace(" ", "").replace(",", "").strip()
            note = (request.form.get("note") or "").strip()

            if direction not in ("IN", "OUT"):
                flash("Direction xato (IN/OUT)", "danger")
                return redirect(url_for("kassa"))

            try:
                amount = float(amount_raw)
            except Exception:
                amount = 0.0

            if amount <= 0:
                flash("Summa noto‘g‘ri", "danger")
                return redirect(url_for("kassa"))

            from datetime import date



            move_date = date.today().isoformat()



            conn.execute(


                "INSERT INTO cash_moves(move_date, direction, amount_uzs, note) VALUES (?,?,?,?)",


                (move_date, direction, amount, note)


            )
            conn.commit()
            flash("Kassa harakati saqlandi ✅", "success")
            return redirect(url_for("kassa"))
        # filter (GET): from/to (YYYY-MM-DD)
        from_date = (request.args.get("from") or "").strip()
        to_date = (request.args.get("to") or "").strip()
        where = ""
        params = []
        if from_date and to_date:
            where = " WHERE move_date >= ? AND move_date <= ? "
            params = [from_date, to_date]
        elif from_date:
            where = " WHERE move_date >= ? "
            params = [from_date]
        elif to_date:
            where = " WHERE move_date <= ? "
            params = [to_date]

        # balans
        bal = conn.execute(f"""
              SELECT
                COALESCE(SUM(CASE WHEN direction='IN' THEN amount_uzs ELSE 0 END),0)
                -
                COALESCE(SUM(CASE WHEN direction='OUT' THEN amount_uzs ELSE 0 END),0)
              FROM cash_moves {where}
          """, params).fetchone()[0] or 0

        # rows (id + sale_id bilan)
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(cash_moves)").fetchall()]
        except Exception:
            cols = []
        if "sale_id" in cols:
            select_sql = f"SELECT id, move_date, direction, amount_uzs, note, sale_id FROM cash_moves {where} ORDER BY id DESC LIMIT 50"
        else:
            select_sql = f"SELECT id, move_date, direction, amount_uzs, note, NULL AS sale_id FROM cash_moves {where} ORDER BY id DESC LIMIT 50"

        rows = conn.execute(select_sql, params).fetchall()

    finally:
        conn.close()

    kassa_fmt = _fmt_uzs(bal)
    return render_template("kassa.html", kassa_fmt=kassa_fmt, rows=rows, from_date=from_date, to_date=to_date)

@app.route("/kirim")
@login_required
@admin_required
def kirim():
    init_db()
    cats = q("SELECT * FROM categories WHERE is_active=1 ORDER BY sort_order, id")
    kpis = []
    for c in cats:
        row = q1("""
          SELECT COALESCE(SUM(COALESCE(p.stock_qty,0)),0) AS qty
          FROM products p
          WHERE p.category_id=? AND p.is_active=1
        """, (c["id"],))
        kpis.append({"id": int(c["id"]), "name": c["name"], "qty": float(row["qty"]) if row else 0.0})
    return render_template("kirim.html", kpis=kpis)

@app.route("/kirim/<int:category_id>")
@login_required
@admin_required
def kirim_detail(category_id: int):
    init_db()
    cat = q1("SELECT * FROM categories WHERE id=?", (category_id,))
    if not cat:
        flash("Kategoriya topilmadi", "danger")
        return redirect(url_for("kirim"))

    rows = q("""
      SELECT
        p.id AS product_id,
        p.name AS product_name,
        p.sell_price_default_uzs AS sell_default,
        COALESCE(p.stock_qty,0) AS qty
      FROM products p
WHERE p.category_id=? AND p.is_active=1
      GROUP BY p.id, p.name, p.sell_price_default_uzs
      ORDER BY p.name
    """, (category_id,))
    return render_template("kirim_detail.html", category=cat, rows=rows)

@app.route("/kirim/add", methods=["POST"])
@login_required
@admin_required
def kirim_add():
    init_db()
    category_id = parse_int(request.form.get("category_id") or "0")
    product_id = parse_int(request.form.get("product_id") or "0")
    qty = parse_float(request.form.get("qty") or "")
    unit_cost = parse_float(request.form.get("unit_cost_uzs") or "")

    if product_id <= 0:
        flash("Mahsulot tanlanmadi", "danger")
        return redirect(url_for("kirim_detail", category_id=category_id))
    if qty is None or qty <= 0:
        flash("Miqdor noto‘g‘ri", "danger")
        return redirect(url_for("kirim_detail", category_id=category_id))
    if unit_cost is None or unit_cost <= 0:
        flash("Tannarx noto‘g‘ri", "danger")
        return redirect(url_for("kirim_detail", category_id=category_id))

    p = q1("SELECT id FROM products WHERE id=? AND is_active=1", (product_id,))
    if not p:
        flash("Mahsulot topilmadi yoki nofaol", "danger")
        return redirect(url_for("kirim_detail", category_id=category_id))
    exec_sql("UPDATE products SET stock_qty = COALESCE(stock_qty,0) + ? WHERE id=?", (float(qty), int(product_id)))

    flash("Kirim saqlandi ✅", "success")
    return redirect(url_for("kirim_detail", category_id=category_id))


# ---- Sotuv ----
@app.route("/sales", methods=["GET", "POST"])
@login_required
def sales():
    init_db()
    # Legacy GET action support: /sales?product_id=2&action=dec
    legacy_product_id = parse_int(request.args.get("product_id") or "0")
    legacy_action = (request.args.get("action") or "").strip()
    if legacy_product_id > 0 and legacy_action in ("inc", "dec", "del", "remove"):
        return sales_qty(legacy_product_id, legacy_action)

    cart = cart_get()

    cats = q("SELECT id, name FROM categories WHERE is_active=1 ORDER BY sort_order, id")
    cat_id = parse_int(request.args.get("category_id") or "0")
    if cat_id <= 0 and cats:
        cat_id = int(cats[0]["id"])

    products = []
    if cat_id > 0:
        products = q("""
          SELECT p.id, p.name,p.sell_price_default_uzs AS sell_default,COALESCE(p.stock_qty,0) AS qty
            FROM products p
            WHERE p.is_active=1 AND p.category_id=?
            GROUP BY p.id, p.name, p.sell_price_default_uzs, p.stock_qty
          ORDER BY p.name
        """, (cat_id,))

    cart_items = []
    for pid_str, it in cart["items"].items():
        cart_items.append({
            "product_id": int(pid_str),
            "name": it["name"],
            "qty": float(it["qty"]),
            "price": float(it["price"]),
            "line_total": float(it["qty"]) * float(it["price"]),
        })

    total = cart_total(cart)
    today = date.today().isoformat()

    if session.get("role") == "agent":
        sum_row = q1("""
          SELECT
            COALESCE(SUM(total_sell_uzs),0) AS sell,
            COALESCE(SUM(total_cost_uzs),0) AS cost,
            COALESCE(SUM(total_profit_uzs),0) AS profit
          FROM sales WHERE sale_date=? AND agent_id=?
        """, (today, session.get("user_id")))
    else:
        sum_row = q1("""
          SELECT
            COALESCE(SUM(total_sell_uzs),0) AS sell,
            COALESCE(SUM(total_cost_uzs),0) AS cost,
            COALESCE(SUM(total_profit_uzs),0) AS profit
          FROM sales WHERE sale_date=?
        """, (today,))
    s_sell = float(sum_row["sell"]) if sum_row else 0.0
    s_cost = float(sum_row["cost"]) if sum_row else 0.0
    s_profit = float(sum_row["profit"]) if sum_row else 0.0

    return render_template(
        "sales.html",
        cats=cats,
        selected_cat_id=cat_id,
        products=products,
        cart_items=cart_items,
        cart_total=total,
        today=today,
        sum_sell=s_sell,
        sum_cost=s_cost,
        sum_profit=s_profit,
    )

@app.route("/sales/add", methods=["POST"])
@login_required
def sales_add():
    init_db()
    category_id = parse_int(request.form.get("category_id") or "0")
    product_id = parse_int(request.form.get("product_id") or "0")
    qty = parse_float(request.form.get("qty") or "")
    price = parse_float(request.form.get("price_uzs") or "")

    if product_id <= 0:
        flash("Mahsulot tanlanmadi", "danger")
        return redirect(url_for("sales", category_id=category_id))
    if qty is None or qty <= 0:
        flash("Miqdor noto‘g‘ri", "danger")
        return redirect(url_for("sales", category_id=category_id))
    if price is None or price <= 0:
        flash("Narx noto‘g‘ri", "danger")
        return redirect(url_for("sales", category_id=category_id))

    p = q1("""
      SELECT p.id, p.name, p.sell_price_default_uzs
      FROM products p WHERE p.id=? AND p.is_active=1
    """, (product_id,))
    if not p:
        flash("Mahsulot topilmadi yoki nofaol", "danger")
        return redirect(url_for("sales", category_id=category_id))

    available = product_qty(product_id)
    cart = cart_get()
    existing = float(cart["items"].get(str(product_id), {}).get("qty", 0))
    if (available is not None) and (available + 1e-9 < (existing + float(qty))):
        flash(f"Qoldiq yetarli emas. Bor: {available:.2f}", "danger")
        return redirect(url_for("sales", category_id=category_id))

    if str(product_id) in cart["items"]:
        cart["items"][str(product_id)]["qty"] = existing + float(qty)
        cart["items"][str(product_id)]["price"] = float(price)
    else:
        cart["items"][str(product_id)] = {"name": p["name"], "qty": float(qty), "price": float(price)}

    session["cart"] = cart
    flash("Savatga qo‘shildi ✅", "success")
    return redirect(url_for("sales", category_id=category_id))

@app.route("/sales/remove/<int:product_id>", methods=["POST"])
@login_required
def sales_remove(product_id: int):
    cart = cart_get()
    cart["items"].pop(str(product_id), None)
    session["cart"] = cart
    return redirect(url_for("home"))

@app.route("/sales/clear", methods=["POST"])
@login_required
def sales_clear():
    session["cart"] = {"items": {}}
    flash("Savat tozalandi", "success")
    return redirect(url_for("home"))

@app.route("/sales/checkout", methods=["POST"])
@login_required
def sales_checkout():
    init_db()
    cart = cart_get()
    if not cart["items"]:
        flash("Savat bo‘sh", "danger")
        return redirect(url_for("home"))

    db = get_db()
    try:
        db.execute("BEGIN")
        d = date.today().isoformat()
        sale_id = db.execute("""
              INSERT INTO sales(sale_date, agent_id, total_sell_uzs, total_cost_uzs, total_profit_uzs)
              VALUES(?,?,?,?,?)
            """, (d, session.get("user_id"), 0, 0, 0)).lastrowid

        total_sell = 0.0
        total_cost = 0.0
        total_profit = 0.0

        for pid_str, it in cart["items"].items():
            pid = int(pid_str)
            qty = float(it["qty"])
            price = float(it["price"])
            if qty <= 0 or price <= 0:
                raise ValueError("Savatda noto‘g‘ri qiymat bor")

            available = product_qty(pid)
            if available + 1e-9 < qty:
                raise ValueError(f"Qoldiq yetarli emas: {it['name']} (Bor: {available:.2f})")

            sell_total = qty * price
            unit_cost = product_avg_cost(pid)
            cost_total = qty * unit_cost
            cons = []
            profit = sell_total - cost_total

            total_sell += sell_total
            total_cost += cost_total
            total_profit += profit

            item_id = db.execute("""
              INSERT INTO sale_items(sale_id, product_id, qty, sell_price_uzs, sell_total_uzs, cost_total_uzs, profit_uzs)
              VALUES(?,?,?,?,?,?,?)
            """, (sale_id, pid, qty, price, sell_total, cost_total, profit)).lastrowid
            # Decrease stock (simple model)
            db.execute("UPDATE products SET stock_qty = COALESCE(stock_qty,0) - ? WHERE id=?", (float(qty), int(pid)))

        # Update sale totals (sales jadvalida 0 qolib ketmasin)
        db.execute(
            "UPDATE sales SET total_sell_uzs=?, total_cost_uzs=?, total_profit_uzs=? WHERE id=?",
            (float(total_sell or 0), float(total_cost or 0), float(total_profit or 0), int(sale_id))
        )

        # Auto: sale checkout -> cash_moves (1 marta, sale_id bo‘yicha)
        try:
            cur = db.cursor()
            # sale_id ustuni bo‘lmasa qo‘shamiz
            try:
                cols = [r[1] for r in cur.execute("PRAGMA table_info(cash_moves)").fetchall()]
                if "sale_id" not in cols:
                    cur.execute("ALTER TABLE cash_moves ADD COLUMN sale_id INTEGER")
            except Exception:
                pass
            # dublikat bo‘lmasin
            try:
                cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_cash_moves_sale_id ON cash_moves(sale_id)")
            except Exception:
                pass
            cur.execute("SELECT 1 FROM cash_moves WHERE sale_id=? LIMIT 1", (int(sale_id),))
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO cash_moves(move_date, direction, amount_uzs, note, sale_id) VALUES (?,?,?,?,?)",
                    (d, "IN", float(total_sell or 0), f"Auto sale #{sale_id}", int(sale_id))
                )
        except Exception:
            pass
        db.commit()
        session["cart"] = {"items": {}}
        flash("Sotuv yakunlandi ✅", "success")
    except Exception as e:
        db.rollback()
        flash(str(e), "danger")

    return redirect(url_for("home"))


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
@app.route("/kassa/delete/<int:move_id>", methods=["POST"])
@login_required
def kassa_delete(move_id: int):
    init_db()
    import sqlite3
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT id, COALESCE(sale_id, NULL) AS sale_id FROM cash_moves WHERE id=?", (move_id,)).fetchone()
        if not row:
            flash("Topilmadi", "danger")
            return redirect(url_for("kassa"))

        # Auto sale yozuvlarini o'chirish taqiqlanadi
        if row["sale_id"] is not None:
            flash("Auto sale yozuvini o‘chirib bo‘lmaydi", "danger")
            return redirect(url_for("kassa"))

        conn.execute("DELETE FROM cash_moves WHERE id=?", (move_id,))
        conn.commit()
        flash("O‘chirildi ✅", "success")
        return redirect(url_for("kassa"))
    finally:
        conn.close()


@app.route("/kassa/edit/<int:move_id>", methods=["GET", "POST"])
@login_required
def kassa_edit(move_id: int):
    init_db()
    import sqlite3
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("""
            SELECT id, move_date, direction, amount_uzs, note, COALESCE(sale_id, NULL) AS sale_id
            FROM cash_moves WHERE id=?
        """, (move_id,)).fetchone()

        if not row:
            flash("Topilmadi", "danger")
            return redirect(url_for("kassa"))

        is_auto_sale = (row["sale_id"] is not None)

        if request.method == "POST":
            note = (request.form.get("note") or "").strip()

            # Auto sale bo'lsa: faqat note o'zgaradi
            if is_auto_sale:
                conn.execute("UPDATE cash_moves SET note=? WHERE id=?", (note, move_id))
                conn.commit()
                flash("Saqlanди ✅ (Auto sale: faqat izoh o‘zgardi)", "success")
                return redirect(url_for("kassa"))

            move_date = (request.form.get("move_date") or "").strip() or (row["move_date"] or "")
            direction = (request.form.get("direction") or row["direction"] or "IN").strip().upper()
            amount_raw = (request.form.get("amount_uzs") or "").replace(" ", "").replace(",", "").strip()

            if direction not in ("IN", "OUT"):
                flash("Direction xato (IN/OUT)", "danger")
                return redirect(url_for("kassa_edit", move_id=move_id))

            try:
                amount = float(amount_raw)
            except Exception:
                amount = 0.0

            if amount <= 0:
                flash("Summa noto‘g‘ri", "danger")
                return redirect(url_for("kassa_edit", move_id=move_id))

            conn.execute("""
                UPDATE cash_moves
                SET move_date=?, direction=?, amount_uzs=?, note=?
                WHERE id=?
            """, (move_date, direction, amount, note, move_id))
            conn.commit()
            flash("Saqlanди ✅", "success")
            return redirect(url_for("kassa"))

        return render_template("kassa_edit.html", r=row, is_auto_sale=is_auto_sale)

    finally:
        conn.close()
# =========================
# /Kassa: Edit / Delete
# =========================


# Auto DB init on import (init sahifa yo'q, methods=["GET", "POST"])
with app.app_context():
    init_db()



@app.route("/sales/qty/<int:product_id>/<action>", methods=["GET", "POST"])
@login_required
def sales_qty(product_id: int, action: str):
    cart = cart_get()
    pid = str(product_id)
    it = cart["items"].get(pid, {"qty": 0})
    try:
        qty = float(it.get("qty", 0) if isinstance(it, dict) else it)
    except Exception:
        qty = 0.0

    if action == "inc":
        qty += 1.0
    elif action == "dec":
        qty = max(0.0, qty - 1.0)
    elif action in ("del", "remove"):
        qty = 0.0

    if qty <= 0:
        cart["items"].pop(pid, None)
    else:
        name = (it.get("name") if isinstance(it, dict) else "") or (cart["items"].get(pid, {}).get("name") if isinstance(cart["items"].get(pid), dict) else "")
        price = (it.get("price") if isinstance(it, dict) else None)
        try:
            price = float(price) if price is not None else float(cart["items"].get(pid, {}).get("price", 0))
        except Exception:
            price = 0.0
        cart["items"][pid] = {"name": name, "qty": qty, "price": price}

    session["cart"] = cart
    return redirect(request.referrer or url_for("sales"))


if __name__ == "__main__":
    app.run(debug=True, port=5001, host="0.0.0.0")



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
    return render_template("kpi.html", cats=cats, stock_map=stock_map, app_name=APP_NAME)


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
    return render_template("kpi_detail.html", cat=cat, prod_rows=prod_rows, app_name=APP_NAME)


# --- KPI -> Category -> Kirim (no FIFO) ---
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

            flash("Mahsulot va miqdorni to‘g‘ri kiriting", "danger")

            return redirect(url_for("kpi_kirim", category_id=category_id))


        # inventory_moves jadvaliga IN yozamiz (FIFO YO'Q)

        exec_sql("""

            INSERT INTO inventory_moves(move_date, move_type, product_id, qty, unit_cost_uzs, note)

            VALUES(?,?,?,?,?,?)

        """, (move_date, "IN", product_id, qty, unit_cost_uzs, note))


        # products.stock_qty ni ham yangilaymiz (jadval va KPI bir xil bo‘lsin)

        exec_sql(

            "UPDATE products SET stock_qty = COALESCE(stock_qty,0) + ? WHERE id=?",

            (float(qty), int(product_id))

        )


        flash("Kirim qo‘shildi ✅", "success")

        return redirect(url_for("kpi"))
    return render_template("kpi_kirim.html", category=cat, products=products, app_name=APP_NAME)
# --- /KPI -> Kirim ---




# =========================
# Sales History (sold list)
# =========================


# (sales_history moved to routes/sales_history.py)


if __name__ == '__main__':
    app.run(debug=True, port=5001, host='0.0.0.0')

def product_avg_cost(product_id: int) -> float:
    db = get_db()
    row = db.execute("""
        SELECT
            COALESCE(SUM(qty * unit_cost_uzs),0) AS total_cost,
            COALESCE(SUM(qty),0) AS total_qty
        FROM inventory_moves
        WHERE product_id=?
          AND move_type='IN'
    """, (product_id,)).fetchone()

    if not row or row["total_qty"] == 0:
        return 0.0

    return float(row["total_cost"] / row["total_qty"])
