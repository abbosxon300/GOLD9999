from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from desktop.printer_api import (
    DesktopPrinterApi,
)
from desktop.update_api import (
    DesktopUpdateApi,
)


class DesktopApi:
    """Canonical PyWebView JavaScript API."""

    def __init__(
        self,
        *,
        update_api: DesktopUpdateApi,
        printer_api: DesktopPrinterApi,
    ) -> None:
        self._update_api = update_api
        self._printer_api = printer_api

    def get_release_info(
        self,
    ) -> dict[str, Any]:
        return (
            self._update_api
            .get_release_info()
        )

    def get_update_status(
        self,
    ) -> dict[str, Any]:
        return (
            self._update_api
            .get_update_status()
        )

    def check_for_update(
        self,
    ) -> dict[str, Any]:
        return (
            self._update_api
            .check_for_update()
        )

    def prepare_update(
        self,
    ) -> dict[str, Any]:
        return (
            self._update_api
            .prepare_update()
        )

    def install_prepared_update(
        self,
    ) -> dict[str, Any]:
        return (
            self._update_api
            .install_prepared_update()
        )

    def exit_for_update(
        self,
    ) -> dict[str, Any]:
        return (
            self._update_api
            .exit_for_update()
        )

    def get_printers(
        self,
    ) -> dict[str, Any]:
        return (
            self._printer_api
            .get_printers()
        )

    def print_test_receipt(
        self,
    ) -> dict[str, Any]:
        return (
            self._printer_api
            .print_test_receipt()
        )

    def get_printer_settings(
        self,
    ) -> dict[str, Any]:
        return (
            self._printer_api
            .get_printer_settings()
        )

    def save_printer_settings(
        self,
        settings: Mapping[str, object],
    ) -> dict[str, Any]:
        return (
            self._printer_api
            .save_printer_settings(
                settings
            )
        )


__all__ = [
    "DesktopApi",
]
