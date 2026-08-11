from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from services.migrations import run_migrations
from services.offline.provisioning import (
    DEFAULT_ACTIVATION_TTL_MINUTES,
    issue_activation_code,
)
from services.runtime_paths import database_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "GOLD9999 uchun bir martalik "
            "offline activation code yaratish"
        )
    )

    parser.add_argument(
        "--db",
        default=None,
        help=(
            "Database path. Berilmasa GOLD9999 "
            "runtime data.db ishlatiladi."
        ),
    )

    parser.add_argument(
        "--ttl-minutes",
        type=int,
        default=DEFAULT_ACTIVATION_TTL_MINUTES,
        help=(
            "Activation code amal qilish vaqti "
            "daqiqalarda."
        ),
    )

    return parser


def _resolve_db_path(value: str | None) -> Path:
    if value:
        path = Path(value).expanduser().resolve()
    else:
        path = database_path().expanduser().resolve()

    if not path.exists():
        raise RuntimeError(
            f"Database topilmadi: {path}"
        )

    if not path.is_file():
        raise RuntimeError(
            f"Database fayl emas: {path}"
        )

    return path


def create_activation_code(
    *,
    db_path: Path,
    ttl_minutes: int,
) -> tuple[str, str]:
    if int(ttl_minutes) <= 0:
        raise ValueError(
            "ttl_minutes musbat bo‘lishi kerak"
        )

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    try:
        run_migrations(connection)

        issued = issue_activation_code(
            connection,
            ttl_minutes=int(ttl_minutes),
        )

        connection.commit()

        return (
            issued.code,
            issued.expires_at,
        )

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        db_path = _resolve_db_path(
            args.db
        )

        code, expires_at = create_activation_code(
            db_path=db_path,
            ttl_minutes=args.ttl_minutes,
        )

    except Exception as exc:
        print(
            f"ERROR: {exc}"
        )
        return 1

    print("")
    print("ACTIVATION CODE CREATED")
    print(f"DB: {db_path}")
    print(f"CODE: {code}")
    print(f"EXPIRES_AT: {expires_at}")
    print("")
    print(
        "Bu kod bir martalik. "
        "Muddati tugagach yoki ishlatilgach "
        "qayta ishlamaydi."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )


__all__ = [
    "create_activation_code",
    "main",
]
