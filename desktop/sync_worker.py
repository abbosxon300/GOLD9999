from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Mapping

from services.offline.sync_runner import (
    run_pending_sync,
)


DEFAULT_INTERVAL_SECONDS = 15
DEFAULT_SYNC_LIMIT = 100


def _positive_integer(
    value: object,
    *,
    field_name: str,
) -> int:
    if isinstance(value, bool):
        raise TypeError(
            f"{field_name} integer bo‘lishi kerak"
        )

    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} integer bo‘lishi kerak"
        ) from exc

    if normalized <= 0:
        raise ValueError(
            f"{field_name} musbat bo‘lishi kerak"
        )

    return normalized


def load_env_file(
    path: Path,
) -> dict[str, str]:
    if not isinstance(path, Path):
        raise TypeError(
            "path Path bo‘lishi kerak"
        )

    if not path.is_file():
        raise FileNotFoundError(
            f"Sync config topilmadi: {path}"
        )

    values: dict[str, str] = {}

    for raw_line in path.read_text(
        encoding="utf-8-sig"
    ).splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            raise ValueError(
                f"Sync config qatori noto‘g‘ri: {line}"
            )

        key, value = line.split("=", 1)

        key = key.strip()
        value = value.strip()

        if not key or not value:
            raise ValueError(
                "Sync config kalit yoki qiymat bo‘sh"
            )

        values[key] = value

    return values


def apply_environment(
    values: Mapping[str, str],
) -> None:
    required = (
        "OFFLINE_SYNC_URL",
        "OFFLINE_SYNC_TOKEN",
        "OFFLINE_DEVICE_UUID",
    )

    for key in required:
        value = str(values.get(key, "")).strip()

        if not value:
            raise RuntimeError(
                f"{key} sync configda yo‘q"
            )

        os.environ[key] = value


class WindowsSyncWorker:
    def __init__(
        self,
        *,
        env_file: Path,
        interval_seconds: int = (
            DEFAULT_INTERVAL_SECONDS
        ),
        limit: int = DEFAULT_SYNC_LIMIT,
    ) -> None:
        self.env_file = env_file
        self.interval_seconds = _positive_integer(
            interval_seconds,
            field_name="interval_seconds",
        )
        self.limit = _positive_integer(
            limit,
            field_name="limit",
        )

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return (
            self._thread is not None
            and self._thread.is_alive()
        )

    def start(self) -> None:
        if self.is_running:
            return

        values = load_env_file(
            self.env_file
        )

        apply_environment(values)

        self.interval_seconds = (
            _positive_integer(
                values.get(
                    "OFFLINE_SYNC_INTERVAL",
                    self.interval_seconds,
                ),
                field_name=(
                    "OFFLINE_SYNC_INTERVAL"
                ),
            )
        )

        self.limit = _positive_integer(
            values.get(
                "OFFLINE_SYNC_LIMIT",
                self.limit,
            ),
            field_name="OFFLINE_SYNC_LIMIT",
        )

        self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._run_loop,
            name="Gold9999AutoSync",
            daemon=True,
        )

        self._thread.start()

    def stop(
        self,
        *,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._stop_event.set()

        thread = self._thread

        if thread is not None:
            thread.join(timeout_seconds)

    def run_once(self) -> int:
        return int(
            run_pending_sync(
                limit=self.limit
            )
        )

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                synced = self.run_once()
            except Exception as exc:
                print(
                    "WINDOWS AUTO SYNC FAILED:",
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
            else:
                print(
                    "WINDOWS AUTO SYNC OK:",
                    f"synced={synced}",
                    flush=True,
                )

            self._stop_event.wait(
                self.interval_seconds
            )


def create_default_worker(
    *,
    data_directory: Path,
) -> WindowsSyncWorker:
    if not isinstance(data_directory, Path):
        data_directory = Path(
            data_directory
        )

    env_file = (
        data_directory
        / "offline.env"
    )

    return WindowsSyncWorker(
        env_file=env_file,
    )


__all__ = [
    "DEFAULT_INTERVAL_SECONDS",
    "DEFAULT_SYNC_LIMIT",
    "WindowsSyncWorker",
    "apply_environment",
    "create_default_worker",
    "load_env_file",
]
