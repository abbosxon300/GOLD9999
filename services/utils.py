from __future__ import annotations

from functools import wraps
from typing import Optional

from flask import (
    flash,
    redirect,
    session,
    url_for,
)


def fmt0_filter(v):
    try:
        return f"{float(v or 0):,.0f}".replace(",", " ")
    except Exception:
        return "0"


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


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Bu bo‘lim faqat admin uchun", "danger")
            return redirect(url_for("home"))
        return fn(*args, **kwargs)
    return wrapper


def _fmt_uzs(x):
    try:
        return f"{float(x or 0):,.0f}".replace(",", " ")
    except Exception:
        return str(x)
