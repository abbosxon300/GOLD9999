from __future__ import annotations

import os
import platform
import socket
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.db import get_db


APP_METADATA_ROW_ID = 1
DEFAULT_APP_VERSION = "unknown"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTALLATION_STATE_DIR = PROJECT_ROOT / "var"
INSTALLATION_ID_PATH = (
    INSTALLATION_STATE_DIR
    / "installation_uuid"
)


@dataclass(frozen=True)
class DeviceIdentity:
    database_uuid: str
    installation_uuid: str
    hostname: str
    platform: str
    machine: str
    python_version: str
    app_version: str


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _clean_text(
    value: Any,
    *,
    fallback: str = "",
) -> str:
    if value is None:
        return fallback

    result = str(value).strip()

    return result or fallback


def _normalize_uuid(
    value: Any,
) -> str:
    text = _clean_text(value)

    if not text:
        raise ValueError(
            "UUID bo‘sh bo‘lishi mumkin emas."
        )

    return str(uuid.UUID(text))


def _runtime_hostname() -> str:
    try:
        return _clean_text(
            socket.gethostname(),
            fallback="unknown",
        )
    except Exception:
        return "unknown"


def _runtime_platform() -> str:
    try:
        return _clean_text(
            platform.system(),
            fallback="unknown",
        )
    except Exception:
        return "unknown"


def _runtime_machine() -> str:
    try:
        return _clean_text(
            platform.machine(),
            fallback="unknown",
        )
    except Exception:
        return "unknown"


def _runtime_python_version() -> str:
    return _clean_text(
        platform.python_version(),
        fallback=(
            f"{sys.version_info.major}."
            f"{sys.version_info.minor}."
            f"{sys.version_info.micro}"
        ),
    )


def _write_installation_uuid_atomic(
    installation_uuid: str,
) -> None:
    INSTALLATION_STATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_path = INSTALLATION_ID_PATH.with_name(
        (
            f".{INSTALLATION_ID_PATH.name}."
            f"{os.getpid()}.tmp"
        )
    )

    try:
        with temp_path.open(
            "x",
            encoding="utf-8",
        ) as file:
            file.write(
                installation_uuid + "\n"
            )
            file.flush()
            os.fsync(file.fileno())

        try:
            temp_path.replace(
                INSTALLATION_ID_PATH
            )
        except OSError:
            if not INSTALLATION_ID_PATH.exists():
                raise

    finally:
        try:
            temp_path.unlink(
                missing_ok=True
            )
        except OSError:
            pass


def get_local_installation_uuid() -> str:
    try:
        raw_value = INSTALLATION_ID_PATH.read_text(
            encoding="utf-8"
        )
    except FileNotFoundError:
        raw_value = ""

    if raw_value.strip():
        try:
            return _normalize_uuid(
                raw_value
            )
        except ValueError as exc:
            raise RuntimeError(
                "Installation UUID fayli buzilgan: "
                f"{INSTALLATION_ID_PATH}"
            ) from exc

    generated_uuid = _new_uuid()

    _write_installation_uuid_atomic(
        generated_uuid
    )

    try:
        stored_value = (
            INSTALLATION_ID_PATH.read_text(
                encoding="utf-8"
            )
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Installation UUID fayli yaratilmadi."
        ) from exc

    try:
        return _normalize_uuid(
            stored_value
        )
    except ValueError as exc:
        raise RuntimeError(
            "Yaratilgan installation UUID noto‘g‘ri."
        ) from exc


def ensure_database_identity(
    connection=None,
) -> str:
    db = connection or get_db()

    row = db.execute(
        """
        SELECT database_uuid
        FROM app_metadata
        WHERE id=?
        """,
        (APP_METADATA_ROW_ID,),
    ).fetchone()

    if row is not None:
        return _normalize_uuid(
            row["database_uuid"]
        )

    database_uuid = _new_uuid()

    db.execute(
        """
        INSERT OR IGNORE INTO app_metadata(
            id,
            database_uuid
        )
        VALUES (?, ?)
        """,
        (
            APP_METADATA_ROW_ID,
            database_uuid,
        ),
    )

    row = db.execute(
        """
        SELECT database_uuid
        FROM app_metadata
        WHERE id=?
        """,
        (APP_METADATA_ROW_ID,),
    ).fetchone()

    if row is None:
        raise RuntimeError(
            "Database identity yaratilmadi."
        )

    return _normalize_uuid(
        row["database_uuid"]
    )


def _find_installation_by_uuid(
    connection,
    installation_uuid: str,
):
    return connection.execute(
        """
        SELECT
            id,
            installation_uuid,
            database_uuid,
            hostname,
            platform,
            machine,
            python_version,
            app_version,
            is_active,
            created_at,
            last_seen_at
        FROM app_installations
        WHERE installation_uuid=?
        LIMIT 1
        """,
        (installation_uuid,),
    ).fetchone()


def _find_legacy_runtime_installation(
    connection,
    *,
    database_uuid: str,
    hostname: str,
    platform_name: str,
    machine: str,
):
    return connection.execute(
        """
        SELECT
            id,
            installation_uuid,
            database_uuid,
            hostname,
            platform,
            machine,
            python_version,
            app_version,
            is_active,
            created_at,
            last_seen_at
        FROM app_installations
        WHERE database_uuid=?
          AND hostname=?
          AND platform=?
          AND machine=?
          AND is_active=1
        ORDER BY id
        LIMIT 1
        """,
        (
            database_uuid,
            hostname,
            platform_name,
            machine,
        ),
    ).fetchone()


def _adopt_existing_installation_uuid(
    connection,
    *,
    database_uuid: str,
    hostname: str,
    platform_name: str,
    machine: str,
) -> str | None:
    if INSTALLATION_ID_PATH.exists():
        return None

    row = _find_legacy_runtime_installation(
        connection,
        database_uuid=database_uuid,
        hostname=hostname,
        platform_name=platform_name,
        machine=machine,
    )

    if row is None:
        return None

    installation_uuid = _normalize_uuid(
        row["installation_uuid"]
    )

    _write_installation_uuid_atomic(
        installation_uuid
    )

    return installation_uuid


def _to_identity(
    row,
) -> DeviceIdentity:
    return DeviceIdentity(
        database_uuid=_normalize_uuid(
            row["database_uuid"]
        ),
        installation_uuid=_normalize_uuid(
            row["installation_uuid"]
        ),
        hostname=_clean_text(
            row["hostname"],
            fallback="unknown",
        ),
        platform=_clean_text(
            row["platform"],
            fallback="unknown",
        ),
        machine=_clean_text(
            row["machine"],
            fallback="unknown",
        ),
        python_version=_clean_text(
            row["python_version"],
            fallback="unknown",
        ),
        app_version=_clean_text(
            row["app_version"],
            fallback=DEFAULT_APP_VERSION,
        ),
    )


def ensure_installation_identity(
    connection=None,
    *,
    app_version: str | None = None,
) -> DeviceIdentity:
    db = connection or get_db()

    database_uuid = ensure_database_identity(
        db
    )

    hostname = _runtime_hostname()
    platform_name = _runtime_platform()
    machine = _runtime_machine()
    python_version = _runtime_python_version()

    installation_uuid = (
        _adopt_existing_installation_uuid(
            db,
            database_uuid=database_uuid,
            hostname=hostname,
            platform_name=platform_name,
            machine=machine,
        )
    )

    if installation_uuid is None:
        installation_uuid = (
            get_local_installation_uuid()
        )

    row = _find_installation_by_uuid(
        db,
        installation_uuid,
    )

    resolved_app_version = (
        _clean_text(app_version)
        if app_version is not None
        else None
    )

    if row is None:
        db.execute(
            """
            INSERT INTO app_installations(
                installation_uuid,
                database_uuid,
                hostname,
                platform,
                machine,
                python_version,
                app_version,
                is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                installation_uuid,
                database_uuid,
                hostname,
                platform_name,
                machine,
                python_version,
                (
                    resolved_app_version
                    or DEFAULT_APP_VERSION
                ),
            ),
        )

    else:
        if (
            _normalize_uuid(
                row["database_uuid"]
            )
            != database_uuid
        ):
            raise RuntimeError(
                "Installation UUID boshqa database "
                "identity bilan bog‘langan."
            )

        if resolved_app_version is None:
            db.execute(
                """
                UPDATE app_installations
                SET
                    hostname=?,
                    platform=?,
                    machine=?,
                    python_version=?,
                    is_active=1,
                    last_seen_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    hostname,
                    platform_name,
                    machine,
                    python_version,
                    row["id"],
                ),
            )
        else:
            db.execute(
                """
                UPDATE app_installations
                SET
                    hostname=?,
                    platform=?,
                    machine=?,
                    python_version=?,
                    app_version=?,
                    is_active=1,
                    last_seen_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    hostname,
                    platform_name,
                    machine,
                    python_version,
                    resolved_app_version,
                    row["id"],
                ),
            )

    row = _find_installation_by_uuid(
        db,
        installation_uuid,
    )

    if row is None:
        raise RuntimeError(
            "Installation identity yaratilmadi."
        )

    return _to_identity(row)


def get_device_identity(
    connection=None,
) -> DeviceIdentity | None:
    db = connection or get_db()

    database_row = db.execute(
        """
        SELECT database_uuid
        FROM app_metadata
        WHERE id=?
        """,
        (APP_METADATA_ROW_ID,),
    ).fetchone()

    if database_row is None:
        return None

    try:
        installation_uuid = (
            get_local_installation_uuid()
        )
    except RuntimeError:
        return None

    row = _find_installation_by_uuid(
        db,
        installation_uuid,
    )

    if row is None:
        return None

    if (
        _normalize_uuid(
            row["database_uuid"]
        )
        != _normalize_uuid(
            database_row["database_uuid"]
        )
    ):
        return None

    return _to_identity(row)
