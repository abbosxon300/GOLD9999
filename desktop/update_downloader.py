from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import (
    HTTPError,
    URLError,
)
from urllib.parse import urlparse
from urllib.request import (
    Request,
    urlopen,
)

from desktop.update_manifest import (
    UpdateManifest,
    verify_installer,
)


DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_INSTALLER_BYTES = 250 * 1024 * 1024
READ_BLOCK_SIZE = 1024 * 1024


class UpdateDownloadError(RuntimeError):
    """Installer yuklashdagi umumiy xato."""


class UpdateDownloadTransportError(UpdateDownloadError):
    """HTTPS transport xatosi."""


class UpdateDownloadResponseError(UpdateDownloadError):
    """Server javobi noto‘g‘ri."""


class UpdateChecksumError(UpdateDownloadError):
    """Installer SHA-256 tekshiruvidan o‘tmadi."""


OpenUrl = Callable[..., Any]


class InstallerDownloader:
    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_bytes: int = MAX_INSTALLER_BYTES,
        opener: OpenUrl = urlopen,
    ) -> None:
        timeout = float(timeout_seconds)
        size_limit = int(max_bytes)

        if timeout <= 0:
            raise ValueError(
                "Timeout musbat bo‘lishi kerak"
            )

        if size_limit <= 0:
            raise ValueError(
                "max_bytes musbat bo‘lishi kerak"
            )

        if not callable(opener):
            raise TypeError(
                "opener callable bo‘lishi kerak"
            )

        self._timeout_seconds = timeout
        self._max_bytes = size_limit
        self._opener = opener

    def download(
        self,
        manifest: UpdateManifest,
        destination: Path,
    ) -> Path:
        if not isinstance(
            manifest,
            UpdateManifest,
        ):
            raise TypeError(
                "manifest UpdateManifest bo‘lishi kerak"
            )

        parsed = urlparse(
            manifest.installer_url
        )

        if (
            parsed.scheme != "https"
            or not parsed.netloc
        ):
            raise ValueError(
                "Installer manzili HTTPS bo‘lishi kerak"
            )

        destination = Path(
            destination
        ).expanduser().resolve()

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        partial = destination.with_suffix(
            destination.suffix + ".part"
        )

        partial.unlink(
            missing_ok=True
        )

        request = Request(
            manifest.installer_url,
            headers={
                "Accept": (
                    "application/octet-stream"
                ),
                "User-Agent": (
                    "Gold9999-Desktop-Updater"
                ),
                "Cache-Control": "no-cache",
            },
            method="GET",
        )

        try:
            self._download_to_partial(
                request=request,
                partial=partial,
            )

            if not verify_installer(
                partial,
                manifest.sha256,
            ):
                raise UpdateChecksumError(
                    "Installer SHA-256 mos kelmadi"
                )

            destination.unlink(
                missing_ok=True
            )

            partial.replace(
                destination
            )

        except Exception:
            partial.unlink(
                missing_ok=True
            )
            raise

        return destination

    def _download_to_partial(
        self,
        *,
        request: Request,
        partial: Path,
    ) -> None:
        try:
            with self._opener(
                request,
                timeout=self._timeout_seconds,
            ) as response:
                status = int(
                    getattr(
                        response,
                        "status",
                        200,
                    )
                )

                if status != 200:
                    raise UpdateDownloadResponseError(
                        "Installer HTTP status "
                        f"noto‘g‘ri: {status}"
                    )

                content_length = str(
                    response.headers.get(
                        "Content-Length",
                        "",
                    )
                ).strip()

                if content_length:
                    try:
                        declared_size = int(
                            content_length
                        )
                    except ValueError as exc:
                        raise UpdateDownloadResponseError(
                            "Content-Length noto‘g‘ri"
                        ) from exc

                    if (
                        declared_size < 0
                        or declared_size
                        > self._max_bytes
                    ):
                        raise UpdateDownloadResponseError(
                            "Installer hajmi ruxsat "
                            "etilgan chegaradan katta"
                        )

                total = 0

                with partial.open("wb") as stream:
                    while True:
                        block = response.read(
                            READ_BLOCK_SIZE
                        )

                        if not block:
                            break

                        total += len(block)

                        if total > self._max_bytes:
                            raise UpdateDownloadResponseError(
                                "Installer hajmi ruxsat "
                                "etilgan chegaradan katta"
                            )

                        stream.write(block)

                if total == 0:
                    raise UpdateDownloadResponseError(
                        "Installer fayli bo‘sh"
                    )

        except UpdateDownloadError:
            raise

        except HTTPError as exc:
            raise UpdateDownloadTransportError(
                f"Installer HTTP xatosi: {exc.code}"
            ) from exc

        except URLError as exc:
            raise UpdateDownloadTransportError(
                "Installer tarmoq xatosi: "
                f"{exc.reason}"
            ) from exc

        except OSError as exc:
            raise UpdateDownloadTransportError(
                f"Installer transport xatosi: {exc}"
            ) from exc


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "InstallerDownloader",
    "MAX_INSTALLER_BYTES",
    "READ_BLOCK_SIZE",
    "UpdateChecksumError",
    "UpdateDownloadError",
    "UpdateDownloadResponseError",
    "UpdateDownloadTransportError",
]
