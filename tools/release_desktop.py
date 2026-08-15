from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from desktop.version import APP_VERSION
SPEC_PATH = PROJECT_ROOT / "desktop" / "Gold9999.spec"
INSTALLER_SCRIPT = (
    PROJECT_ROOT / "installer" / "Gold9999.iss"
)
SETUP_PATH = (
    PROJECT_ROOT
    / "installer_output"
    / "Gold9999Setup.exe"
)
MANIFEST_PATH = PROJECT_ROOT / "update.json"

REPOSITORY = "abbosxon300/GOLD9999"


def run(
    arguments: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    print("$", subprocess.list2cmdline(arguments))

    return subprocess.run(
        arguments,
        cwd=PROJECT_ROOT,
        check=check,
        text=True,
    )


def command_path(
    name: str,
    alternatives: tuple[Path, ...] = (),
) -> str:
    found = shutil.which(name)

    if found:
        return found

    for candidate in alternatives:
        if candidate.is_file():
            return str(candidate)

    raise RuntimeError(
        f"Buyruq topilmadi: {name}"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for block in iter(
            lambda: stream.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def ensure_clean_git() -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    if result.stdout.strip():
        raise RuntimeError(
            "Release oldidan Git worktree "
            "toza bo‘lishi kerak"
        )


def build_exe() -> None:
    run([
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(SPEC_PATH),
    ])


def build_installer(version: str) -> None:
    local_app_data = Path.home() / "AppData" / "Local"

    iscc = command_path(
        "ISCC.exe",
        (
            local_app_data
            / "Programs"
            / "Inno Setup 6"
            / "ISCC.exe",
            Path(
                r"C:\Program Files (x86)"
                r"\Inno Setup 6\ISCC.exe"
            ),
        ),
    )

    run([
        iscc,
        f"/DMyAppVersion={version}",
        str(INSTALLER_SCRIPT),
    ])

    if not SETUP_PATH.is_file():
        raise RuntimeError(
            "Gold9999Setup.exe yaratilmagan"
        )


def write_manifest(
    *,
    version: str,
    digest: str,
    notes: str,
) -> None:
    payload = {
        "version": version,
        "installer_url": (
            "https://gold9999.pythonanywhere.com/"
            "downloads/Gold9999Setup.exe"
        ),
        "sha256": digest,
        "release_notes": notes,
    }

    MANIFEST_PATH.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _gh_json(
    gh: str,
    arguments: list[str],
):
    result = subprocess.run(
        [
            gh,
            *arguments,
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    output = result.stdout.strip()

    if not output:
        return None

    return json.loads(output)


def _github_token(gh: str) -> str:
    result = subprocess.run(
        [
            gh,
            "auth",
            "token",
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    token = result.stdout.strip()

    if not token:
        raise RuntimeError(
            "GitHub token olinmadi"
        )

    return token


def _current_commit_sha() -> str:
    result = subprocess.run(
        [
            "git",
            "rev-parse",
            "HEAD",
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    sha = result.stdout.strip()

    if not sha:
        raise RuntimeError(
            "Git HEAD SHA olinmadi"
        )

    return sha


def _find_release(
    gh: str,
    tag: str,
):
    releases = _gh_json(
        gh,
        [
            "api",
            f"repos/{REPOSITORY}/releases"
            "?per_page=100",
        ],
    )

    if not isinstance(releases, list):
        return None

    for release in releases:
        if (
            isinstance(release, dict)
            and release.get("tag_name") == tag
        ):
            return release

    return None


def _create_draft_release(
    gh: str,
    *,
    tag: str,
    version: str,
    notes: str,
):
    sha = _current_commit_sha()

    result = _gh_json(
        gh,
        [
            "api",
            "--method",
            "POST",
            f"repos/{REPOSITORY}/releases",
            "-f",
            f"tag_name={tag}",
            "-f",
            f"target_commitish={sha}",
            "-f",
            f"name=Gold9999 {version}",
            "-f",
            f"body={notes}",
            "-F",
            "draft=true",
            "-F",
            "prerelease=false",
        ],
    )

    if not isinstance(result, dict):
        raise RuntimeError(
            "GitHub draft release yaratilmadi"
        )

    return result


def _delete_asset(
    gh: str,
    asset_id: int,
) -> None:
    run([
        gh,
        "api",
        "--method",
        "DELETE",
        f"repos/{REPOSITORY}/releases/assets/"
        f"{asset_id}",
    ])


def _upload_asset(
    *,
    token: str,
    release_id: int,
) -> None:
    filename = SETUP_PATH.name

    query = urllib.parse.urlencode(
        {
            "name": filename,
        }
    )

    url = (
        "https://uploads.github.com/repos/"
        f"{REPOSITORY}/releases/"
        f"{release_id}/assets?{query}"
    )

    size = SETUP_PATH.stat().st_size

    print(
        "UPLOAD:",
        filename,
        f"({size / 1024 / 1024:.2f} MB)",
    )

    data = SETUP_PATH.read_bytes()

    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": (
                f"Bearer {token}"
            ),
            "Accept": (
                "application/vnd.github+json"
            ),
            "X-GitHub-Api-Version": (
                "2022-11-28"
            ),
            "Content-Type": (
                "application/octet-stream"
            ),
            "Content-Length": str(size),
            "User-Agent": (
                "Gold9999-release-tool"
            ),
        },
    )

    last_error = None

    for attempt in range(1, 4):
        try:
            print(
                f"UPLOAD ATTEMPT {attempt}/3..."
            )

            with urllib.request.urlopen(
                request,
                timeout=300,
            ) as response:
                body = response.read().decode(
                    "utf-8"
                )

                if response.status not in (
                    200,
                    201,
                ):
                    raise RuntimeError(
                        "Asset upload HTTP "
                        f"{response.status}"
                    )

                result = json.loads(body)

                if result.get("name") != filename:
                    raise RuntimeError(
                        "Uploaded asset nomi noto?g?ri"
                    )

                print(
                    "ASSET UPLOAD OK:",
                    result.get("name"),
                )
                return

        except Exception as exc:
            last_error = exc

            print(
                "UPLOAD FAILED:",
                repr(exc),
            )

            if attempt < 3:
                print("RETRY IN 5 SEC...")
                time.sleep(5)

    raise RuntimeError(
        "GitHub asset upload failed"
    ) from last_error


def _release_assets(
    gh: str,
    release_id: int,
):
    result = _gh_json(
        gh,
        [
            "api",
            f"repos/{REPOSITORY}/releases/"
            f"{release_id}/assets",
        ],
    )

    if not isinstance(result, list):
        raise RuntimeError(
            "Release assets olinmadi"
        )

    return result


def _publish_draft(
    gh: str,
    release_id: int,
):
    result = _gh_json(
        gh,
        [
            "api",
            "--method",
            "PATCH",
            f"repos/{REPOSITORY}/releases/"
            f"{release_id}",
            "-F",
            "draft=false",
        ],
    )

    if not isinstance(result, dict):
        raise RuntimeError(
            "Release publish bo?lmadi"
        )

    if result.get("draft") is not False:
        raise RuntimeError(
            "Release hali draft holatida"
        )

    return result


def publish_release(
    *,
    version: str,
    notes: str,
) -> None:
    gh = command_path(
        "gh",
        (
            Path(
                r"C:\Program Files"
                r"\GitHub CLI\gh.exe"
            ),
        ),
    )

    tag = f"v{version}"
    filename = SETUP_PATH.name

    print("RELEASE TAG:", tag)

    release = _find_release(
        gh,
        tag,
    )

    if release is None:
        print("CREATE DRAFT RELEASE...")

        release = _create_draft_release(
            gh,
            tag=tag,
            version=version,
            notes=notes,
        )

        print("DRAFT RELEASE CREATED")

    else:
        print(
            "EXISTING RELEASE FOUND:",
            release.get("id"),
        )

    release_id = int(
        release["id"]
    )

    is_draft = bool(
        release.get("draft")
    )

    if not is_draft:
        assets = _release_assets(
            gh,
            release_id,
        )

        matching = [
            asset
            for asset in assets
            if asset.get("name") == filename
        ]

        if matching:
            print(
                "RELEASE ALREADY PUBLISHED "
                "WITH INSTALLER"
            )
            return

        raise RuntimeError(
            "Release published, lekin "
            "installer asset yo?q"
        )

    assets = _release_assets(
        gh,
        release_id,
    )

    for asset in assets:
        if asset.get("name") == filename:
            print(
                "DELETE OLD ASSET:",
                filename,
            )

            _delete_asset(
                gh,
                int(asset["id"]),
            )

    token = _github_token(gh)

    _upload_asset(
        token=token,
        release_id=release_id,
    )

    print("VERIFY ASSET...")

    assets = _release_assets(
        gh,
        release_id,
    )

    matching = [
        asset
        for asset in assets
        if (
            asset.get("name") == filename
            and int(
                asset.get("size") or 0
            )
            == SETUP_PATH.stat().st_size
        )
    ]

    if len(matching) != 1:
        raise RuntimeError(
            "Uploaded installer verify failed"
        )

    print(
        "ASSET VERIFIED:",
        matching[0]["name"],
        matching[0]["size"],
        "bytes",
    )

    print("PUBLISH RELEASE...")

    published = _publish_draft(
        gh,
        release_id,
    )

    print(
        "RELEASE PUBLISHED:",
        published.get("html_url"),
    )

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Gold9999 desktop release "
            "jarayonini avtomatlashtiradi."
        )
    )

    parser.add_argument(
        "--notes",
        required=True,
        help="Release izohi.",
    )

    parser.add_argument(
        "--publish",
        action="store_true",
        help=(
            "GitHub Release'ga installer "
            "yuklaydi."
        ),
    )

    parser.add_argument(
        "--skip-clean-check",
        action="store_true",
        help="Faqat diagnostika uchun.",
    )

    arguments = parser.parse_args()

    version = APP_VERSION
    notes = arguments.notes.strip()

    if not notes:
        raise ValueError(
            "Release izohi bo‘sh bo‘lmasligi kerak"
        )

    if not arguments.skip_clean_check:
        ensure_clean_git()

    print("VERSION:", version)

    build_exe()
    build_installer(version)

    digest = sha256_file(SETUP_PATH)

    write_manifest(
        version=version,
        digest=digest,
        notes=notes,
    )

    print("SETUP:", SETUP_PATH)
    print("SHA256:", digest)
    print("MANIFEST:", MANIFEST_PATH)

    if arguments.publish:
        publish_release(
            version=version,
            notes=notes,
        )

    print("RELEASE PIPELINE COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
