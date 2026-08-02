from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
from typing import Any


class UpdateInstallerError(RuntimeError):
    """Update installerini ishga tushirishdagi xato."""


@dataclass(frozen=True, slots=True)
class InstallerLaunchResult:
    installer_path: Path
    arguments: tuple[str, ...]
    process_id: int


ProcessRunner = Callable[..., Any]


def build_silent_installer_arguments(
    installer_path: Path,
    *,
    log_path: Path | None = None,
) -> tuple[str, ...]:
    installer = Path(
        installer_path
    ).expanduser().resolve()

    if installer.suffix.lower() != ".exe":
        raise ValueError(
            "Installer .exe fayl bo‘lishi kerak"
        )

    arguments = [
        str(installer),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/CLOSEAPPLICATIONS",
        "/FORCECLOSEAPPLICATIONS",
    ]

    if log_path is not None:
        log_file = Path(
            log_path
        ).expanduser().resolve()

        log_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        arguments.append(
            f'/LOG="{log_file}"'
        )

    return tuple(arguments)


def _windows_creation_flags() -> int:
    if os.name != "nt":
        return 0

    return (
        int(
            getattr(
                subprocess,
                "DETACHED_PROCESS",
                0,
            )
        )
        | int(
            getattr(
                subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0,
            )
        )
    )


def launch_silent_installer(
    installer_path: Path,
    *,
    log_path: Path | None = None,
    runner: ProcessRunner = subprocess.Popen,
) -> InstallerLaunchResult:
    installer = Path(
        installer_path
    ).expanduser().resolve()

    if not installer.is_file():
        raise UpdateInstallerError(
            f"Installer topilmadi: {installer}"
        )

    if installer.stat().st_size <= 0:
        raise UpdateInstallerError(
            "Installer fayli bo‘sh"
        )

    if not callable(runner):
        raise TypeError(
            "runner callable bo‘lishi kerak"
        )

    arguments = build_silent_installer_arguments(
        installer,
        log_path=log_path,
    )

    try:
        process = runner(
            list(arguments),
            cwd=str(installer.parent),
            close_fds=True,
            creationflags=(
                _windows_creation_flags()
            ),
        )
    except OSError as exc:
        raise UpdateInstallerError(
            "Update installerini ishga "
            f"tushirib bo‘lmadi: {exc}"
        ) from exc

    process_id = int(
        getattr(
            process,
            "pid",
            0,
        )
    )

    if process_id <= 0:
        raise UpdateInstallerError(
            "Installer process ID olinmadi"
        )

    return InstallerLaunchResult(
        installer_path=installer,
        arguments=arguments,
        process_id=process_id,
    )


__all__ = [
    "InstallerLaunchResult",
    "UpdateInstallerError",
    "build_silent_installer_arguments",
    "launch_silent_installer",
]
