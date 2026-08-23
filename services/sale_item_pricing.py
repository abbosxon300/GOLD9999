from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DISCOUNT_NONE = "none"
DISCOUNT_PERCENT = "percent"
DISCOUNT_AMOUNT = "amount"

DISCOUNT_TYPES = frozenset({
    DISCOUNT_NONE,
    DISCOUNT_PERCENT,
    DISCOUNT_AMOUNT,
})


@dataclass(frozen=True)
class SaleItemPricing:
    list_price_uzs: float
    discount_type: str
    discount_value: float
    sell_price_uzs: float
    discount_total_uzs: float
    sell_total_uzs: float


def _number(
    value: Any,
    *,
    field: str,
) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field} noto'g'ri"
        ) from exc

    if number < 0:
        raise ValueError(
            f"{field} manfiy bo'lishi mumkin emas"
        )

    return number


def normalize_discount_type(
    value: Any,
) -> str:
    discount_type = str(
        value or DISCOUNT_NONE
    ).strip().lower()

    if discount_type not in DISCOUNT_TYPES:
        raise ValueError(
            "Skidka turi noto'g'ri"
        )

    return discount_type


def calculate_sale_item_pricing(
    *,
    qty: Any,
    list_price_uzs: Any,
    discount_type: Any = DISCOUNT_NONE,
    discount_value: Any = 0,
) -> SaleItemPricing:
    quantity = _number(
        qty,
        field="Miqdor",
    )
    list_price = _number(
        list_price_uzs,
        field="Asl narx",
    )
    dtype = normalize_discount_type(
        discount_type
    )
    dvalue = _number(
        discount_value,
        field="Skidka",
    )

    if quantity <= 0:
        raise ValueError(
            "Miqdor 0 dan katta bo'lishi kerak"
        )

    if list_price <= 0:
        raise ValueError(
            "Asl narx 0 dan katta bo'lishi kerak"
        )

    if dtype == DISCOUNT_NONE:
        dvalue = 0.0
        discount_per_unit = 0.0

    elif dtype == DISCOUNT_PERCENT:
        if dvalue > 100:
            raise ValueError(
                "Foizli skidka 100% dan oshmasligi kerak"
            )

        discount_per_unit = (
            list_price * dvalue / 100.0
        )

    else:
        if dvalue > list_price:
            raise ValueError(
                "Skidka asl narxdan katta bo'lishi mumkin emas"
            )

        discount_per_unit = dvalue

    sell_price = (
        list_price - discount_per_unit
    )

    discount_total = (
        quantity * discount_per_unit
    )
    sell_total = (
        quantity * sell_price
    )

    return SaleItemPricing(
        list_price_uzs=list_price,
        discount_type=dtype,
        discount_value=dvalue,
        sell_price_uzs=sell_price,
        discount_total_uzs=discount_total,
        sell_total_uzs=sell_total,
    )


__all__ = [
    "DISCOUNT_AMOUNT",
    "DISCOUNT_NONE",
    "DISCOUNT_PERCENT",
    "DISCOUNT_TYPES",
    "SaleItemPricing",
    "calculate_sale_item_pricing",
    "normalize_discount_type",
]
