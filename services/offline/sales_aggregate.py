from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping
from uuid import UUID


SALE_AGGREGATE_SCHEMA_VERSION = 3


class InvalidSaleAggregatePayloadError(ValueError):
    """Sale aggregate payload contract buzilgan."""


def _required_text(
    value: Any,
    *,
    field_name: str,
) -> str:
    if not isinstance(value, str):
        raise InvalidSaleAggregatePayloadError(
            f"{field_name} matn bo‘lishi kerak"
        )

    normalized = value.strip()

    if not normalized:
        raise InvalidSaleAggregatePayloadError(
            f"{field_name} bo‘sh bo‘lmasligi kerak"
        )

    return normalized


def _optional_text(
    value: Any,
    *,
    field_name: str,
) -> str | None:
    if value is None:
        return None

    return _required_text(
        value,
        field_name=field_name,
    )


def _entity_uuid(
    value: Any,
    *,
    field_name: str,
) -> str:
    normalized = _required_text(
        value,
        field_name=field_name,
    )

    try:
        return str(UUID(normalized))
    except (TypeError, ValueError, AttributeError) as exc:
        raise InvalidSaleAggregatePayloadError(
            f"{field_name} UUID noto‘g‘ri"
        ) from exc


def _positive_integer(
    value: Any,
    *,
    field_name: str,
) -> int:
    if isinstance(value, bool):
        raise InvalidSaleAggregatePayloadError(
            f"{field_name} musbat integer bo‘lishi kerak"
        )

    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidSaleAggregatePayloadError(
            f"{field_name} musbat integer bo‘lishi kerak"
        ) from exc

    if normalized <= 0:
        raise InvalidSaleAggregatePayloadError(
            f"{field_name} musbat integer bo‘lishi kerak"
        )

    return normalized


def _positive_number(
    value: Any,
    *,
    field_name: str,
) -> float:
    if isinstance(value, bool):
        raise InvalidSaleAggregatePayloadError(
            f"{field_name} musbat son bo‘lishi kerak"
        )

    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidSaleAggregatePayloadError(
            f"{field_name} musbat son bo‘lishi kerak"
        ) from exc

    if normalized <= 0:
        raise InvalidSaleAggregatePayloadError(
            f"{field_name} musbat son bo‘lishi kerak"
        )

    return normalized


def _non_negative_number(
    value: Any,
    *,
    field_name: str,
) -> float:
    if isinstance(value, bool):
        raise InvalidSaleAggregatePayloadError(
            f"{field_name} manfiy bo‘lmagan son "
            "bo‘lishi kerak"
        )

    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidSaleAggregatePayloadError(
            f"{field_name} manfiy bo‘lmagan son "
            "bo‘lishi kerak"
        ) from exc

    if normalized < 0:
        raise InvalidSaleAggregatePayloadError(
            f"{field_name} manfiy bo‘lmasligi kerak"
        )

    return normalized


def _sale_date(value: Any) -> str:
    normalized = _required_text(
        value,
        field_name="sale_date",
    )

    try:
        return date.fromisoformat(normalized).isoformat()
    except ValueError as exc:
        raise InvalidSaleAggregatePayloadError(
            "sale_date YYYY-MM-DD formatida "
            "bo‘lishi kerak"
        ) from exc


@dataclass(frozen=True, slots=True)
class SaleAggregateItem:
    entity_uuid: str
    sync_version: int
    product_uuid: str
    qty: float
    sell_price_uzs: float
    unit_cost_uzs: float
    list_price_uzs: float
    discount_type: str
    discount_value: float
    discount_total_uzs: float

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> SaleAggregateItem:
        if not isinstance(payload, Mapping):
            raise InvalidSaleAggregatePayloadError(
                "Sale item Mapping bo‘lishi kerak"
            )

        return cls(
            entity_uuid=_entity_uuid(
                payload.get("entity_uuid"),
                field_name="item.entity_uuid",
            ),
            sync_version=_positive_integer(
                payload.get("sync_version"),
                field_name="item.sync_version",
            ),
            product_uuid=_entity_uuid(
                payload.get("product_uuid"),
                field_name="item.product_uuid",
            ),
            qty=_positive_number(
                payload.get("qty"),
                field_name="item.qty",
            ),
            sell_price_uzs=_positive_number(
                payload.get("sell_price_uzs"),
                field_name="item.sell_price_uzs",
            ),
            unit_cost_uzs=_non_negative_number(
                payload.get("unit_cost_uzs"),
                field_name="item.unit_cost_uzs",
            ),
            list_price_uzs=_positive_number(
                payload.get(
                    "list_price_uzs",
                    payload.get("sell_price_uzs"),
                ),
                field_name="item.list_price_uzs",
            ),
            discount_type=str(
                payload.get(
                    "discount_type",
                    "none",
                )
                or "none"
            ).strip().lower(),
            discount_value=_non_negative_number(
                payload.get(
                    "discount_value",
                    0,
                ),
                field_name="item.discount_value",
            ),
            discount_total_uzs=_non_negative_number(
                payload.get(
                    "discount_total_uzs",
                    0,
                ),
                field_name="item.discount_total_uzs",
            ),
        )

    @property
    def sell_total_uzs(self) -> float:
        return self.qty * self.sell_price_uzs

    @property
    def cost_total_uzs(self) -> float:
        return self.qty * self.unit_cost_uzs

    @property
    def profit_uzs(self) -> float:
        return self.sell_total_uzs - self.cost_total_uzs

    def to_payload(self) -> dict[str, Any]:
        return {
            "entity_uuid": self.entity_uuid,
            "sync_version": self.sync_version,
            "product_uuid": self.product_uuid,
            "qty": self.qty,
            "sell_price_uzs": self.sell_price_uzs,
            "unit_cost_uzs": self.unit_cost_uzs,
            "list_price_uzs": self.list_price_uzs,
            "discount_type": self.discount_type,
            "discount_value": self.discount_value,
            "discount_total_uzs": self.discount_total_uzs,
        }


@dataclass(frozen=True, slots=True)
class SaleAggregatePayment:
    payment_method: str
    amount_uzs: float

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "SaleAggregatePayment":
        if not isinstance(payload, Mapping):
            raise InvalidSaleAggregatePayloadError(
                "Sale payment Mapping bo‘lishi kerak"
            )

        method = _required_text(
            payload.get("payment_method"),
            field_name="payment.payment_method",
        ).upper()

        if method not in ("CASH", "CLICK"):
            raise InvalidSaleAggregatePayloadError(
                "payment_method CASH yoki CLICK "
                "bo‘lishi kerak"
            )

        return cls(
            payment_method=method,
            amount_uzs=_positive_number(
                payload.get("amount_uzs"),
                field_name="payment.amount_uzs",
            ),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "payment_method": self.payment_method,
            "amount_uzs": self.amount_uzs,
        }


@dataclass(frozen=True, slots=True)
class SaleAggregatePayload:
    schema_version: int
    entity_uuid: str
    sync_version: int
    sale_date: str
    agent_username: str | None
    items: tuple[SaleAggregateItem, ...]
    payments: tuple[SaleAggregatePayment, ...]

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> SaleAggregatePayload:
        if not isinstance(payload, Mapping):
            raise InvalidSaleAggregatePayloadError(
                "Sale aggregate Mapping bo‘lishi kerak"
            )

        schema_version = _positive_integer(
            payload.get("schema_version"),
            field_name="schema_version",
        )

        if schema_version not in (
            1,
            2,
            SALE_AGGREGATE_SCHEMA_VERSION,
        ):
            raise InvalidSaleAggregatePayloadError(
                "Sale aggregate schema version "
                f"qo‘llab-quvvatlanmaydi: {schema_version}"
            )

        raw_items = payload.get("items")

        if not isinstance(raw_items, (list, tuple)):
            raise InvalidSaleAggregatePayloadError(
                "items ro‘yxat bo‘lishi kerak"
            )

        if not raw_items:
            raise InvalidSaleAggregatePayloadError(
                "Sale aggregate ichida kamida "
                "bitta item bo‘lishi kerak"
            )

        items = tuple(
            SaleAggregateItem.from_payload(item)
            for item in raw_items
        )

        item_uuids = [
            item.entity_uuid
            for item in items
        ]

        if len(item_uuids) != len(set(item_uuids)):
            raise InvalidSaleAggregatePayloadError(
                "Sale aggregate ichida takroriy "
                "item UUID mavjud"
            )

        items_total = sum(
            item.sell_total_uzs
            for item in items
        )

        if schema_version >= 3:
            raw_payments = payload.get("payments")

            if not isinstance(
                raw_payments,
                (list, tuple),
            ):
                raise InvalidSaleAggregatePayloadError(
                    "payments ro‘yxat bo‘lishi kerak"
                )

            if not raw_payments:
                raise InvalidSaleAggregatePayloadError(
                    "Sale aggregate ichida kamida "
                    "bitta payment bo‘lishi kerak"
                )

            payments = tuple(
                SaleAggregatePayment.from_payload(
                    payment
                )
                for payment in raw_payments
            )

            methods = [
                payment.payment_method
                for payment in payments
            ]

            if len(methods) != len(set(methods)):
                raise InvalidSaleAggregatePayloadError(
                    "Bir xil payment_method "
                    "takrorlangan"
                )

            payments_total = sum(
                payment.amount_uzs
                for payment in payments
            )

            if abs(
                payments_total - items_total
            ) > 0.000001:
                raise InvalidSaleAggregatePayloadError(
                    "Payment jami sotuv jami "
                    "bilan teng emas"
                )

        else:
            # Legacy schema v1/v2 payment ma’lumotini
            # olib yurmagan. Ular tarixiy ravishda
            # 100% CASH sifatida ishlagan.
            payments = (
                SaleAggregatePayment(
                    payment_method="CASH",
                    amount_uzs=items_total,
                ),
            )

        return cls(
            schema_version=schema_version,
            entity_uuid=_entity_uuid(
                payload.get("entity_uuid"),
                field_name="sale.entity_uuid",
            ),
            sync_version=_positive_integer(
                payload.get("sync_version"),
                field_name="sale.sync_version",
            ),
            sale_date=_sale_date(
                payload.get("sale_date")
            ),
            agent_username=_optional_text(
                payload.get("agent_username"),
                field_name="agent_username",
            ),
            items=items,
            payments=payments,
        )

    @property
    def total_sell_uzs(self) -> float:
        return sum(
            item.sell_total_uzs
            for item in self.items
        )

    @property
    def total_payment_uzs(self) -> float:
        return sum(
            payment.amount_uzs
            for payment in self.payments
        )

    @property
    def cash_uzs(self) -> float:
        return sum(
            payment.amount_uzs
            for payment in self.payments
            if payment.payment_method == "CASH"
        )

    @property
    def click_uzs(self) -> float:
        return sum(
            payment.amount_uzs
            for payment in self.payments
            if payment.payment_method == "CLICK"
        )

    @property
    def total_cost_uzs(self) -> float:
        return sum(
            item.cost_total_uzs
            for item in self.items
        )

    @property
    def total_profit_uzs(self) -> float:
        return sum(
            item.profit_uzs
            for item in self.items
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "entity_uuid": self.entity_uuid,
            "sync_version": self.sync_version,
            "sale_date": self.sale_date,
            "agent_username": self.agent_username,
            "items": [
                item.to_payload()
                for item in self.items
            ],
            "payments": [
                payment.to_payload()
                for payment in self.payments
            ],
        }


def parse_sale_aggregate_payload(
    payload: Mapping[str, Any],
) -> SaleAggregatePayload:
    return SaleAggregatePayload.from_payload(payload)


__all__ = [
    "InvalidSaleAggregatePayloadError",
    "SALE_AGGREGATE_SCHEMA_VERSION",
    "SaleAggregateItem",
    "SaleAggregatePayment",
    "SaleAggregatePayload",
    "parse_sale_aggregate_payload",
]
