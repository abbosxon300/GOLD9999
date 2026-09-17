from __future__ import annotations

import sys
import textwrap
from datetime import datetime
from typing import Any, Mapping


_COLUMNS_BY_WIDTH = {
    58: 32,
    80: 42,
}

_FONT_POINTS_BY_WIDTH = {
    58: 8,
    80: 9,
}


def _required_printer_name(
    settings: Mapping[str, object],
) -> str:
    name = str(
        settings.get(
            "printer_name",
            "",
        )
        or ""
    ).strip()

    if not name:
        raise ValueError(
            "Printer tanlanmagan"
        )

    return name


def _paper_width_mm(
    settings: Mapping[str, object],
) -> int:
    try:
        width = int(
            settings.get(
                "paper_width_mm",
                80,
            )
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "Qog‘oz kengligi noto‘g‘ri"
        ) from exc

    if width not in _COLUMNS_BY_WIDTH:
        raise ValueError(
            "Faqat 58 yoki 80 mm "
            "profil qo‘llanadi"
        )

    return width


def receipt_columns(
    paper_width_mm: int,
) -> int:
    try:
        return _COLUMNS_BY_WIDTH[
            int(paper_width_mm)
        ]
    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "Faqat 58 yoki 80 mm "
            "profil qo‘llanadi"
        ) from exc


def _center(
    text: str,
    columns: int,
) -> str:
    return str(text)[:columns].center(
        columns
    )


def _wrap(
    text: str,
    columns: int,
) -> list[str]:
    value = str(
        text or ""
    ).strip()

    if not value:
        return [""]

    lines = textwrap.wrap(
        value,
        width=columns,
        break_long_words=True,
        break_on_hyphens=False,
        replace_whitespace=True,
        drop_whitespace=True,
    )

    return lines or [""]


def build_test_receipt_lines(
    settings: Mapping[str, object],
    *,
    now: datetime | None = None,
) -> list[str]:
    printer_name = _required_printer_name(
        settings
    )

    width = _paper_width_mm(
        settings
    )

    columns = receipt_columns(
        width
    )

    timestamp = (
        now
        if now is not None
        else datetime.now()
    )

    separator = "-" * columns

    lines: list[str] = [
        _center(
            "GOLD 9999",
            columns,
        ),
        _center(
            "PRINTER TEST",
            columns,
        ),
        separator,
    ]

    lines.extend(
        _wrap(
            f"Printer: {printer_name}",
            columns,
        )
    )

    lines.append(
        f"Qog'oz: {width} mm"
    )

    lines.append(
        "Vaqt: "
        + timestamp.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    lines.append(
        separator
    )

    lines.extend(
        _wrap(
            "Windows printer driver orqali "
            "test chek yuborildi.",
            columns,
        )
    )

    lines.extend(
        _wrap(
            "Agar shu matn chiqsa, "
            "Gold9999 printer aloqasi ishlayapti.",
            columns,
        )
    )

    lines.append(
        separator
    )

    lines.append(
        _center(
            "TEST OK",
            columns,
        )
    )

    return lines


def _receipt_money(value: object) -> str:
    try:
        amount = round(float(value or 0))
    except (TypeError, ValueError):
        amount = 0

    return f"{amount:,}".replace(",", " ")


def _receipt_qty(value: object) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0

    if number.is_integer():
        return str(int(number))

    return (
        f"{number:.3f}"
        .rstrip("0")
        .rstrip(".")
    )


def build_receipt_lines(
    payload: Mapping[str, object],
    settings: Mapping[str, object],
) -> list[str]:
    width = _paper_width_mm(settings)
    columns = receipt_columns(width)
    separator = "-" * columns

    business_name = str(
        payload.get("business_name")
        or "GOLD 9999"
    ).strip()

    sale_id = str(
        payload.get("sale_id")
        or ""
    ).strip()

    sale_date = str(
        payload.get("sale_date")
        or ""
    ).strip()

    lines = [
        _center(business_name, columns),
        _center(
            f"CHEK #{sale_id}",
            columns,
        ),
    ]

    if sale_date:
        lines.append(
            _center(
                sale_date,
                columns,
            )
        )

    lines.append(separator)

    items = payload.get("items")

    if not isinstance(items, list):
        items = []

    for item in items:
        if not isinstance(item, Mapping):
            continue

        name = str(
            item.get("name")
            or ""
        ).strip()

        lines.extend(
            _wrap(
                name,
                columns,
            )
        )

        qty = _receipt_qty(
            item.get("qty")
        )

        unit_price = _receipt_money(
            item.get("unit_price_uzs")
        )

        line_total = _receipt_money(
            item.get("line_total_uzs")
        )

        lines.extend(
            _wrap(
                f"{qty} x {unit_price} = {line_total}",
                columns,
            )
        )

    lines.append(separator)

    total = _receipt_money(
        payload.get("total_uzs")
    )

    lines.extend(
        _wrap(
            f"JAMI: {total} so'm",
            columns,
        )
    )

    lines.append(separator)

    lines.append(
        _center(
            "Xaridingiz uchun rahmat!",
            columns,
        )
    )

    return lines


def _load_windows_modules():
    if sys.platform != "win32":
        raise RuntimeError(
            "Chop etish faqat Gold9999 "
            "Windows Desktop ichida ishlaydi"
        )

    try:
        import win32con
        import win32print
        import win32ui
    except ImportError as exc:
        raise RuntimeError(
            "Windows printer modullari "
            "o‘rnatilmagan"
        ) from exc

    return (
        win32con,
        win32print,
        win32ui,
    )


def _validate_windows_printer(
    printer_name: str,
    win32print,
) -> None:
    handle = None

    try:
        handle = win32print.OpenPrinter(
            printer_name
        )

    except Exception as exc:
        raise RuntimeError(
            "Windows printer topilmadi "
            f"yoki ochilmadi: {printer_name}"
        ) from exc

    finally:
        if handle is not None:
            win32print.ClosePrinter(
                handle
            )


def _print_lines_windows(
    *,
    printer_name: str,
    paper_width_mm: int,
    lines: list[str],
    copies: int,
    job_name: str,
) -> dict[str, Any]:
    (
        win32con,
        win32print,
        win32ui,
    ) = _load_windows_modules()

    _validate_windows_printer(
        printer_name,
        win32print,
    )

    if copies < 1 or copies > 5:
        raise ValueError(
            "Nusxa soni 1 dan 5 gacha "
            "bo‘lishi kerak"
        )

    dc = win32ui.CreateDC()

    doc_started = False
    selected_old_font = None

    try:
        dc.CreatePrinterDC(
            printer_name
        )

        dpi_x = int(
            dc.GetDeviceCaps(
                win32con.LOGPIXELSX
            )
            or 203
        )

        dpi_y = int(
            dc.GetDeviceCaps(
                win32con.LOGPIXELSY
            )
            or 203
        )

        printable_width = int(
            dc.GetDeviceCaps(
                win32con.HORZRES
            )
            or 1
        )

        printable_height = int(
            dc.GetDeviceCaps(
                win32con.VERTRES
            )
            or 1
        )

        point_size = (
            _FONT_POINTS_BY_WIDTH[
                paper_width_mm
            ]
        )

        font_height = -max(
            1,
            round(
                dpi_y
                * point_size
                / 72
            ),
        )

        font = win32ui.CreateFont({
            "name": "Courier New",
            "height": font_height,
            "weight": 400,
        })

        selected_old_font = (
            dc.SelectObject(
                font
            )
        )

        margin_x = max(
            1,
            round(
                dpi_x
                * 1.5
                / 25.4
            ),
        )

        margin_y = max(
            1,
            round(
                dpi_y
                * 2.0
                / 25.4
            ),
        )

        line_height = max(
            1,
            round(
                dpi_y
                * (
                    point_size + 3
                )
                / 72
            ),
        )

        job_id = dc.StartDoc(
            job_name
        )

        doc_started = True

        for _copy_index in range(
            copies
        ):
            dc.StartPage()

            y = margin_y

            for line in lines:
                if (
                    y + line_height
                    > printable_height
                ):
                    dc.EndPage()
                    dc.StartPage()
                    y = margin_y

                dc.TextOut(
                    margin_x,
                    y,
                    str(line),
                )

                y += line_height

            dc.EndPage()

        dc.EndDoc()
        doc_started = False

        return {
            "job_id": (
                int(job_id)
                if job_id is not None
                else None
            ),
            "dpi_x": dpi_x,
            "dpi_y": dpi_y,
            "printable_width": (
                printable_width
            ),
            "printable_height": (
                printable_height
            ),
        }

    except Exception:
        if doc_started:
            try:
                dc.AbortDoc()
            except Exception:
                pass

        raise

    finally:
        if selected_old_font is not None:
            try:
                dc.SelectObject(
                    selected_old_font
                )
            except Exception:
                pass

        try:
            dc.DeleteDC()
        except Exception:
            pass


def print_receipt(
    payload: Mapping[str, object],
    settings: Mapping[str, object],
) -> dict[str, Any]:
    printer_name = _required_printer_name(
        settings
    )

    width = _paper_width_mm(
        settings
    )

    try:
        copies = int(
            settings.get("copies", 1)
            or 1
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Nusxa soni noto‘g‘ri"
        ) from exc

    lines = build_receipt_lines(
        payload,
        settings,
    )

    sale_id = str(
        payload.get("sale_id")
        or ""
    ).strip()

    result = _print_lines_windows(
        printer_name=printer_name,
        paper_width_mm=width,
        lines=lines,
        copies=copies,
        job_name=(
            f"Gold9999 Receipt {sale_id}"
        ),
    )

    return {
        "printer_name": printer_name,
        "paper_width_mm": width,
        "copies": copies,
        "line_count": len(lines),
        **result,
    }


def print_test_receipt(
    settings: Mapping[str, object],
) -> dict[str, Any]:
    printer_name = _required_printer_name(
        settings
    )

    width = _paper_width_mm(
        settings
    )

    lines = build_test_receipt_lines(
        settings
    )

    result = _print_lines_windows(
        printer_name=printer_name,
        paper_width_mm=width,
        lines=lines,
        copies=1,
        job_name="Gold9999 Printer Test",
    )

    return {
        "printer_name": printer_name,
        "paper_width_mm": width,
        "copies": 1,
        "line_count": len(lines),
        **result,
    }


__all__ = [
    "build_receipt_lines",
    "build_test_receipt_lines",
    "print_receipt",
    "print_test_receipt",
    "receipt_columns",
]
