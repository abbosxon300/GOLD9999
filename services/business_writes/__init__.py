"""
Central business write layer.

HTTP routes may parse requests and render responses, but business
database mutations belong to this package.
"""

from services.business_writes.cash import (
    CashMoveResult,
    create_cash_move,
    delete_cash_move,
    ensure_sale_cash_move,
    get_cash_move,
    normalize_cash_direction,
    update_cash_move,
    update_cash_move_note,
)
from services.business_writes.inventory import (
    InventoryMoveResult,
    consume_stock,
    get_inventory_move,
    get_product_stock,
    normalize_inventory_move_type,
    receive_stock,
    record_inventory_move,
)
from services.business_writes.transaction import (
    business_transaction,
)

__all__ = [
    "InventoryMoveResult",
    "consume_stock",
    "get_inventory_move",
    "get_product_stock",
    "normalize_inventory_move_type",
    "receive_stock",
    "record_inventory_move",
    "CashMoveResult",
    "business_transaction",
    "create_cash_move",
    "delete_cash_move",
    "ensure_sale_cash_move",
    "get_cash_move",
    "normalize_cash_direction",
    "update_cash_move",
    "update_cash_move_note",
]
