from __future__ import annotations

from collections.abc import Callable
from typing import Any

from flask import session


def cart_get() -> dict[str, Any]:
    """
    Session cart format:

    {
        "items": {
            "<product_id>": {
                "name": str,
                "qty": float,
                "price": float,
            }
        }
    }
    """
    cart = session.get("cart")

    if not isinstance(cart, dict):
        cart = {"items": {}}
        session["cart"] = cart
        return cart

    if "items" not in cart or not isinstance(cart.get("items"), dict):
        items: dict[str, dict[str, float]] = {}

        for key, value in list(cart.items()):
            if key == "items":
                continue

            try:
                qty = float(value)
            except (TypeError, ValueError):
                continue

            if qty > 0:
                items[str(key)] = {"qty": qty}

        cart = {"items": items}
        session["cart"] = cart
        return cart

    cleaned: dict[str, dict[str, Any]] = {}

    for product_id, item in cart["items"].items():
        product_key = str(product_id)

        if isinstance(item, dict):
            try:
                qty = float(item.get("qty", 0))
            except (TypeError, ValueError):
                qty = 0.0

            if qty <= 0:
                continue

            normalized = dict(item)
            normalized["qty"] = qty
            cleaned[product_key] = normalized
            continue

        try:
            qty = float(item)
        except (TypeError, ValueError):
            continue

        if qty > 0:
            cleaned[product_key] = {"qty": qty}

    cart["items"] = cleaned
    session["cart"] = cart
    return cart


def cart_set(cart: dict[str, Any]) -> None:
    if not isinstance(cart, dict):
        cart = {"items": {}}

    if "items" not in cart or not isinstance(cart.get("items"), dict):
        cart = {"items": {}}

    session["cart"] = cart


def cart_clear() -> None:
    session["cart"] = {"items": {}}


def cart_add(
    product_id: int,
    qty: float = 1,
    price: float | None = None,
) -> dict[str, Any]:
    cart = cart_get()
    product_key = str(product_id)
    current = cart["items"].get(product_key, {"qty": 0})

    try:
        current_qty = (
            float(current.get("qty", 0))
            if isinstance(current, dict)
            else float(current)
        )
    except (TypeError, ValueError):
        current_qty = 0.0

    new_qty = current_qty + float(qty or 0)
    new_item = dict(current) if isinstance(current, dict) else {}
    new_item["qty"] = new_qty

    if price is not None:
        try:
            new_item["price"] = float(price)
        except (TypeError, ValueError):
            pass

    if new_qty > 0:
        cart["items"][product_key] = new_item
    else:
        cart["items"].pop(product_key, None)

    cart_set(cart)
    return cart


def cart_remove(product_id: int) -> dict[str, Any]:
    cart = cart_get()
    cart["items"].pop(str(product_id), None)
    cart_set(cart)
    return cart


def cart_total(cart: dict[str, Any] | None = None) -> float:
    if cart is None:
        cart = cart_get()

    items = cart.get("items", {}) if isinstance(cart, dict) else {}
    total = 0.0

    for item in items.values():
        if not isinstance(item, dict):
            continue

        try:
            qty = float(item.get("qty", 0))
        except (TypeError, ValueError):
            qty = 0.0

        try:
            price = float(item.get("price", 0))
        except (TypeError, ValueError):
            price = 0.0

        total += qty * price

    return total


def product_qty(
    get_db: Callable[[], Any],
    product_id: int,
) -> float:
    db = get_db()

    try:
        row = db.execute("""
            SELECT COALESCE(stock_qty, 0)
            FROM products
            WHERE id=?
        """, (int(product_id),)).fetchone()

        return float(row[0] if row else 0)
    except Exception:
        return 0.0


def product_avg_cost(
    get_db: Callable[[], Any],
    product_id: int,
) -> float:
    db = get_db()

    row = db.execute("""
        SELECT
            COALESCE(SUM(qty * unit_cost_uzs), 0) AS total_cost,
            COALESCE(SUM(qty), 0) AS total_qty
        FROM inventory_moves
        WHERE product_id=?
          AND move_type='IN'
    """, (int(product_id),)).fetchone()

    if not row:
        return 0.0

    total_qty = float(row["total_qty"] or 0)

    if total_qty <= 0:
        return 0.0

    return float(row["total_cost"] or 0) / total_qty
