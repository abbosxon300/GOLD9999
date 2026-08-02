from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse

from desktop.version import (
    APP_VERSION,
    is_newer_version,
    parse_version,
)


_SHA256_PATTERN = re.compile(
    r"^[0-9a-f]{64}$"
)


@dataclass(frozen=True, slots=True)
class UpdateManifest:
    version: str
    installer_url: str
    sha256: str
    release_notes: str = ""

    @property
    def update_available(self) -> bool:
        return is_newer_version(
            self.version,
            APP_VERSION,
        )


def manifest_from_dict(
    payload: object,
) -> UpdateManifest:
    if not isinstance(payload, dict):
        raise ValueError(
            "Update manifest JSON object "
            "bo‘lishi kerak"
        )

    required_fields = {
        "version",
        "installer_url",
        "sha256",
    }

    optional_fields = {
        "release_notes",
    }

    missing = required_fields - set(payload)
    unknown = (
        set(payload)
        - required_fields
        - optional_fields
    )

    if missing:
        raise ValueError(
            "Manifest maydonlari yetishmaydi: "
            + ", ".join(sorted(missing))
        )

    if unknown:
        raise ValueError(
            "Manifestda noma’lum maydonlar bor: "
            + ", ".join(sorted(unknown))
        )

    version = str(
        payload["version"]
    ).strip()

    installer_url = str(
        payload["installer_url"]
    ).strip()

    sha256 = str(
        payload["sha256"]
    ).strip().lower()

    release_notes = str(
        payload.get(
            "release_notes",
            "",
        )
    ).strip()

    parse_version(version)

    parsed_url = urlparse(
        installer_url
    )

    if (
        parsed_url.scheme != "https"
        or not parsed_url.netloc
    ):
        raise ValueError(
            "installer_url to‘liq HTTPS "
            "manzil bo‘lishi kerak"
        )

    if _SHA256_PATTERN.fullmatch(
        sha256
    ) is None:
        raise ValueError(
            "sha256 64 ta kichik hex "
            "belgidan iborat bo‘lishi kerak"
        )

    return UpdateManifest(
        version=version,
        installer_url=installer_url,
        sha256=sha256,
        release_notes=release_notes,
    )


def manifest_from_json(
    content: str,
) -> UpdateManifest:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Update manifest JSON noto‘g‘ri"
        ) from exc

    return manifest_from_dict(
        payload
    )


def sha256_file(
    path: Path,
) -> str:
    digest = hashlib.sha256()

    with Path(path).open("rb") as stream:
        for block in iter(
            lambda: stream.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def verify_installer(
    path: Path,
    expected_sha256: str,
) -> bool:
    normalized = str(
        expected_sha256
    ).strip().lower()

    if _SHA256_PATTERN.fullmatch(
        normalized
    ) is None:
        raise ValueError(
            "Noto‘g‘ri expected SHA-256"
        )

    return (
        sha256_file(path)
        == normalized
    )


__all__ = [
    "UpdateManifest",
    "manifest_from_dict",
    "manifest_from_json",
    "sha256_file",
    "verify_installer",
]
