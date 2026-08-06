from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from services.runtime_paths import (
    installation_state_directory,
)


BOOTSTRAP_STATE_FILENAME = (
    "first_install_bootstrap.json"
)
BOOTSTRAP_STATE_SCHEMA_VERSION = 1


class FirstInstallStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class FirstInstallState:
    completed: bool
    schema_version: int
    completed_at: str
    server_database_uuid: str
    users: int
    agents: int
    categories: int
    products: int


def bootstrap_state_path() -> Path:
    return (
        installation_state_directory()
        / BOOTSTRAP_STATE_FILENAME
    )


def _required_text(
    value: object,
    *,
    field_name: str,
) -> str:
    if not isinstance(value, str):
        raise FirstInstallStateError(
            f"{field_name} matn bo‘lishi kerak"
        )

    normalized = value.strip()

    if not normalized:
        raise FirstInstallStateError(
            f"{field_name} bo‘sh bo‘lmasligi kerak"
        )

    return normalized


def _non_negative_integer(
    value: object,
    *,
    field_name: str,
) -> int:
    if isinstance(value, bool):
        raise FirstInstallStateError(
            f"{field_name} integer bo‘lishi kerak"
        )

    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise FirstInstallStateError(
            f"{field_name} integer bo‘lishi kerak"
        ) from exc

    if normalized < 0:
        raise FirstInstallStateError(
            f"{field_name} manfiy bo‘lmasligi kerak"
        )

    return normalized


def _state_from_mapping(
    payload: Mapping[str, Any],
) -> FirstInstallState:
    if payload.get("completed") is not True:
        raise FirstInstallStateError(
            "Bootstrap completed true bo‘lishi kerak"
        )

    schema_version = _non_negative_integer(
        payload.get("schema_version"),
        field_name="schema_version",
    )

    if (
        schema_version
        != BOOTSTRAP_STATE_SCHEMA_VERSION
    ):
        raise FirstInstallStateError(
            "Bootstrap marker schema version "
            "qo‘llab-quvvatlanmaydi"
        )

    return FirstInstallState(
        completed=True,
        schema_version=schema_version,
        completed_at=_required_text(
            payload.get("completed_at"),
            field_name="completed_at",
        ),
        server_database_uuid=_required_text(
            payload.get("server_database_uuid"),
            field_name="server_database_uuid",
        ),
        users=_non_negative_integer(
            payload.get("users"),
            field_name="users",
        ),
        agents=_non_negative_integer(
            payload.get("agents"),
            field_name="agents",
        ),
        categories=_non_negative_integer(
            payload.get("categories"),
            field_name="categories",
        ),
        products=_non_negative_integer(
            payload.get("products"),
            field_name="products",
        ),
    )


def read_first_install_state() -> (
    FirstInstallState | None
):
    path = bootstrap_state_path()

    if not path.is_file():
        return None

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8-sig"
            )
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise FirstInstallStateError(
            "Bootstrap marker o‘qilmadi"
        ) from exc

    if not isinstance(payload, Mapping):
        raise FirstInstallStateError(
            "Bootstrap marker object bo‘lishi kerak"
        )

    return _state_from_mapping(payload)


def is_first_install_bootstrap_complete() -> bool:
    try:
        return read_first_install_state() is not None
    except FirstInstallStateError:
        return False


def write_first_install_state(
    *,
    server_database_uuid: str,
    users: int,
    agents: int,
    categories: int,
    products: int,
) -> FirstInstallState:
    state = FirstInstallState(
        completed=True,
        schema_version=(
            BOOTSTRAP_STATE_SCHEMA_VERSION
        ),
        completed_at=(
            datetime.now(timezone.utc).isoformat()
        ),
        server_database_uuid=_required_text(
            server_database_uuid,
            field_name="server_database_uuid",
        ),
        users=_non_negative_integer(
            users,
            field_name="users",
        ),
        agents=_non_negative_integer(
            agents,
            field_name="agents",
        ),
        categories=_non_negative_integer(
            categories,
            field_name="categories",
        ),
        products=_non_negative_integer(
            products,
            field_name="products",
        ),
    )

    path = bootstrap_state_path()
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = json.dumps(
        asdict(state),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"

    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=(
                BOOTSTRAP_STATE_FILENAME + "."
            ),
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

            temporary_path = Path(
                handle.name
            )

        os.replace(
            temporary_path,
            path,
        )

    except OSError as exc:
        if (
            temporary_path is not None
            and temporary_path.exists()
        ):
            temporary_path.unlink(
                missing_ok=True
            )

        raise FirstInstallStateError(
            "Bootstrap marker yozilmadi"
        ) from exc

    return state


def clear_first_install_state() -> None:
    bootstrap_state_path().unlink(
        missing_ok=True
    )


__all__ = [
    "BOOTSTRAP_STATE_FILENAME",
    "BOOTSTRAP_STATE_SCHEMA_VERSION",
    "FirstInstallState",
    "FirstInstallStateError",
    "bootstrap_state_path",
    "clear_first_install_state",
    "is_first_install_bootstrap_complete",
    "read_first_install_state",
    "write_first_install_state",
]
