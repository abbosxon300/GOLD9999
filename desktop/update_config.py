from __future__ import annotations

import os
from urllib.parse import urlparse


UPDATE_MANIFEST_ENV = (
    "GOLD9999_UPDATE_MANIFEST_URL"
)


def get_update_manifest_url() -> str | None:
    value = str(
        os.environ.get(
            UPDATE_MANIFEST_ENV,
            "",
        )
    ).strip()

    if not value:
        return None

    parsed = urlparse(value)

    if (
        parsed.scheme != "https"
        or not parsed.netloc
    ):
        raise ValueError(
            f"{UPDATE_MANIFEST_ENV} "
            "to‘liq HTTPS URL bo‘lishi kerak"
        )

    return value


def update_enabled() -> bool:
    return (
        get_update_manifest_url()
        is not None
    )


__all__ = [
    "UPDATE_MANIFEST_ENV",
    "get_update_manifest_url",
    "update_enabled",
]
