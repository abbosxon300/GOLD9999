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


def _windows_helper_path(
    installer: Path,
) -> Path:
    return installer.parent / "run-update.cmd"


def _quote_cmd_value(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _write_windows_update_helper(
    installer: Path,
    arguments: tuple[str, ...],
) -> Path:
    helper = _windows_helper_path(installer)

    trace_path = (
        installer.parent
        / "update-helper.log"
    )

    command_parts = [
        _quote_cmd_value(str(installer)),
    ]

    for argument in arguments[1:]:
        if (
            argument.startswith('/LOG="')
            and argument.endswith('"')
        ):
            command_parts.append(argument)
        else:
            command_parts.append(
                _quote_cmd_value(argument)
            )

    installer_command = " ".join(
        command_parts
    )

    helper_text = (
        "@echo off\r\n"
        "setlocal\r\n"
        f"set \"TRACE={trace_path}\"\r\n"
        "> \"%TRACE%\" echo UPDATE HELPER STARTED\r\n"
        ">> \"%TRACE%\" echo Waiting for Gold9999 to close...\r\n"
        "timeout /t 3 /nobreak >nul\r\n"
        ">> \"%TRACE%\" echo Starting installer...\r\n"
        f"{installer_command}\r\n"
        "set \"INSTALL_EXIT=%ERRORLEVEL%\"\r\n"
        ">> \"%TRACE%\" echo INSTALL EXIT=%INSTALL_EXIT%\r\n"
        "if not \"%INSTALL_EXIT%\"==\"0\" (\r\n"
        "  >> \"%TRACE%\" echo INSTALL FAILED - FILES KEPT\r\n"
        "  exit /b %INSTALL_EXIT%\r\n"
        ")\r\n"
        ">> \"%TRACE%\" echo INSTALL SUCCEEDED\r\n"
        f"del /f /q {_quote_cmd_value(str(installer))} "
        ">nul 2>&1\r\n"
        ">> \"%TRACE%\" echo INSTALLER REMOVED\r\n"
        "exit /b 0\r\n"
    )

    helper.write_text(
        helper_text,
        encoding="utf-8",
        newline="",
    )

    return helper


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
            "Installer fayli bo?sh"
        )

    if not callable(runner):
        raise TypeError(
            "runner callable bo?lishi kerak"
        )

    arguments = build_silent_installer_arguments(
        installer,
        log_path=log_path,
    )

    if os.name == "nt":
        helper = _write_windows_update_helper(
            installer,
            arguments,
        )

        command = [
            "cmd.exe",
            "/d",
            "/s",
            "/c",
            str(helper),
        ]

        cwd = str(helper.parent)
    else:
        command = list(arguments)
        cwd = str(installer.parent)

    try:
        process = runner(
            command,
            cwd=cwd,
            close_fds=True,
            creationflags=(
                _windows_creation_flags()
            ),
        )
    except OSError as exc:
        raise UpdateInstallerError(
            "Update installerini ishga "
            f"tushirib bo?lmadi: {exc}"
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
            "Installer helper process ID olinmadi"
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
