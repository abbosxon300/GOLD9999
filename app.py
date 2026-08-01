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
from services.runtime_paths import (
    backup_directory,
    database_path,
    ensure_runtime_directories,
)
from services.db import (
    close_db as _db_close_db,
    configure_db,
    exec_sql as _db_exec_sql,
    get_db as _db_get_db,
    q as _db_q,
    q1 as _db_q1,
)
from services.bootstrap import init_db as _bootstrap_init_db
from services.utils import (
    _fmt_uzs,
    admin_required,
    fmt0_filter,
    login_required,
    parse_float,
    parse_int,
)
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
    from routes.kassa import register_kassa_routes
except Exception:
    register_kassa_routes = None

try:
    from routes.kpi import register_kpi_routes
except Exception:
    register_kpi_routes = None

try:
    from routes.reports import register_reports_routes
except Exception:
    register_reports_routes = None

try:
    from routes.settings import register_settings_routes
except Exception:
    register_settings_routes = None

try:
    from routes.sales import register_sales_routes
except Exception:
    register_sales_routes = None
try:
    from routes.offline_api import (
        register_offline_api_routes,
    )
except Exception:
    register_offline_api_routes = None
try:
    from routes.offline_status import (
        register_offline_status_routes,
    )
except Exception:
    register_offline_status_routes = None


# --- /routes registration ---
ensure_runtime_directories()

DB_PATH = str(database_path())
configure_db(DB_PATH)

BACKUP_DIR = str(backup_directory())


# === DASHBOARD HELPERS ===
import os, sqlite3

def _db_path():
    return DB_PATH

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


def init_db() -> None:
    _bootstrap_init_db(BACKUP_DIR)

# Register extra routes
register_sales_history(
    app,
    db_path=DB_PATH,
)
app.add_template_filter(fmt0_filter, "fmt0")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "GOLD9999_CHANGE_ME_2026")
app.config["OFFLINE_SYNC_TOKEN"] = os.environ.get("OFFLINE_SYNC_TOKEN", "")


# ---------------- DB helpers ----------------


def get_db() -> sqlite3.Connection:
    return _db_get_db()


@app.teardown_appcontext
def close_db(exc=None):
    return _db_close_db(exc)


def q1(
    sql: str,
    params: tuple = (),
) -> Optional[sqlite3.Row]:
    return _db_q1(sql, params)


def q(
    sql: str,
    params: tuple = (),
) -> list[sqlite3.Row]:
    return _db_q(sql, params)


def exec_sql(
    sql: str,
    params: tuple = (),
) -> int:
    return _db_exec_sql(sql, params)













def product_qty(product_id: int) -> float:
    return _product_qty(get_db, product_id)


def product_avg_cost(product_id: int) -> float:
    return _product_avg_cost(get_db, product_id)


# ---------------- Auth ----------------


# === CART HELPERS ===





# === END CART HELPERS ===




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







if register_settings_routes:
    register_settings_routes(
        app,
        app_name=APP_NAME,
        backup_dir=BACKUP_DIR,
        db_path=DB_PATH,
        init_db=init_db,
        q=q,
        q1=q1,
        exec_sql=exec_sql,
        parse_int=parse_int,
        parse_float=parse_float,
        login_required=login_required,
        admin_required=admin_required,
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


if register_reports_routes:
    register_reports_routes(
        app,
        app_name=APP_NAME,
        init_db=init_db,
        get_db=get_db,
        fmt_uzs=_fmt_uzs,
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




# ---- Sozlamalar: Mahsulot ----




# ---- Sozlamalar: Xodimlar ----





# ---- Sozlamalar: Backup / Restore ----






# =========================
# Kassa: Edit / Delete
# =========================


# =========================
# /Kassa: Edit / Delete
# =========================


if register_offline_api_routes is not None:
    register_offline_api_routes(
        app,
        get_db=get_db,
    )

if register_offline_status_routes is not None:
    register_offline_status_routes(
        app,
        login_required=login_required,
        db_path=DB_PATH,
    )

# Auto DB init on import (init sahifa yo'q, methods=["GET", "POST"])
with app.app_context():
    init_db()









# --- KPI -> Category -> Kirim (no FIFO) ---
# --- /KPI -> Kirim ---




# =========================
# Sales History (sold list)
# =========================


# (sales_history moved to routes/sales_history.py)
