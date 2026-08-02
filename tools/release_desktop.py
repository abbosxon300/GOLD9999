from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


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
            "https://github.com/"
            f"{REPOSITORY}/releases/download/"
            f"v{version}/Gold9999Setup.exe"
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

    run([
        gh,
        "release",
        "create",
        tag,
        str(SETUP_PATH),
        "--repo",
        REPOSITORY,
        "--target",
        "main",
        "--title",
        f"Gold9999 {version}",
        "--notes",
        notes,
    ])


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
