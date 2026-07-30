from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping

from services.offline.entity_lookup import (
    find_local_entity,
    normalize_entity_uuid,
)
from services.offline.remote_applier import (
    InvalidRemotePayloadError,
    MissingDependencyError,
    RemoteApplyContext,
    RemoteApplyResult,
    StaleRemoteChangeError,
    register_remote_handler,
)


CATEGORY_FIELDS = frozenset(
    {
        "name",
        "sort_order",
        "is_active",
        "created_at",
    }
)


def _require_exact_fields(
    payload: Mapping[str, Any],
    expected_fields: frozenset[str],
    *,
    entity_type: str,
) -> None:
    actual_fields = set(payload)

    missing = sorted(expected_fields - actual_fields)
    extra = sorted(actual_fields - expected_fields)

    if not missing and not extra:
        return

    details: list[str] = []

    if missing:
        details.append(
            "missing: " + ", ".join(missing)
        )

    if extra:
        details.append(
            "extra: " + ", ".join(extra)
        )

    raise InvalidRemotePayloadError(
        f"{entity_type} payload noto‘g‘ri: "
        + "; ".join(details)
    )


def _normalize_name(
    value: Any,
) -> str:
    if not isinstance(value, str):
        raise InvalidRemotePayloadError(
            "name matn bo‘lishi kerak"
        )

    normalized = value.strip()

    if not normalized:
        raise InvalidRemotePayloadError(
            "name bo‘sh bo‘lishi mumkin emas"
        )

    return normalized


def _normalize_sort_order(
    value: Any,
) -> int:
    if isinstance(value, bool):
        raise InvalidRemotePayloadError(
            "sort_order butun son bo‘lishi kerak"
        )

    if isinstance(value, int):
        normalized = value
    elif (
        isinstance(value, float)
        and value.is_integer()
    ):
        normalized = int(value)
    elif isinstance(value, str):
        raw = value.strip()

        if not raw:
            raise InvalidRemotePayloadError(
                "sort_order butun son bo‘lishi kerak"
            )

        try:
            normalized = int(raw)
        except ValueError as exc:
            raise InvalidRemotePayloadError(
                "sort_order butun son bo‘lishi kerak"
            ) from exc
    else:
        raise InvalidRemotePayloadError(
            "sort_order butun son bo‘lishi kerak"
        )

    if normalized < 0:
        raise InvalidRemotePayloadError(
            "sort_order manfiy bo‘lishi mumkin emas"
        )

    return normalized


def _normalize_is_active(
    value: Any,
) -> int:
    if isinstance(value, bool):
        return int(value)

    if isinstance(value, int) and value in (0, 1):
        return value

    raise InvalidRemotePayloadError(
        "is_active faqat true/false yoki 0/1 "
        "bo‘lishi kerak"
    )


def _normalize_created_at(
    value: Any,
) -> str:
    if not isinstance(value, str):
        raise InvalidRemotePayloadError(
            "created_at matn bo‘lishi kerak"
        )

    raw = value.strip()

    if not raw:
        raise InvalidRemotePayloadError(
            "created_at bo‘sh bo‘lishi mumkin emas"
        )

    candidate = raw

    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise InvalidRemotePayloadError(
            "created_at ISO datetime bo‘lishi kerak"
        ) from exc

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(
            timezone.utc
        ).replace(
            tzinfo=None
        )

    return parsed.isoformat(
        sep=" ",
        timespec=(
            "microseconds"
            if parsed.microsecond
            else "seconds"
        ),
    )


def _normalize_category_payload(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    _require_exact_fields(
        payload,
        CATEGORY_FIELDS,
        entity_type="category",
    )

    return {
        "name": _normalize_name(
            payload["name"]
        ),
        "sort_order": _normalize_sort_order(
            payload["sort_order"]
        ),
        "is_active": _normalize_is_active(
            payload["is_active"]
        ),
        "created_at": _normalize_created_at(
            payload["created_at"]
        ),
    }


def _get_category_row(
    connection: sqlite3.Connection,
    local_id: int,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT
            id,
            name,
            sort_order,
            is_active,
            created_at,
            entity_uuid,
            sync_version
        FROM categories
        WHERE id=?
        """,
        (local_id,),
    ).fetchone()

    if row is None:
        raise RuntimeError(
            "Category identity mavjud, "
            "lekin row topilmadi"
        )

    return row


def _category_matches(
    row: sqlite3.Row,
    payload: Mapping[str, Any],
) -> bool:
    return (
        str(row["name"]) == payload["name"]
        and int(row["sort_order"])
        == payload["sort_order"]
        and int(row["is_active"])
        == payload["is_active"]
        and _normalize_created_at(
            str(row["created_at"])
        )
        == payload["created_at"]
    )


def _raise_category_integrity_error(
    exc: sqlite3.IntegrityError,
) -> None:
    raise InvalidRemotePayloadError(
        "Category database chekloviga zid: "
        f"{exc}"
    ) from exc


def apply_category_remote(
    context: RemoteApplyContext,
) -> RemoteApplyResult:
    payload = _normalize_category_payload(
        context.payload
    )

    if context.existing is None:
        try:
            cursor = context.connection.execute(
                """
                INSERT INTO categories(
                    name,
                    sort_order,
                    is_active,
                    created_at,
                    entity_uuid,
                    sync_version
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["name"],
                    payload["sort_order"],
                    payload["is_active"],
                    payload["created_at"],
                    context.entity_uuid,
                    context.remote_version,
                ),
            )
        except sqlite3.IntegrityError as exc:
            _raise_category_integrity_error(exc)

        return RemoteApplyResult(
            entity_type=context.entity_type,
            entity_uuid=context.entity_uuid,
            local_id=int(cursor.lastrowid),
            previous_version=None,
            applied_version=context.remote_version,
            created=True,
            changed=True,
        )

    row = _get_category_row(
        context.connection,
        context.existing.local_id,
    )

    previous_version = int(
        row["sync_version"]
    )

    if context.remote_version == previous_version:
        if not _category_matches(row, payload):
            raise StaleRemoteChangeError(
                "Category bir xil version bilan "
                "boshqa ma’lumot yubordi"
            )

        return RemoteApplyResult(
            entity_type=context.entity_type,
            entity_uuid=context.entity_uuid,
            local_id=context.existing.local_id,
            previous_version=previous_version,
            applied_version=previous_version,
            created=False,
            changed=False,
        )

    local_created_at = _normalize_created_at(
        str(row["created_at"])
    )

    if payload["created_at"] != local_created_at:
        raise InvalidRemotePayloadError(
            "Category created_at update vaqtida "
            "o‘zgarmasligi kerak"
        )

    try:
        context.connection.execute(
            """
            UPDATE categories
            SET name=?,
                sort_order=?,
                is_active=?,
                sync_version=?
            WHERE id=?
            """,
            (
                payload["name"],
                payload["sort_order"],
                payload["is_active"],
                context.remote_version,
                context.existing.local_id,
            ),
        )
    except sqlite3.IntegrityError as exc:
        _raise_category_integrity_error(exc)

    return RemoteApplyResult(
        entity_type=context.entity_type,
        entity_uuid=context.entity_uuid,
        local_id=context.existing.local_id,
        previous_version=previous_version,
        applied_version=context.remote_version,
        created=False,
        changed=True,
    )


PRODUCT_FIELDS = frozenset(
    {
        "name",
        "category_uuid",
        "sell_price_default_uzs",
        "is_active",
        "created_at",
    }
)


def _normalize_price(
    value: Any,
) -> float:
    if isinstance(value, bool):
        raise InvalidRemotePayloadError(
            "sell_price_default_uzs son bo‘lishi kerak"
        )

    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRemotePayloadError(
            "sell_price_default_uzs son bo‘lishi kerak"
        ) from exc

    if normalized < 0:
        raise InvalidRemotePayloadError(
            "sell_price_default_uzs manfiy "
            "bo‘lishi mumkin emas"
        )

    return normalized


def _normalize_category_uuid(
    value: Any,
) -> str:
    if not isinstance(value, str):
        raise InvalidRemotePayloadError(
            "category_uuid matn bo‘lishi kerak"
        )

    try:
        return normalize_entity_uuid(
            value.strip()
        )
    except (TypeError, ValueError) as exc:
        raise InvalidRemotePayloadError(
            "category_uuid noto‘g‘ri UUID"
        ) from exc


def _normalize_product_payload(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    _require_exact_fields(
        payload,
        PRODUCT_FIELDS,
        entity_type="product",
    )

    return {
        "name": _normalize_name(
            payload["name"]
        ),
        "category_uuid": (
            _normalize_category_uuid(
                payload["category_uuid"]
            )
        ),
        "sell_price_default_uzs": (
            _normalize_price(
                payload[
                    "sell_price_default_uzs"
                ]
            )
        ),
        "is_active": _normalize_is_active(
            payload["is_active"]
        ),
        "created_at": _normalize_created_at(
            payload["created_at"]
        ),
    }


def _get_product_row(
    connection: sqlite3.Connection,
    local_id: int,
) -> sqlite3.Row:
    row = connection.execute(
        '''
        SELECT
            p.id,
            p.name,
            p.category_id,
            p.sell_price_default_uzs,
            p.is_active,
            p.created_at,
            p.stock_qty,
            p.entity_uuid,
            p.sync_version,
            c.entity_uuid AS category_uuid
        FROM products p
        JOIN categories c
          ON c.id=p.category_id
        WHERE p.id=?
        ''',
        (local_id,),
    ).fetchone()

    if row is None:
        raise RuntimeError(
            "Product identity mavjud, "
            "lekin row topilmadi"
        )

    return row


def _product_matches(
    row: sqlite3.Row,
    payload: Mapping[str, Any],
) -> bool:
    return (
        str(row["name"]) == payload["name"]
        and str(row["category_uuid"])
        == payload["category_uuid"]
        and float(
            row["sell_price_default_uzs"]
        )
        == payload["sell_price_default_uzs"]
        and int(row["is_active"])
        == payload["is_active"]
        and _normalize_created_at(
            str(row["created_at"])
        )
        == payload["created_at"]
    )


def _raise_product_integrity_error(
    exc: sqlite3.IntegrityError,
) -> None:
    raise InvalidRemotePayloadError(
        "Product database chekloviga zid: "
        f"{exc}"
    ) from exc


def apply_product_remote(
    context: RemoteApplyContext,
) -> RemoteApplyResult:
    payload = _normalize_product_payload(
        context.payload
    )

    category = find_local_entity(
        context.connection,
        "category",
        payload["category_uuid"],
    )

    if category is None:
        raise MissingDependencyError(
            "Product category lokal bazada "
            "topilmadi"
        )

    category_row = context.connection.execute(
        '''
        SELECT
            id,
            is_active
        FROM categories
        WHERE id=?
        ''',
        (category.local_id,),
    ).fetchone()

    if category_row is None:
        raise MissingDependencyError(
            "Product category row topilmadi"
        )

    if (
        payload["is_active"] == 1
        and int(category_row["is_active"]) != 1
    ):
        raise InvalidRemotePayloadError(
            "Faol product nofaol category "
            "ichida bo‘lishi mumkin emas"
        )

    if context.existing is None:
        try:
            cursor = context.connection.execute(
                '''
                INSERT INTO products(
                    name,
                    category_id,
                    sell_price_default_uzs,
                    is_active,
                    created_at,
                    stock_qty,
                    entity_uuid,
                    sync_version
                )
                VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                ''',
                (
                    payload["name"],
                    category.local_id,
                    payload[
                        "sell_price_default_uzs"
                    ],
                    payload["is_active"],
                    payload["created_at"],
                    context.entity_uuid,
                    context.remote_version,
                ),
            )
        except sqlite3.IntegrityError as exc:
            _raise_product_integrity_error(exc)

        return RemoteApplyResult(
            entity_type=context.entity_type,
            entity_uuid=context.entity_uuid,
            local_id=int(cursor.lastrowid),
            previous_version=None,
            applied_version=context.remote_version,
            created=True,
            changed=True,
        )

    row = _get_product_row(
        context.connection,
        context.existing.local_id,
    )

    previous_version = int(
        row["sync_version"]
    )

    if context.remote_version == previous_version:
        if not _product_matches(row, payload):
            raise StaleRemoteChangeError(
                "Product bir xil version bilan "
                "boshqa ma’lumot yubordi"
            )

        return RemoteApplyResult(
            entity_type=context.entity_type,
            entity_uuid=context.entity_uuid,
            local_id=context.existing.local_id,
            previous_version=previous_version,
            applied_version=previous_version,
            created=False,
            changed=False,
        )

    local_created_at = _normalize_created_at(
        str(row["created_at"])
    )

    if payload["created_at"] != local_created_at:
        raise InvalidRemotePayloadError(
            "Product created_at update vaqtida "
            "o‘zgarmasligi kerak"
        )

    try:
        context.connection.execute(
            '''
            UPDATE products
            SET name=?,
                category_id=?,
                sell_price_default_uzs=?,
                is_active=?,
                sync_version=?
            WHERE id=?
            ''',
            (
                payload["name"],
                category.local_id,
                payload[
                    "sell_price_default_uzs"
                ],
                payload["is_active"],
                context.remote_version,
                context.existing.local_id,
            ),
        )
    except sqlite3.IntegrityError as exc:
        _raise_product_integrity_error(exc)

    return RemoteApplyResult(
        entity_type=context.entity_type,
        entity_uuid=context.entity_uuid,
        local_id=context.existing.local_id,
        previous_version=previous_version,
        applied_version=context.remote_version,
        created=False,
        changed=True,
    )


register_remote_handler(
    "category",
    apply_category_remote,
)

register_remote_handler(
    "product",
    apply_product_remote,
)


__all__ = [
    "CATEGORY_FIELDS",
    "PRODUCT_FIELDS",
    "apply_category_remote",
    "apply_product_remote",
]
