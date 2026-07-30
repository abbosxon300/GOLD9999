from __future__ import annotations

import hashlib
import importlib
import inspect
import pkgutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from types import ModuleType

from migrations import versions as migration_versions


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    checksum: str
    module: ModuleType


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def migration_checksum(module: ModuleType) -> str:
    source = inspect.getsource(module)

    return hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()


def discover_migrations() -> list[Migration]:
    discovered: list[Migration] = []
    module_prefix = f"{migration_versions.__name__}."

    for module_info in pkgutil.iter_modules(
        migration_versions.__path__,
        module_prefix,
    ):
        module = importlib.import_module(module_info.name)

        version = getattr(module, "VERSION", None)
        name = getattr(module, "NAME", None)
        upgrade = getattr(module, "upgrade", None)

        if not isinstance(version, int) or version <= 0:
            raise RuntimeError(
                f"Migration VERSION noto‘g‘ri: {module_info.name}"
            )

        if not isinstance(name, str) or not name.strip():
            raise RuntimeError(
                f"Migration NAME noto‘g‘ri: {module_info.name}"
            )

        if not callable(upgrade):
            raise RuntimeError(
                f"Migration upgrade() topilmadi: {module_info.name}"
            )

        discovered.append(
            Migration(
                version=version,
                name=name.strip(),
                checksum=migration_checksum(module),
                module=module,
            )
        )

    discovered.sort(key=lambda migration: migration.version)

    versions = [
        migration.version
        for migration in discovered
    ]
    names = [
        migration.name
        for migration in discovered
    ]

    if len(versions) != len(set(versions)):
        raise RuntimeError(
            "Duplicate migration VERSION aniqlandi"
        )

    if len(names) != len(set(names)):
        raise RuntimeError(
            "Duplicate migration NAME aniqlandi"
        )

    expected_versions = list(
        range(1, len(discovered) + 1)
    )

    if versions != expected_versions:
        raise RuntimeError(
            "Migration VERSION ketma-ketligi buzilgan: "
            f"expected={expected_versions}, actual={versions}"
        )

    return discovered


def ensure_schema_migrations(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations(
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def read_applied_migrations(
    connection: sqlite3.Connection,
) -> dict[int, dict[str, object]]:
    rows = connection.execute(
        """
        SELECT
            version,
            name,
            checksum,
            applied_at
        FROM schema_migrations
        ORDER BY version
        """
    ).fetchall()

    return {
        int(row[0]): {
            "version": int(row[0]),
            "name": str(row[1]),
            "checksum": str(row[2]),
            "applied_at": str(row[3]),
        }
        for row in rows
    }


def validate_applied_migrations(
    available: list[Migration],
    applied: dict[int, dict[str, object]],
) -> None:
    available_by_version = {
        migration.version: migration
        for migration in available
    }

    unknown_versions = sorted(
        set(applied) - set(available_by_version)
    )

    if unknown_versions:
        raise RuntimeError(
            "Bazaga yozilgan, lekin kodda mavjud bo‘lmagan "
            "migrationlar bor: "
            + ", ".join(map(str, unknown_versions))
        )

    for version, record in applied.items():
        migration = available_by_version[version]

        if record["name"] != migration.name:
            raise RuntimeError(
                f"Migration nomi o‘zgargan: version={version}"
            )

        if record["checksum"] != migration.checksum:
            raise RuntimeError(
                "Migration checksum o‘zgargan: "
                f"version={version}, name={migration.name}"
            )


def run_migrations(
    connection: sqlite3.Connection,
) -> list[int]:
    available = discover_migrations()

    # Migration registry managerning ichki jadvali.
    # Business schema migrationlari esa faqat version modullarida bo‘ladi.
    ensure_schema_migrations(connection)
    connection.commit()

    applied = read_applied_migrations(connection)
    validate_applied_migrations(
        available,
        applied,
    )

    newly_applied: list[int] = []

    for migration in available:
        if migration.version in applied:
            continue

        try:
            connection.execute("BEGIN IMMEDIATE")

            migration.module.upgrade(connection)

            connection.execute(
                """
                INSERT INTO schema_migrations(
                    version,
                    name,
                    checksum,
                    applied_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    migration.version,
                    migration.name,
                    migration.checksum,
                    utc_now(),
                ),
            )

            connection.commit()
            newly_applied.append(migration.version)

        except Exception:
            connection.rollback()
            raise

    return newly_applied
