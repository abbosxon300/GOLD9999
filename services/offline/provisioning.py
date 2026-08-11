from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID


DEFAULT_ACTIVATION_TTL_MINUTES = 30
ACTIVATION_CODE_BYTES = 9
DEVICE_CREDENTIAL_BYTES = 48


class ProvisioningError(RuntimeError):
    pass


class InvalidActivationCodeError(ProvisioningError):
    pass


class ExpiredActivationCodeError(ProvisioningError):
    pass


class UsedActivationCodeError(ProvisioningError):
    pass


class RevokedActivationCodeError(ProvisioningError):
    pass


class DeviceCredentialError(ProvisioningError):
    pass


@dataclass(frozen=True, slots=True)
class IssuedActivationCode:
    code: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class ProvisionedDevice:
    installation_uuid: str
    credential: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(
        timespec="seconds"
    )


def _hash_secret(value: str) -> str:
    normalized = str(value or "").strip()

    if not normalized:
        raise ValueError("Secret bo‘sh bo‘lishi mumkin emas")

    return hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()


def _normalize_installation_uuid(value: str) -> str:
    normalized = str(value or "").strip()

    try:
        parsed = UUID(normalized)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ProvisioningError(
            "installation_uuid noto‘g‘ri"
        ) from exc

    return str(parsed)


def issue_activation_code(
    connection: sqlite3.Connection,
    *,
    ttl_minutes: int = DEFAULT_ACTIVATION_TTL_MINUTES,
) -> IssuedActivationCode:
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError(
            "connection sqlite3.Connection bo‘lishi kerak"
        )

    normalized_ttl = int(ttl_minutes)

    if normalized_ttl <= 0:
        raise ValueError("ttl_minutes musbat bo‘lishi kerak")

    raw_code = secrets.token_urlsafe(
        ACTIVATION_CODE_BYTES
    ).replace("-", "").replace("_", "").upper()

    code = f"G9-{raw_code[:6]}-{raw_code[6:12]}"

    now = _utc_now()
    expires_at = now + timedelta(
        minutes=normalized_ttl
    )

    connection.execute(
        """
        INSERT INTO offline_activation_codes(
            code_hash,
            created_at,
            expires_at,
            used_at,
            used_by_installation_uuid,
            is_revoked
        )
        VALUES (?, ?, ?, NULL, NULL, 0)
        """,
        (
            _hash_secret(code),
            _timestamp(now),
            _timestamp(expires_at),
        ),
    )

    return IssuedActivationCode(
        code=code,
        expires_at=_timestamp(expires_at),
    )


def provision_device(
    connection: sqlite3.Connection,
    *,
    activation_code: str,
    installation_uuid: str,
) -> ProvisionedDevice:
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError(
            "connection sqlite3.Connection bo‘lishi kerak"
        )

    normalized_uuid = _normalize_installation_uuid(
        installation_uuid
    )
    code_hash = _hash_secret(activation_code)

    row = connection.execute(
        """
        SELECT
            id,
            expires_at,
            used_at,
            is_revoked
        FROM offline_activation_codes
        WHERE code_hash=?
        """,
        (code_hash,),
    ).fetchone()

    if row is None:
        raise InvalidActivationCodeError(
            "Aktivatsiya kodi noto‘g‘ri"
        )

    if int(row["is_revoked"] or 0):
        raise RevokedActivationCodeError(
            "Aktivatsiya kodi bekor qilingan"
        )

    if row["used_at"]:
        raise UsedActivationCodeError(
            "Aktivatsiya kodi avval ishlatilgan"
        )

    expires_at = datetime.fromisoformat(
        str(row["expires_at"])
    )

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(
            tzinfo=timezone.utc
        )

    now = _utc_now()

    if expires_at <= now:
        raise ExpiredActivationCodeError(
            "Aktivatsiya kodi muddati tugagan"
        )

    credential = secrets.token_urlsafe(
        DEVICE_CREDENTIAL_BYTES
    )
    credential_hash = _hash_secret(
        credential
    )

    savepoint = "offline_provision_device"

    connection.execute(
        f"SAVEPOINT {savepoint}"
    )

    try:
        existing = connection.execute(
            """
            SELECT id
            FROM offline_device_credentials
            WHERE installation_uuid=?
            """,
            (normalized_uuid,),
        ).fetchone()

        if existing is None:
            connection.execute(
                """
                INSERT INTO offline_device_credentials(
                    installation_uuid,
                    credential_hash,
                    created_at,
                    last_used_at,
                    revoked_at
                )
                VALUES (?, ?, ?, NULL, NULL)
                """,
                (
                    normalized_uuid,
                    credential_hash,
                    _timestamp(now),
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
                    revoked_at=NULL
                WHERE installation_uuid=?
                """,
                (
                    credential_hash,
                    _timestamp(now),
                    normalized_uuid,
                ),
            )

        connection.execute(
            """
            UPDATE offline_activation_codes
            SET
                used_at=?,
                used_by_installation_uuid=?
            WHERE id=?
              AND used_at IS NULL
              AND is_revoked=0
            """,
            (
                _timestamp(now),
                normalized_uuid,
                int(row["id"]),
            ),
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

    return ProvisionedDevice(
        installation_uuid=normalized_uuid,
        credential=credential,
    )


def validate_device_credential(
    connection: sqlite3.Connection,
    *,
    installation_uuid: str,
    credential: str,
) -> bool:
    normalized_uuid = _normalize_installation_uuid(
        installation_uuid
    )

    row = connection.execute(
        """
        SELECT
            id,
            credential_hash,
            revoked_at
        FROM offline_device_credentials
        WHERE installation_uuid=?
        """,
        (normalized_uuid,),
    ).fetchone()

    if row is None or row["revoked_at"]:
        return False

    candidate_hash = _hash_secret(
        credential
    )

    valid = hmac.compare_digest(
        str(row["credential_hash"]),
        candidate_hash,
    )

    if valid:
        connection.execute(
            """
            UPDATE offline_device_credentials
            SET last_used_at=?
            WHERE id=?
            """,
            (
                _timestamp(_utc_now()),
                int(row["id"]),
            ),
        )

    return valid


__all__ = [
    "DEFAULT_ACTIVATION_TTL_MINUTES",
    "DeviceCredentialError",
    "ExpiredActivationCodeError",
    "InvalidActivationCodeError",
    "IssuedActivationCode",
    "ProvisionedDevice",
    "ProvisioningError",
    "RevokedActivationCodeError",
    "UsedActivationCodeError",
    "issue_activation_code",
    "provision_device",
    "validate_device_credential",
]
