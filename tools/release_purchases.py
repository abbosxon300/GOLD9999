"""Back up and migrate an existing database without importing/running the app.

Run from repository root: python3 tools/release_purchases.py
An explicit --database path can be used when WSGI uses a custom database.
"""

import argparse
from datetime import datetime
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.migrations import run_migrations
from services.runtime_paths import database_path


def release(path, backup_dir):
    path = Path(path).resolve()
    if not path.is_file():
        raise RuntimeError(f"Mavjud baza topilmadi: {path}")
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"before_purchases_{datetime.now():%Y%m%d_%H%M%S_%f}.db"
    db = sqlite3.connect(f"{path.as_uri()}?mode=rw", uri=True)
    db.execute("PRAGMA foreign_keys=ON")
    try:
        before = db.execute("SELECT id,stock_qty FROM products ORDER BY id").fetchall()
        with sqlite3.connect(backup) as target:
            db.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Zaxira nusxa tekshiruvi muvaffaqiyatsiz")
        print(f"BACKUP: {backup}")
        applied = run_migrations(db)
        if (
            db.execute("SELECT id,stock_qty FROM products ORDER BY id").fetchall()
            != before
        ):
            raise RuntimeError(
                "Qoldiq o‘zgargan: reload qilmang, zaxira nusxani tekshiring"
            )
        for table in ("suppliers", "purchases", "purchase_items", "purchase_payments"):
            db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        violations = db.execute("PRAGMA foreign_key_check(purchase_items)").fetchall()
        violations += db.execute(
            "PRAGMA foreign_key_check(purchase_payments)"
        ).fetchall()
        if violations:
            raise RuntimeError("Yangi kirim jadvallarida bog‘lanish xatosi")
        print(f"MIGRATION OK: {applied or 'already applied'}; STOCK UNCHANGED")
    finally:
        db.close()
    return backup


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=database_path())
    args = parser.parse_args()
    release(args.database, ROOT / "backups")
