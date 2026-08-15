from __future__ import annotations

import hashlib
import hmac
import os
import re
import shutil
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path

from flask import (
    Flask,
    abort,
    jsonify,
    request,
    send_file,
)


INSTALLER_FILENAME = "Gold9999Setup.exe"

RELEASE_REPOSITORY = "abbosxon300/GOLD9999"

_VERSION_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)$"
)

_SHA256_PATTERN = re.compile(
    r"^[0-9a-f]{64}$"
)

MAX_INSTALLER_BYTES = 100 * 1024 * 1024

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



def _deploy_token() -> str:
    return str(
        os.environ.get(
            "GOLD9999_RELEASE_DEPLOY_TOKEN",
            "",
        )
    ).strip()


def _authorized_deploy_request() -> bool:
    expected = _deploy_token()

    if not expected:
        return False

    authorization = str(
        request.headers.get(
            "Authorization",
            "",
        )
    ).strip()

    prefix = "Bearer "

    if not authorization.startswith(prefix):
        return False

    supplied = authorization[len(prefix):].strip()

    if not supplied:
        return False

    return hmac.compare_digest(
        supplied,
        expected,
    )


def _normalize_version(value: object) -> str:
    version = str(value or "").strip()

    if _VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError(
            "version noto'g'ri"
        )

    return version


def _normalize_sha256(value: object) -> str:
    digest = str(value or "").strip().lower()

    if _SHA256_PATTERN.fullmatch(digest) is None:
        raise ValueError(
            "sha256 noto'g'ri"
        )

    return digest


def _installer_release_url(
    version: str,
) -> str:
    return (
        "https://github.com/"
        f"{RELEASE_REPOSITORY}/"
        "releases/download/"
        f"v{version}/"
        f"{INSTALLER_FILENAME}"
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for block in iter(
            lambda: stream.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def _download_release_installer(
    *,
    version: str,
    expected_sha256: str,
    destination: Path,
) -> int:
    url = _installer_release_url(
        version
    )

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Gold9999-Release-Deployer/1"
            ),
        },
    )

    total = 0

    with urllib.request.urlopen(
        req,
        timeout=120,
    ) as response:
        status = int(
            getattr(
                response,
                "status",
                200,
            )
        )

        if status != 200:
            raise RuntimeError(
                f"GitHub download HTTP {status}"
            )

        content_length = response.headers.get(
            "Content-Length"
        )

        if content_length:
            declared = int(content_length)

            if declared <= 0:
                raise RuntimeError(
                    "Installer hajmi noto'g'ri"
                )

            if declared > MAX_INSTALLER_BYTES:
                raise RuntimeError(
                    "Installer juda katta"
                )

        with destination.open("wb") as output:
            while True:
                block = response.read(
                    1024 * 1024
                )

                if not block:
                    break

                total += len(block)

                if total > MAX_INSTALLER_BYTES:
                    raise RuntimeError(
                        "Installer juda katta"
                    )

                output.write(block)

    if total <= 0:
        raise RuntimeError(
            "Installer bo'sh"
        )

    actual_sha256 = _sha256_file(
        destination
    )

    if not hmac.compare_digest(
        actual_sha256,
        expected_sha256,
    ):
        raise RuntimeError(
            "Installer SHA256 mos emas"
        )

    return total


def _deploy_release_installer(
    *,
    version: str,
    expected_sha256: str,
) -> dict[str, object]:
    release_dir = _release_directory()

    release_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    live_path = (
        release_dir
        / INSTALLER_FILENAME
    )

    fd, tmp_name = tempfile.mkstemp(
        prefix="Gold9999Setup.",
        suffix=".new",
        dir=str(release_dir),
    )
    os.close(fd)

    tmp_path = Path(tmp_name)

    backup_path: Path | None = None

    try:
        size = _download_release_installer(
            version=version,
            expected_sha256=expected_sha256,
            destination=tmp_path,
        )

        if live_path.is_file():
            stamp = datetime.now().strftime(
                "%Y%m%d_%H%M%S"
            )

            backup_path = (
                release_dir
                / (
                    f"{INSTALLER_FILENAME}"
                    f".bak_{stamp}"
                )
            )

            shutil.copy2(
                live_path,
                backup_path,
            )

        os.replace(
            tmp_path,
            live_path,
        )

        deployed_sha256 = _sha256_file(
            live_path
        )

        if not hmac.compare_digest(
            deployed_sha256,
            expected_sha256,
        ):
            raise RuntimeError(
                "Live installer SHA256 mos emas"
            )

        return {
            "version": version,
            "sha256": deployed_sha256,
            "size": int(size),
            "path": str(live_path),
            "backup": (
                str(backup_path)
                if backup_path is not None
                else None
            ),
        }

    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def register_download_routes(
    app: Flask,
) -> None:
    @app.post(
        "/api/releases/deploy-installer"
    )
    def deploy_gold9999_installer():
        if not _authorized_deploy_request():
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), 401

        if not request.is_json:
            return jsonify({
                "success": False,
                "message": (
                    "Content-Type application/json "
                    "bo'lishi kerak"
                ),
            }), 415

        body = request.get_json(
            silent=True
        )

        if not isinstance(body, dict):
            return jsonify({
                "success": False,
                "message": (
                    "JSON object kutilgan"
                ),
            }), 400

        if set(body) != {
            "version",
            "sha256",
        }:
            return jsonify({
                "success": False,
                "message": (
                    "Faqat version va sha256 "
                    "maydonlari ruxsat etilgan"
                ),
            }), 400

        try:
            version = _normalize_version(
                body["version"]
            )

            expected_sha256 = (
                _normalize_sha256(
                    body["sha256"]
                )
            )

            result = (
                _deploy_release_installer(
                    version=version,
                    expected_sha256=(
                        expected_sha256
                    ),
                )
            )

        except ValueError as exc:
            return jsonify({
                "success": False,
                "message": str(exc),
            }), 400

        except Exception as exc:
            app.logger.exception(
                "Desktop installer deploy failed"
            )

            return jsonify({
                "success": False,
                "message": str(exc),
            }), 500

        return jsonify({
            "success": True,
            **result,
        })

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
