from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from desktop.update_client import (
    UpdateCheckResult,
    UpdateClient,
)
from desktop.update_downloader import (
    InstallerDownloader,
)
from desktop.update_installer import (
    InstallerLaunchResult,
    launch_silent_installer,
)
from desktop.update_manifest import (
    UpdateManifest,
)
from services.runtime_paths import (
    data_directory,
)


INSTALLER_FILENAME = "Gold9999Setup.exe"
UPDATE_DIRECTORY_NAME = "updates"
UPDATE_LOG_FILENAME = "update-install.log"


class UpdateChecker(Protocol):
    def check(self) -> UpdateCheckResult:
        ...


class UpdateDownloader(Protocol):
    def download(
        self,
        manifest: UpdateManifest,
        destination: Path,
    ) -> Path:
        ...


@dataclass(frozen=True, slots=True)
class PreparedUpdate:
    manifest: UpdateManifest
    installer_path: Path
    log_path: Path


@dataclass(frozen=True, slots=True)
class UpdateExecution:
    prepared: PreparedUpdate
    launch: InstallerLaunchResult


class DesktopUpdater:
    def __init__(
        self,
        checker: UpdateChecker,
        downloader: UpdateDownloader,
        *,
        update_directory: Path | None = None,
    ) -> None:
        if not callable(
            getattr(
                checker,
                "check",
                None,
            )
        ):
            raise TypeError(
                "checker check() metodiga ega "
                "bo‘lishi kerak"
            )

        if not callable(
            getattr(
                downloader,
                "download",
                None,
            )
        ):
            raise TypeError(
                "downloader download() metodiga "
                "ega bo‘lishi kerak"
            )

        selected_directory = (
            Path(update_directory)
            if update_directory is not None
            else (
                data_directory()
                / UPDATE_DIRECTORY_NAME
            )
        )

        self._checker = checker
        self._downloader = downloader
        self._update_directory = (
            selected_directory
            .expanduser()
            .resolve()
        )

    @property
    def update_directory(self) -> Path:
        return self._update_directory

    def check_for_update(
        self,
    ) -> UpdateCheckResult:
        return self._checker.check()

    def prepare_update(
        self,
        result: UpdateCheckResult,
    ) -> PreparedUpdate | None:
        if not isinstance(
            result,
            UpdateCheckResult,
        ):
            raise TypeError(
                "result UpdateCheckResult "
                "bo‘lishi kerak"
            )

        if not result.update_available:
            return None

        self._update_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        installer_path = (
            self._update_directory
            / INSTALLER_FILENAME
        )

        downloaded = self._downloader.download(
            result.manifest,
            installer_path,
        )

        downloaded = (
            Path(downloaded)
            .expanduser()
            .resolve()
        )

        if downloaded != installer_path:
            raise RuntimeError(
                "Downloader kutilmagan fayl "
                "manzilini qaytardi"
            )

        if not downloaded.is_file():
            raise RuntimeError(
                "Yuklangan installer topilmadi"
            )

        log_path = (
            self._update_directory
            / UPDATE_LOG_FILENAME
        )

        return PreparedUpdate(
            manifest=result.manifest,
            installer_path=downloaded,
            log_path=log_path,
        )

    def launch_update(
        self,
        prepared: PreparedUpdate,
    ) -> UpdateExecution:
        if not isinstance(
            prepared,
            PreparedUpdate,
        ):
            raise TypeError(
                "prepared PreparedUpdate "
                "bo‘lishi kerak"
            )

        launch = launch_silent_installer(
            prepared.installer_path,
            log_path=prepared.log_path,
        )

        return UpdateExecution(
            prepared=prepared,
            launch=launch,
        )


def create_desktop_updater(
    manifest_url: str,
    *,
    update_directory: Path | None = None,
) -> DesktopUpdater:
    return DesktopUpdater(
        checker=UpdateClient(
            manifest_url
        ),
        downloader=InstallerDownloader(),
        update_directory=update_directory,
    )


__all__ = [
    "DesktopUpdater",
    "INSTALLER_FILENAME",
    "PreparedUpdate",
    "UPDATE_DIRECTORY_NAME",
    "UPDATE_LOG_FILENAME",
    "UpdateExecution",
    "create_desktop_updater",
]
