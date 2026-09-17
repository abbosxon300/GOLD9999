from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from desktop.printer_service import (
    print_test_receipt,
)
from services.runtime_paths import (
    data_directory,
)


SETTINGS_VERSION = 1
SETTINGS_FILE_NAME = "printer_settings.json"

SUPPORTED_PAPER_WIDTHS_MM = (
    58,
    80,
)

DEFAULT_SETTINGS: dict[str, Any] = {
    "version": SETTINGS_VERSION,
    "enabled": False,
    "printer_name": "",
    "paper_width_mm": 80,
    "auto_print": False,
    "copies": 1,
}


def printer_settings_path() -> Path:
    return (
        data_directory()
        / SETTINGS_FILE_NAME
    )


def _normalize_bool(
    value: object,
    *,
    field_name: str,
) -> bool:
    if isinstance(value, bool):
        return value

    raise ValueError(
        f"{field_name} boolean bo‘lishi kerak"
    )


def _normalize_printer_name(
    value: object,
) -> str:
    name = str(
        value or ""
    ).strip()

    if len(name) > 255:
        raise ValueError(
            "Printer nomi juda uzun"
        )

    return name


def _normalize_paper_width(
    value: object,
) -> int:
    try:
        width = int(value)
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "Qog‘oz kengligi noto‘g‘ri"
        ) from exc

    if width not in SUPPORTED_PAPER_WIDTHS_MM:
        raise ValueError(
            "Qog‘oz kengligi 58 yoki "
            "80 mm bo‘lishi kerak"
        )

    return width


def _normalize_copies(
    value: object,
) -> int:
    try:
        copies = int(value)
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "Nusxa soni noto‘g‘ri"
        ) from exc

    if copies < 1 or copies > 5:
        raise ValueError(
            "Nusxa soni 1 dan 5 gacha "
            "bo‘lishi kerak"
        )

    return copies


def normalize_settings(
    raw: Mapping[str, object] | None,
) -> dict[str, Any]:
    source = (
        dict(raw)
        if raw is not None
        else {}
    )

    enabled = (
        _normalize_bool(
            source["enabled"],
            field_name="enabled",
        )
        if "enabled" in source
        else bool(
            DEFAULT_SETTINGS["enabled"]
        )
    )

    auto_print = (
        _normalize_bool(
            source["auto_print"],
            field_name="auto_print",
        )
        if "auto_print" in source
        else bool(
            DEFAULT_SETTINGS["auto_print"]
        )
    )

    printer_name = _normalize_printer_name(
        source.get(
            "printer_name",
            DEFAULT_SETTINGS[
                "printer_name"
            ],
        )
    )

    paper_width_mm = _normalize_paper_width(
        source.get(
            "paper_width_mm",
            DEFAULT_SETTINGS[
                "paper_width_mm"
            ],
        )
    )

    copies = _normalize_copies(
        source.get(
            "copies",
            DEFAULT_SETTINGS[
                "copies"
            ],
        )
    )

    if enabled and not printer_name:
        raise ValueError(
            "Printer yoqilgan bo‘lsa "
            "printer tanlanishi kerak"
        )

    return {
        "version": SETTINGS_VERSION,
        "enabled": enabled,
        "printer_name": printer_name,
        "paper_width_mm": paper_width_mm,
        "auto_print": auto_print,
        "copies": copies,
    }


def load_printer_settings() -> dict[str, Any]:
    path = printer_settings_path()

    if not path.is_file():
        return dict(
            DEFAULT_SETTINGS
        )

    try:
        raw = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ) as exc:
        raise RuntimeError(
            "Printer sozlamalarini "
            "o‘qib bo‘lmadi"
        ) from exc

    if not isinstance(raw, dict):
        raise RuntimeError(
            "Printer sozlamalari object emas"
        )

    try:
        return normalize_settings(raw)
    except ValueError as exc:
        raise RuntimeError(
            "Printer sozlamalari noto‘g‘ri"
        ) from exc


def save_printer_settings(
    raw: Mapping[str, object],
) -> dict[str, Any]:
    settings = normalize_settings(
        raw
    )

    path = printer_settings_path()

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_path = path.with_name(
        path.name + ".tmp"
    )

    payload = (
        json.dumps(
            settings,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    try:
        temp_path.write_text(
            payload,
            encoding="utf-8",
        )

        os.replace(
            temp_path,
            path,
        )

    finally:
        if temp_path.exists():
            temp_path.unlink()

    return settings


def _windows_printer_module():
    if sys.platform != "win32":
        return None

    try:
        import win32print
    except ImportError as exc:
        raise RuntimeError(
            "Windows printer moduli "
            "o‘rnatilmagan"
        ) from exc

    return win32print


def _printer_name_from_row(
    row: object,
) -> str:
    if isinstance(row, Mapping):
        for key in (
            "pPrinterName",
            "PrinterName",
            "Name",
        ):
            value = row.get(key)

            if value:
                return str(
                    value
                ).strip()

        return ""

    if isinstance(
        row,
        (tuple, list),
    ):
        candidates = []

        if len(row) > 2:
            candidates.append(
                row[2]
            )

        if len(row) > 1:
            candidates.append(
                row[1]
            )

        for value in candidates:
            name = str(
                value or ""
            ).strip()

            if name:
                return name

    return ""


def list_windows_printers() -> dict[str, Any]:
    win32print = (
        _windows_printer_module()
    )

    if win32print is None:
        return {
            "available": False,
            "platform": sys.platform,
            "default_printer": "",
            "printers": [],
        }

    flags = (
        win32print.PRINTER_ENUM_LOCAL
        | win32print.PRINTER_ENUM_CONNECTIONS
    )

    rows = win32print.EnumPrinters(
        flags,
        None,
        4,
    )

    names: list[str] = []

    for row in rows:
        name = _printer_name_from_row(
            row
        )

        if name:
            names.append(name)

    printers = sorted(
        set(names),
        key=str.casefold,
    )

    try:
        default_printer = str(
            win32print.GetDefaultPrinter()
            or ""
        ).strip()
    except Exception:
        default_printer = ""

    return {
        "available": True,
        "platform": sys.platform,
        "default_printer": default_printer,
        "printers": printers,
    }


class DesktopPrinterApi:
    """Local Windows receipt-printer bridge."""

    def get_printers(
        self,
    ) -> dict[str, Any]:
        try:
            return {
                "success": True,
                **list_windows_printers(),
            }

        except Exception as exc:
            return {
                "success": False,
                "available": (
                    sys.platform == "win32"
                ),
                "platform": sys.platform,
                "default_printer": "",
                "printers": [],
                "message": str(exc),
            }

    def print_test_receipt(
        self,
    ) -> dict[str, Any]:
        try:
            settings = (
                load_printer_settings()
            )

            result = print_test_receipt(
                settings
            )

            return {
                "success": True,
                "message": (
                    "Test chek printerga "
                    "yuborildi"
                ),
                **result,
            }

        except Exception as exc:
            return {
                "success": False,
                "message": str(exc),
            }

    def get_printer_settings(
        self,
    ) -> dict[str, Any]:
        try:
            return {
                "success": True,
                "settings": (
                    load_printer_settings()
                ),
                "settings_path": str(
                    printer_settings_path()
                ),
            }

        except Exception as exc:
            return {
                "success": False,
                "message": str(exc),
            }

    def save_printer_settings(
        self,
        settings: Mapping[str, object],
    ) -> dict[str, Any]:
        try:
            saved = save_printer_settings(
                settings
            )

            return {
                "success": True,
                "settings": saved,
                "settings_path": str(
                    printer_settings_path()
                ),
            }

        except Exception as exc:
            return {
                "success": False,
                "message": str(exc),
            }


__all__ = [
    "DEFAULT_SETTINGS",
    "DesktopPrinterApi",
    "SETTINGS_FILE_NAME",
    "SETTINGS_VERSION",
    "SUPPORTED_PAPER_WIDTHS_MM",
    "list_windows_printers",
    "load_printer_settings",
    "normalize_settings",
    "printer_settings_path",
    "save_printer_settings",
]
