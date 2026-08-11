from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from werkzeug.security import check_password_hash


DEVICE_CREDENTIAL_BYTES = 48


class SaasProvisioningError(RuntimeError):
    pass


class InvalidLoginError(SaasProvisioningError):
    pass


class InactiveUserError(SaasProvisioningError):
    pass


class TenantError(SaasProvisioningError):
    pass


@dataclass(
    frozen=True,
    slots=True,
)
class SaasProvisionedDevice:
    tenant_id: int
    user_id: int
    username: str
    installation_uuid: str
    credential: str


def _utc_timestamp() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat(
        timespec="seconds"
    )


def _hash_secret(
    value: str,
) -> str:
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def _required_text(
    value: object,
    *,
    field_name: str,
) -> str:
    if not isinstance(value, str):
        raise SaasProvisioningError(
            f"{field_name} matn bo‘lishi kerak"
        )

    normalized = value.strip()

    if not normalized:
        raise SaasProvisioningError(
            f"{field_name} bo‘sh bo‘lmasligi kerak"
        )

    return normalized


def _normalize_uuid(
    value: str,
) -> str:
    text = _required_text(
        value,
        field_name="installation_uuid",
    )

    try:
        return str(
            UUID(text)
        )
    except ValueError as exc:
        raise SaasProvisioningError(
            "installation_uuid noto‘g‘ri"
        ) from exc


def provision_device_by_login(
    connection: sqlite3.Connection,
    *,
    username: str,
    password: str,
    installation_uuid: str,
) -> SaasProvisionedDevice:
    normalized_username = _required_text(
        username,
        field_name="username",
    )

    normalized_password = _required_text(
        password,
        field_name="password",
    )

    normalized_uuid = _normalize_uuid(
        installation_uuid
    )

    user = connection.execute(
        """
        SELECT
            u.id,
            u.username,
            u.password_hash,
            u.is_active,
            u.tenant_id,
            t.is_active AS tenant_is_active
        FROM users AS u
        LEFT JOIN tenants AS t
          ON t.id=u.tenant_id
        WHERE u.username=?
        LIMIT 1
        """,
        (normalized_username,),
    ).fetchone()

    if user is None:
        raise InvalidLoginError(
            "Login yoki parol noto‘g‘ri"
        )

    if not check_password_hash(
        str(user["password_hash"]),
        normalized_password,
    ):
        raise InvalidLoginError(
            "Login yoki parol noto‘g‘ri"
        )

    if int(user["is_active"] or 0) != 1:
        raise InactiveUserError(
            "Foydalanuvchi faol emas"
        )

    tenant_id = user["tenant_id"]

    if tenant_id is None:
        raise TenantError(
            "Foydalanuvchiga tenant biriktirilmagan"
        )

    if int(
        user["tenant_is_active"] or 0
    ) != 1:
        raise TenantError(
            "Tenant faol emas"
        )

    credential = secrets.token_urlsafe(
        DEVICE_CREDENTIAL_BYTES
    )

    credential_hash = _hash_secret(
        credential
    )

    existing = connection.execute(
        """
        SELECT id
        FROM offline_device_credentials
        WHERE installation_uuid=?
        """,
        (normalized_uuid,),
    ).fetchone()

    now = _utc_timestamp()

    if existing is None:
        connection.execute(
            """
            INSERT INTO offline_device_credentials(
                installation_uuid,
                credential_hash,
                created_at,
                last_used_at,
                revoked_at,
                tenant_id,
                user_id
            )
            VALUES (
                ?, ?, ?, NULL, NULL, ?, ?
            )
            """,
            (
                normalized_uuid,
                credential_hash,
                now,
                int(tenant_id),
                int(user["id"]),
            ),
        )
    else:
        connection.execute(
            """
            UPDATE offline_device_credentials
            SET
                credential_hash=?,
                created_at=?,
                last_used_at=NULL,
                revoked_at=NULL,
                tenant_id=?,
                user_id=?
            WHERE installation_uuid=?
            """,
            (
                credential_hash,
                now,
                int(tenant_id),
                int(user["id"]),
                normalized_uuid,
            ),
        )

    return SaasProvisionedDevice(
        tenant_id=int(tenant_id),
        user_id=int(user["id"]),
        username=str(user["username"]),
        installation_uuid=normalized_uuid,
        credential=credential,
    )


def resolve_device_identity(
    connection: sqlite3.Connection,
    *,
    installation_uuid: str,
    credential: str,
) -> tuple[int, int] | None:
    normalized_uuid = _normalize_uuid(
        installation_uuid
    )

    normalized_credential = _required_text(
        credential,
        field_name="credential",
    )

    row = connection.execute(
        """
        SELECT
            id,
            credential_hash,
            tenant_id,
            user_id,
            revoked_at
        FROM offline_device_credentials
        WHERE installation_uuid=?
        """,
        (normalized_uuid,),
    ).fetchone()

    if (
        row is None
        or row["revoked_at"]
        or row["tenant_id"] is None
        or row["user_id"] is None
    ):
        return None

    valid = secrets.compare_digest(
        str(row["credential_hash"]),
        _hash_secret(
            normalized_credential
        ),
    )

    if not valid:
        return None

    connection.execute(
        """
        UPDATE offline_device_credentials
        SET last_used_at=?
        WHERE id=?
        """,
        (
            _utc_timestamp(),
            int(row["id"]),
        ),
    )

    return (
        int(row["tenant_id"]),
        int(row["user_id"]),
    )


__all__ = [
    "InactiveUserError",
    "InvalidLoginError",
    "SaasProvisionedDevice",
    "SaasProvisioningError",
    "TenantError",
    "provision_device_by_login",
    "resolve_device_identity",
]
