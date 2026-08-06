from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from services.offline.first_install_bootstrap import (
    BootstrapResult,
    run_first_install_bootstrap,
)
from services.offline.first_install_state import (
    is_first_install_bootstrap_complete,
    write_first_install_state,
)


OFFLINE_URL_KEY = "OFFLINE_SYNC_URL"
OFFLINE_TOKEN_KEY = "OFFLINE_SYNC_TOKEN"


class FirstInstallRunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class FirstInstallRunResult:
    completed: bool
    skipped: bool
    users: int
    agents: int
    categories: int
    products: int
    server_database_uuid: str | None


def _required_text(
    value: object,
    *,
    field_name: str,
) -> str:
    if not isinstance(value, str):
        raise FirstInstallRunnerError(
            f"{field_name} matn bo‘lishi kerak"
        )

    normalized = value.strip()

    if not normalized:
        raise FirstInstallRunnerError(
            f"{field_name} bo‘sh bo‘lmasligi kerak"
        )

    return normalized


def load_offline_environment(
    env_path: str | Path,
) -> dict[str, str]:
    path = Path(env_path)

    if not path.is_file():
        raise FirstInstallRunnerError(
            f"Offline config topilmadi: {path}"
        )

    try:
        lines = path.read_text(
            encoding="utf-8-sig"
        ).splitlines()

    except OSError as exc:
        raise FirstInstallRunnerError(
            "Offline config o‘qilmadi"
        ) from exc

    result: dict[str, str] = {}

    for line_number, raw_line in enumerate(
        lines,
        start=1,
    ):
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            raise FirstInstallRunnerError(
                "Offline config qatori noto‘g‘ri: "
                f"{line_number}"
            )

        key, value = line.split("=", 1)

        normalized_key = key.strip()
        normalized_value = value.strip()

        if not normalized_key:
            raise FirstInstallRunnerError(
                "Offline config kaliti bo‘sh: "
                f"{line_number}"
            )

        result[normalized_key] = (
            normalized_value
        )

    _required_text(
        result.get(OFFLINE_URL_KEY),
        field_name=OFFLINE_URL_KEY,
    )

    _required_text(
        result.get(OFFLINE_TOKEN_KEY),
        field_name=OFFLINE_TOKEN_KEY,
    )

    return result


def run_first_install_setup(
    connection: sqlite3.Connection,
    *,
    base_url: str,
    token: str,
    state_checker: Callable[[], bool] = (
        is_first_install_bootstrap_complete
    ),
    bootstrap_runner: Callable[..., BootstrapResult] = (
        run_first_install_bootstrap
    ),
    state_writer: Callable[..., object] = (
        write_first_install_state
    ),
) -> FirstInstallRunResult:
    if not isinstance(
        connection,
        sqlite3.Connection,
    ):
        raise TypeError(
            "connection sqlite3.Connection "
            "bo‘lishi kerak"
        )

    if not callable(state_checker):
        raise TypeError(
            "state_checker callable bo‘lishi kerak"
        )

    if not callable(bootstrap_runner):
        raise TypeError(
            "bootstrap_runner callable bo‘lishi kerak"
        )

    if not callable(state_writer):
        raise TypeError(
            "state_writer callable bo‘lishi kerak"
        )

    normalized_url = _required_text(
        base_url,
        field_name="base_url",
    )

    normalized_token = _required_text(
        token,
        field_name="token",
    )

    if state_checker():
        return FirstInstallRunResult(
            completed=True,
            skipped=True,
            users=0,
            agents=0,
            categories=0,
            products=0,
            server_database_uuid=None,
        )

    try:
        result = bootstrap_runner(
            connection,
            base_url=normalized_url,
            token=normalized_token,
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    state_writer(
        server_database_uuid=(
            result.database_uuid
        ),
        users=result.users,
        agents=result.agents,
        categories=result.categories,
        products=result.products,
    )

    return FirstInstallRunResult(
        completed=True,
        skipped=False,
        users=result.users,
        agents=result.agents,
        categories=result.categories,
        products=result.products,
        server_database_uuid=(
            result.database_uuid
        ),
    )


def run_first_install_from_files(
    *,
    database_path: str | Path,
    env_path: str | Path,
) -> FirstInstallRunResult:
    normalized_database_path = Path(
        database_path
    )

    if not normalized_database_path.is_file():
        raise FirstInstallRunnerError(
            "Desktop database topilmadi: "
            f"{normalized_database_path}"
        )

    environment = load_offline_environment(
        env_path
    )

    connection = sqlite3.connect(
        normalized_database_path
    )
    connection.row_factory = sqlite3.Row

    try:
        connection.execute(
            "PRAGMA foreign_keys=ON"
        )

        return run_first_install_setup(
            connection,
            base_url=environment[
                OFFLINE_URL_KEY
            ],
            token=environment[
                OFFLINE_TOKEN_KEY
            ],
        )

    finally:
        connection.close()


__all__ = [
    "OFFLINE_TOKEN_KEY",
    "OFFLINE_URL_KEY",
    "FirstInstallRunResult",
    "FirstInstallRunnerError",
    "load_offline_environment",
    "run_first_install_from_files",
    "run_first_install_setup",
]
