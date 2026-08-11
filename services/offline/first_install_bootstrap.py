from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.request import Request, build_opener


BOOTSTRAP_PATH = "/api/offline/bootstrap"
BOOTSTRAP_SCHEMA_VERSION = 1


class BootstrapError(RuntimeError):
    pass


class BootstrapResponseError(BootstrapError):
    pass


class BootstrapApplyError(BootstrapError):
    pass


@dataclass(frozen=True)
class BootstrapResult:
    users: int
    agents: int
    categories: int
    products: int
    database_uuid: str


def _required_text(
    value: object,
    *,
    field_name: str,
) -> str:
    if not isinstance(value, str):
        raise BootstrapResponseError(
            f"{field_name} matn bo‘lishi kerak"
        )

    normalized = value.strip()

    if not normalized:
        raise BootstrapResponseError(
            f"{field_name} bo‘sh bo‘lmasligi kerak"
        )

    return normalized


def _optional_text(
    value: object,
    *,
    field_name: str,
) -> str | None:
    if value is None:
        return None

    return _required_text(
        value,
        field_name=field_name,
    )


def _integer(
    value: object,
    *,
    field_name: str,
) -> int:
    if isinstance(value, bool):
        raise BootstrapResponseError(
            f"{field_name} integer bo‘lishi kerak"
        )

    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise BootstrapResponseError(
            f"{field_name} integer bo‘lishi kerak"
        ) from exc


def _number(
    value: object,
    *,
    field_name: str,
) -> float:
    if isinstance(value, bool):
        raise BootstrapResponseError(
            f"{field_name} son bo‘lishi kerak"
        )

    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise BootstrapResponseError(
            f"{field_name} son bo‘lishi kerak"
        ) from exc


def _list(
    payload: Mapping[str, Any],
    field_name: str,
) -> list[Mapping[str, Any]]:
    value = payload.get(field_name)

    if not isinstance(value, list):
        raise BootstrapResponseError(
            f"{field_name} ro‘yxat bo‘lishi kerak"
        )

    result: list[Mapping[str, Any]] = []

    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise BootstrapResponseError(
                f"{field_name}[{index}] object bo‘lishi kerak"
            )

        result.append(item)

    return result


def fetch_bootstrap_snapshot(
    *,
    base_url: str,
    token: str,
    installation_uuid: str | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    normalized_url = _required_text(
        base_url,
        field_name="base_url",
    ).rstrip("/")

    normalized_token = _required_text(
        token,
        field_name="token",
    )

    headers = {
        "Accept": "application/json",
        "Authorization": (
            f"Bearer {normalized_token}"
        ),
        "User-Agent": (
            "Gold9999-FirstInstallBootstrap/1"
        ),
    }

    normalized_installation_uuid = str(
        installation_uuid or ""
    ).strip()

    if normalized_installation_uuid:
        headers[
            "X-Gold9999-Installation-UUID"
        ] = normalized_installation_uuid

    request = Request(
        url=normalized_url + BOOTSTRAP_PATH,
        method="GET",
        headers=headers,
    )

    try:
        with build_opener().open(
            request,
            timeout=timeout_seconds,
        ) as response:
            status_code = int(response.getcode())
            raw_body = response.read()

    except Exception as exc:
        raise BootstrapResponseError(
            f"Bootstrap serverga ulanilmadi: {exc}"
        ) from exc

    if not 200 <= status_code < 300:
        raise BootstrapResponseError(
            f"Bootstrap HTTP xatosi: {status_code}"
        )

    try:
        payload = json.loads(
            raw_body.decode("utf-8")
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise BootstrapResponseError(
            "Bootstrap javobi noto‘g‘ri JSON"
        ) from exc

    if not isinstance(payload, dict):
        raise BootstrapResponseError(
            "Bootstrap javobi object bo‘lishi kerak"
        )

    if payload.get("success") is not True:
        raise BootstrapResponseError(
            str(
                payload.get("message")
                or "Bootstrap muvaffaqiyatsiz"
            )
        )

    return payload


def apply_bootstrap_snapshot(
    connection: sqlite3.Connection,
    payload: Mapping[str, Any],
) -> BootstrapResult:
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError(
            "connection sqlite3.Connection bo‘lishi kerak"
        )

    if not isinstance(payload, Mapping):
        raise BootstrapResponseError(
            "payload object bo‘lishi kerak"
        )

    schema_version = _integer(
        payload.get("schema_version"),
        field_name="schema_version",
    )

    if schema_version != BOOTSTRAP_SCHEMA_VERSION:
        raise BootstrapResponseError(
            "Bootstrap schema version qo‘llab-quvvatlanmaydi: "
            f"{schema_version}"
        )

    database_uuid = _required_text(
        payload.get("database_uuid"),
        field_name="database_uuid",
    )

    users = _list(payload, "users")
    agents = _list(payload, "agents")
    categories = _list(payload, "categories")
    products = _list(payload, "products")

    savepoint = "first_install_bootstrap"

    connection.execute(
        f"SAVEPOINT {savepoint}"
    )

    try:
        for item in users:
            username = _required_text(
                item.get("username"),
                field_name="user.username",
            )

            values = (
                _required_text(
                    item.get("password_hash"),
                    field_name="user.password_hash",
                ),
                _optional_text(
                    item.get("full_name"),
                    field_name="user.full_name",
                ),
                _required_text(
                    item.get("role"),
                    field_name="user.role",
                ),
                _integer(
                    item.get("is_active"),
                    field_name="user.is_active",
                ),
                _required_text(
                    item.get("created_at"),
                    field_name="user.created_at",
                ),
                username,
            )

            existing = connection.execute(
                """
                SELECT id
                FROM users
                WHERE username=?
                """,
                (username,),
            ).fetchone()

            if existing is None:
                connection.execute(
                    """
                    INSERT INTO users(
                        password_hash,
                        full_name,
                        role,
                        is_active,
                        created_at,
                        username
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            else:
                connection.execute(
                    """
                    UPDATE users
                    SET
                        password_hash=?,
                        full_name=?,
                        role=?,
                        is_active=?,
                        created_at=?
                    WHERE username=?
                    """,
                    values,
                )

        for item in agents:
            full_name = _optional_text(
                item.get("full_name"),
                field_name="agent.full_name",
            )

            phone = _optional_text(
                item.get("phone"),
                field_name="agent.phone",
            )

            is_active = _integer(
                item.get("is_active"),
                field_name="agent.is_active",
            )

            existing = connection.execute(
                """
                SELECT id
                FROM agents
                WHERE
                    COALESCE(full_name, '') =
                    COALESCE(?, '')
                  AND
                    COALESCE(phone, '') =
                    COALESCE(?, '')
                ORDER BY id
                LIMIT 1
                """,
                (full_name, phone),
            ).fetchone()

            if existing is None:
                connection.execute(
                    """
                    INSERT INTO agents(
                        full_name,
                        phone,
                        is_active
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        full_name,
                        phone,
                        is_active,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE agents
                    SET
                        full_name=?,
                        phone=?,
                        is_active=?
                    WHERE id=?
                    """,
                    (
                        full_name,
                        phone,
                        is_active,
                        int(existing["id"]),
                    ),
                )

        for item in categories:
            entity_uuid = _required_text(
                item.get("entity_uuid"),
                field_name="category.entity_uuid",
            )

            values = (
                _required_text(
                    item.get("name"),
                    field_name="category.name",
                ),
                _integer(
                    item.get("sort_order"),
                    field_name="category.sort_order",
                ),
                _integer(
                    item.get("is_active"),
                    field_name="category.is_active",
                ),
                _required_text(
                    item.get("created_at"),
                    field_name="category.created_at",
                ),
                _integer(
                    item.get("sync_version"),
                    field_name="category.sync_version",
                ),
                entity_uuid,
            )

            existing = connection.execute(
                """
                SELECT id
                FROM categories
                WHERE entity_uuid=?
                """,
                (entity_uuid,),
            ).fetchone()

            if existing is None:
                connection.execute(
                    """
                    INSERT INTO categories(
                        name,
                        sort_order,
                        is_active,
                        created_at,
                        sync_version,
                        entity_uuid
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            else:
                connection.execute(
                    """
                    UPDATE categories
                    SET
                        name=?,
                        sort_order=?,
                        is_active=?,
                        created_at=?,
                        sync_version=?
                    WHERE entity_uuid=?
                    """,
                    values,
                )

        for item in products:
            entity_uuid = _required_text(
                item.get("entity_uuid"),
                field_name="product.entity_uuid",
            )

            category_uuid = _required_text(
                item.get("category_uuid"),
                field_name="product.category_uuid",
            )

            category = connection.execute(
                """
                SELECT id
                FROM categories
                WHERE entity_uuid=?
                """,
                (category_uuid,),
            ).fetchone()

            if category is None:
                raise BootstrapApplyError(
                    "Product category lokal bazada topilmadi: "
                    f"{category_uuid}"
                )

            values = (
                _required_text(
                    item.get("name"),
                    field_name="product.name",
                ),
                int(category["id"]),
                _number(
                    item.get(
                        "sell_price_default_uzs"
                    ),
                    field_name=(
                        "product.sell_price_default_uzs"
                    ),
                ),
                _integer(
                    item.get("is_active"),
                    field_name="product.is_active",
                ),
                _required_text(
                    item.get("created_at"),
                    field_name="product.created_at",
                ),
                _integer(
                    item.get("sync_version"),
                    field_name="product.sync_version",
                ),
                entity_uuid,
            )

            existing = connection.execute(
                """
                SELECT id
                FROM products
                WHERE entity_uuid=?
                """,
                (entity_uuid,),
            ).fetchone()

            if existing is None:
                connection.execute(
                    """
                    INSERT INTO products(
                        name,
                        category_id,
                        sell_price_default_uzs,
                        is_active,
                        created_at,
                        sync_version,
                        entity_uuid
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            else:
                connection.execute(
                    """
                    UPDATE products
                    SET
                        name=?,
                        category_id=?,
                        sell_price_default_uzs=?,
                        is_active=?,
                        created_at=?,
                        sync_version=?
                    WHERE entity_uuid=?
                    """,
                    values,
                )

        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        foreign_keys = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        if integrity != "ok":
            raise BootstrapApplyError(
                f"Database integrity xato: {integrity}"
            )

        if foreign_keys:
            raise BootstrapApplyError(
                "Bootstrap foreign key xatosi: "
                f"{len(foreign_keys)}"
            )

        connection.execute(
            f"RELEASE SAVEPOINT {savepoint}"
        )

    except Exception:
        connection.execute(
            f"ROLLBACK TO SAVEPOINT {savepoint}"
        )
        connection.execute(
            f"RELEASE SAVEPOINT {savepoint}"
        )
        raise

    return BootstrapResult(
        users=len(users),
        agents=len(agents),
        categories=len(categories),
        products=len(products),
        database_uuid=database_uuid,
    )


def run_first_install_bootstrap(
    connection: sqlite3.Connection,
    *,
    base_url: str,
    token: str,
    installation_uuid: str | None = None,
    timeout_seconds: float = 30.0,
) -> BootstrapResult:
    payload = fetch_bootstrap_snapshot(
        base_url=base_url,
        token=token,
        installation_uuid=installation_uuid,
        timeout_seconds=timeout_seconds,
    )

    return apply_bootstrap_snapshot(
        connection,
        payload,
    )


__all__ = [
    "BOOTSTRAP_PATH",
    "BOOTSTRAP_SCHEMA_VERSION",
    "BootstrapApplyError",
    "BootstrapError",
    "BootstrapResponseError",
    "BootstrapResult",
    "apply_bootstrap_snapshot",
    "fetch_bootstrap_snapshot",
    "run_first_install_bootstrap",
]
