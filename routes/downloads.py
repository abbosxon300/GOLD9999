from __future__ import annotations

import os
from pathlib import Path

from flask import (
    Flask,
    abort,
    send_file,
)


INSTALLER_FILENAME = "Gold9999Setup.exe"

DEFAULT_RELEASE_DIRECTORY = (
    Path.home()
    / "releases"
)


def _release_directory() -> Path:
    configured = str(
        os.environ.get(
            "GOLD9999_RELEASE_DIR",
            "",
        )
    ).strip()

    if configured:
        return (
            Path(configured)
            .expanduser()
            .resolve()
        )

    return (
        DEFAULT_RELEASE_DIRECTORY
        .expanduser()
        .resolve()
    )


def register_download_routes(
    app: Flask,
) -> None:
    @app.get(
        "/downloads/Gold9999Setup.exe"
    )
    def download_gold9999_installer():
        path = (
            _release_directory()
            / INSTALLER_FILENAME
        )

        if not path.is_file():
            abort(404)

        return send_file(
            path,
            as_attachment=True,
            download_name=INSTALLER_FILENAME,
            mimetype="application/octet-stream",
            conditional=True,
        )


__all__ = [
    "INSTALLER_FILENAME",
    "register_download_routes",
]
