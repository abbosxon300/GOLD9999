from __future__ import annotations

import argparse
import fcntl
import os
import signal
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Callable, Mapping

from services.offline.sync_runner import (
    DEFAULT_LIMIT,
    run_pending_sync,
)


DEFAULT_INTERVAL_SECONDS = 15.0

ENV_SCHEDULER_INTERVAL = (
    "OFFLINE_SYNC_INTERVAL_SECONDS"
)
ENV_SCHEDULER_LIMIT = "OFFLINE_SYNC_LIMIT"
ENV_SCHEDULER_LOCK_PATH = (
    "OFFLINE_SYNC_LOCK_PATH"
)


def _project_lock_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / ".offline_sync_scheduler.lock"
    )


def _positive_integer(
    value: int,
    *,
    field_name: str,
) -> int:
    if isinstance(value, bool) or not isinstance(
        value,
        int,
    ):
        raise TypeError(
            f"{field_name} integer bo‘lishi kerak"
        )

    if value <= 0:
        raise ValueError(
            f"{field_name} musbat bo‘lishi kerak"
        )

    return value


def _positive_number(
    value: float,
    *,
    field_name: str,
) -> float:
    if isinstance(value, bool) or not isinstance(
        value,
        (int, float),
    ):
        raise TypeError(
            f"{field_name} son bo‘lishi kerak"
        )

    normalized = float(value)

    if normalized <= 0:
        raise ValueError(
            f"{field_name} musbat bo‘lishi kerak"
        )

    return normalized


@dataclass(frozen=True, slots=True)
class SchedulerConfig:
    interval_seconds: float = (
        DEFAULT_INTERVAL_SECONDS
    )
    limit: int = DEFAULT_LIMIT
    lock_path: Path = _project_lock_path()

    def __post_init__(self) -> None:
        interval_seconds = _positive_number(
            self.interval_seconds,
            field_name="interval_seconds",
        )
        limit = _positive_integer(
            self.limit,
            field_name="limit",
        )
        lock_path = Path(
            self.lock_path
        ).expanduser().resolve()

        object.__setattr__(
            self,
            "interval_seconds",
            interval_seconds,
        )
        object.__setattr__(
            self,
            "limit",
            limit,
        )
        object.__setattr__(
            self,
            "lock_path",
            lock_path,
        )

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "SchedulerConfig":
        env = (
            os.environ
            if environment is None
            else environment
        )

        interval_raw = env.get(
            ENV_SCHEDULER_INTERVAL,
            str(DEFAULT_INTERVAL_SECONDS),
        )
        limit_raw = env.get(
            ENV_SCHEDULER_LIMIT,
            str(DEFAULT_LIMIT),
        )
        lock_raw = env.get(
            ENV_SCHEDULER_LOCK_PATH,
            str(_project_lock_path()),
        )

        try:
            interval_seconds = float(interval_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{ENV_SCHEDULER_INTERVAL} "
                "musbat son bo‘lishi kerak"
            ) from exc

        try:
            limit = int(limit_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{ENV_SCHEDULER_LIMIT} "
                "musbat integer bo‘lishi kerak"
            ) from exc

        return cls(
            interval_seconds=interval_seconds,
            limit=limit,
            lock_path=Path(lock_raw),
        )


class SchedulerAlreadyRunningError(
    RuntimeError
):
    """Boshqa scheduler jarayoni ishlayotganida."""


class SchedulerProcessLock:
    def __init__(
        self,
        lock_path: Path,
    ) -> None:
        self._lock_path = Path(lock_path)
        self._handle = None

    def acquire(self) -> None:
        self._lock_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        handle = self._lock_path.open(
            "a+",
            encoding="utf-8",
        )

        try:
            fcntl.flock(
                handle.fileno(),
                fcntl.LOCK_EX
                | fcntl.LOCK_NB,
            )
        except BlockingIOError as exc:
            handle.close()
            raise SchedulerAlreadyRunningError(
                "Offline sync scheduler "
                "allaqachon ishlayapti"
            ) from exc

        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()

        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return

        try:
            fcntl.flock(
                self._handle.fileno(),
                fcntl.LOCK_UN,
            )
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(
        self,
    ) -> "SchedulerProcessLock":
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:
        self.release()


SyncCallable = Callable[..., int]


class SyncScheduler:
    def __init__(
        self,
        config: SchedulerConfig,
        *,
        sync_callable: SyncCallable = (
            run_pending_sync
        ),
    ) -> None:
        if not isinstance(
            config,
            SchedulerConfig,
        ):
            raise TypeError(
                "config SchedulerConfig "
                "bo‘lishi kerak"
            )

        if not callable(sync_callable):
            raise TypeError(
                "sync_callable callable "
                "bo‘lishi kerak"
            )

        self.config = config
        self._sync_callable = sync_callable
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run_once(self) -> int:
        return int(
            self._sync_callable(
                limit=self.config.limit
            )
        )

    def run_forever(self) -> None:
        process_lock = SchedulerProcessLock(
            self.config.lock_path
        )

        with process_lock:
            self._install_signal_handlers()

            print(
                "OFFLINE SYNC SCHEDULER STARTED:",
                f"interval={self.config.interval_seconds}",
                f"limit={self.config.limit}",
                flush=True,
            )

            while not self._stop_event.is_set():
                started_at = monotonic()

                try:
                    synced_count = self.run_once()
                except Exception as exc:
                    print(
                        "OFFLINE SYNC CYCLE FAILED:",
                        f"{type(exc).__name__}: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )
                else:
                    print(
                        "OFFLINE SYNC CYCLE OK:",
                        f"synced={synced_count}",
                        flush=True,
                    )

                elapsed = monotonic() - started_at
                wait_seconds = max(
                    0.0,
                    self.config.interval_seconds
                    - elapsed,
                )

                self._stop_event.wait(
                    wait_seconds
                )

            print(
                "OFFLINE SYNC SCHEDULER STOPPED",
                flush=True,
            )

    def _install_signal_handlers(self) -> None:
        if (
            threading.current_thread()
            is not threading.main_thread()
        ):
            return

        def request_stop(
            signum,
            frame,
        ) -> None:
            del signum, frame
            self.stop()

        signal.signal(
            signal.SIGINT,
            request_stop,
        )
        signal.signal(
            signal.SIGTERM,
            request_stop,
        )


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "GOLD9999 offline sync scheduler."
        )
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Faqat bitta sync siklini ishlatadi.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Sync intervali, sekundda.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Har sikldagi maksimal queue soni.",
    )

    return parser


def main() -> int:
    parser = _build_argument_parser()
    arguments = parser.parse_args()

    try:
        environment_config = (
            SchedulerConfig.from_environment()
        )

        config = SchedulerConfig(
            interval_seconds=(
                arguments.interval
                if arguments.interval is not None
                else environment_config.interval_seconds
            ),
            limit=(
                arguments.limit
                if arguments.limit is not None
                else environment_config.limit
            ),
            lock_path=environment_config.lock_path,
        )

        scheduler = SyncScheduler(config)

        if arguments.once:
            synced_count = scheduler.run_once()
            print(
                "OFFLINE SYNC ONCE OK:",
                f"synced={synced_count}",
            )
        else:
            scheduler.run_forever()

    except Exception as exc:
        print(
            "OFFLINE SYNC SCHEDULER FAILED:",
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_INTERVAL_SECONDS",
    "ENV_SCHEDULER_INTERVAL",
    "ENV_SCHEDULER_LIMIT",
    "ENV_SCHEDULER_LOCK_PATH",
    "SchedulerAlreadyRunningError",
    "SchedulerConfig",
    "SchedulerProcessLock",
    "SyncScheduler",
]
