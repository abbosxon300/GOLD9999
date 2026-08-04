from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
import sqlite3
from typing import Any


DEFAULT_TOKEN_DAYS = 30


@dataclass(frozen=True, slots=True)
class RememberToken:
    raw_token: str
    expires_at: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime) -> str:
    return value.replace(
        microsecond=0
    ).isoformat()


def hash_token(raw_token: str) -> str:
    value = str(raw_token or "").strip()

    if not value:
        raise ValueError(
            "Remember token bo?sh bo?lishi mumkin emas"
        )

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def issue_token(
    connection: sqlite3.Connection,
    *,
    user_id: int,
    device_id: str,
    valid_days: int = DEFAULT_TOKEN_DAYS,
) -> RememberToken:
    if int(user_id) <= 0:
        raise ValueError(
            "user_id musbat bo?lishi kerak"
        )

    normalized_device = str(
        device_id or ""
    ).strip()

    if not normalized_device:
        raise ValueError(
            "device_id bo?sh bo?lishi mumkin emas"
        )

    if int(valid_days) <= 0:
        raise ValueError(
            "valid_days musbat bo?lishi kerak"
        )

    raw_token = secrets.token_urlsafe(48)
    token_hash = hash_token(raw_token)

    expires_at = _utc_now() + timedelta(
        days=int(valid_days)
    )

    connection.execute(
        """
        INSERT INTO remember_tokens (
            user_id,
            token_hash,
            device_id,
            expires_at,
            revoked_at,
            last_used_at
        )
        VALUES (?, ?, ?, ?, NULL, NULL)
        """,
        (
            int(user_id),
            token_hash,
            normalized_device,
            _to_iso(expires_at),
        ),
    )

    return RememberToken(
        raw_token=raw_token,
        expires_at=_to_iso(expires_at),
    )


def validate_token(
    connection: sqlite3.Connection,
    *,
    raw_token: str,
    device_id: str,
) -> dict[str, Any] | None:
    normalized_device = str(
        device_id or ""
    ).strip()

    if not normalized_device:
        return None

    candidate_hash = hash_token(raw_token)

    row = connection.execute(
        """
        SELECT
            rt.id,
            rt.user_id,
            rt.token_hash,
            rt.device_id,
            rt.expires_at,
            rt.revoked_at,
            u.username,
            u.full_name,
            u.role,
            u.is_active
        FROM remember_tokens AS rt
        JOIN users AS u
          ON u.id = rt.user_id
        WHERE rt.device_id = ?
          AND rt.revoked_at IS NULL
        ORDER BY rt.id DESC
        """,
        (normalized_device,),
    ).fetchall()

    now = _utc_now()

    for item in row:
        stored_hash = str(
            item["token_hash"] or ""
        )

        if not hmac.compare_digest(
            stored_hash,
            candidate_hash,
        ):
            continue

        expires_at = datetime.fromisoformat(
            str(item["expires_at"])
        )

        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(
                tzinfo=timezone.utc
            )

        if expires_at <= now:
            return None

        if int(item["is_active"] or 0) != 1:
            return None

        connection.execute(
            """
            UPDATE remember_tokens
            SET last_used_at = ?
            WHERE id = ?
            """,
            (
                _to_iso(now),
                int(item["id"]),
            ),
        )

        return {
            "token_id": int(item["id"]),
            "user_id": int(item["user_id"]),
            "username": item["username"],
            "full_name": (
                item["full_name"]
                or item["username"]
            ),
            "role": item["role"],
            "expires_at": item["expires_at"],
        }

    return None


def revoke_token(
    connection: sqlite3.Connection,
    *,
    raw_token: str,
    device_id: str,
) -> bool:
    token_hash = hash_token(raw_token)

    cursor = connection.execute(
        """
        UPDATE remember_tokens
        SET revoked_at = ?
        WHERE token_hash = ?
          AND device_id = ?
          AND revoked_at IS NULL
        """,
        (
            _to_iso(_utc_now()),
            token_hash,
            str(device_id or "").strip(),
        ),
    )

    return int(cursor.rowcount or 0) > 0


def revoke_all_for_user(
    connection: sqlite3.Connection,
    *,
    user_id: int,
) -> int:
    cursor = connection.execute(
        """
        UPDATE remember_tokens
        SET revoked_at = ?
        WHERE user_id = ?
          AND revoked_at IS NULL
        """,
        (
            _to_iso(_utc_now()),
            int(user_id),
        ),
    )

    return int(cursor.rowcount or 0)
