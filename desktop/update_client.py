from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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
    manifest_from_json,
)


DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_MANIFEST_BYTES = 64 * 1024


class UpdateClientError(RuntimeError):
    """Update manifestini olishdagi umumiy xato."""


class UpdateTransportError(UpdateClientError):
    """Tarmoq yoki HTTPS transport xatosi."""


class UpdateResponseError(UpdateClientError):
    """Server javobi noto‘g‘ri bo‘lgandagi xato."""


@dataclass(frozen=True, slots=True)
class UpdateCheckResult:
    manifest: UpdateManifest

    @property
    def update_available(self) -> bool:
        return self.manifest.update_available


OpenUrl = Callable[..., Any]


class UpdateClient:
    def __init__(
        self,
        manifest_url: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        opener: OpenUrl = urlopen,
    ) -> None:
        normalized_url = str(
            manifest_url
        ).strip()

        parsed = urlparse(
            normalized_url
        )

        if (
            parsed.scheme != "https"
            or not parsed.netloc
        ):
            raise ValueError(
                "Manifest manzili to‘liq HTTPS URL "
                "bo‘lishi kerak"
            )

        timeout = float(
            timeout_seconds
        )

        if timeout <= 0:
            raise ValueError(
                "Timeout musbat bo‘lishi kerak"
            )

        if not callable(opener):
            raise TypeError(
                "opener callable bo‘lishi kerak"
            )

        self._manifest_url = normalized_url
        self._timeout_seconds = timeout
        self._opener = opener

    @property
    def manifest_url(self) -> str:
        return self._manifest_url

    def check(self) -> UpdateCheckResult:
        request = Request(
            self._manifest_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Gold9999-Desktop-Updater",
                "Cache-Control": "no-cache",
            },
            method="GET",
        )

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
                    raise UpdateResponseError(
                        f"Manifest HTTP status noto‘g‘ri: {status}"
                    )

                content_type = str(
                    response.headers.get(
                        "Content-Type",
                        "",
                    )
                ).lower()

                if (
                    "application/json"
                    not in content_type
                ):
                    raise UpdateResponseError(
                        "Manifest Content-Type "
                        "application/json emas"
                    )

                content = response.read(
                    MAX_MANIFEST_BYTES + 1
                )

        except UpdateClientError:
            raise

        except HTTPError as exc:
            raise UpdateTransportError(
                f"Manifest HTTP xatosi: {exc.code}"
            ) from exc

        except URLError as exc:
            raise UpdateTransportError(
                f"Manifest tarmoq xatosi: {exc.reason}"
            ) from exc

        except OSError as exc:
            raise UpdateTransportError(
                f"Manifest transport xatosi: {exc}"
            ) from exc

        if len(content) > MAX_MANIFEST_BYTES:
            raise UpdateResponseError(
                "Manifest hajmi ruxsat etilgan "
                "chegaradan katta"
            )

        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UpdateResponseError(
                "Manifest UTF-8 formatida emas"
            ) from exc

        try:
            manifest = manifest_from_json(
                text
            )
        except ValueError as exc:
            raise UpdateResponseError(
                f"Manifest noto‘g‘ri: {exc}"
            ) from exc

        return UpdateCheckResult(
            manifest=manifest
        )


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_MANIFEST_BYTES",
    "UpdateCheckResult",
    "UpdateClient",
    "UpdateClientError",
    "UpdateResponseError",
    "UpdateTransportError",
]
