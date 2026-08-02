from __future__ import annotations

import threading
import time

from threading import Lock
from typing import Any

from desktop.updater import (
    DesktopUpdater,
    PreparedUpdate,
)
from desktop.version import APP_VERSION


class DesktopUpdateApi:
    """PyWebView JavaScript update ko‘prigi."""

    def __init__(
        self,
        updater: DesktopUpdater | None,
    ) -> None:
        self._updater = updater
        self._prepared: PreparedUpdate | None = None
        self._lock = Lock()
        self._exit_callback = None

    def set_exit_callback(
        self,
        callback,
    ) -> None:
        if callback is not None and not callable(callback):
            raise TypeError(
                "exit callback callable bo?lishi kerak"
            )

        self._exit_callback = callback

    def exit_for_update(self) -> dict[str, Any]:
        callback = self._exit_callback

        if callback is None:
            return {
                "success": False,
                "message": (
                    "Desktop oynasini yopish "
                    "callback?i sozlanmagan."
                ),
            }

        def delayed_exit() -> None:
            time.sleep(0.8)

            try:
                callback()
            except Exception as exc:
                print(
                    "DESKTOP UPDATE EXIT FAILED:",
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )

        threading.Thread(
            target=delayed_exit,
            name="Gold9999UpdateExit",
            daemon=True,
        ).start()

        return {
            "success": True,
            "message": (
                "Gold9999 yangilanish uchun "
                "yopilmoqda."
            ),
        }

    def get_release_info(self) -> dict[str, Any]:
        if self._updater is None:
            return {
                "success": False,
                "enabled": False,
                "message": (
                    "Yangilanish serveri "
                    "sozlanmagan."
                ),
            }

        try:
            result = self._updater.check_for_update()
            manifest = result.manifest

            return {
                "success": True,
                "enabled": True,
                "version": manifest.version,
                "release_notes": (
                    manifest.release_notes
                ),
                "current_version": APP_VERSION,
                "update_available": (
                    manifest.update_available
                ),
            }

        except Exception as exc:
            return {
                "success": False,
                "enabled": True,
                "message": (
                    "Yangilanish ma?lumotini "
                    f"olib bo?lmadi: {exc}"
                ),
            }

    def get_update_status(self) -> dict[str, Any]:
        return {
            "enabled": self._updater is not None,
            "current_version": APP_VERSION,
            "update_available": False,
            "version": None,
            "release_notes": "",
            "message": (
                "Yangilanish tekshiruvi tayyor."
                if self._updater is not None
                else (
                    "Yangilanish serveri "
                    "sozlanmagan."
                )
            ),
        }

    def check_for_update(self) -> dict[str, Any]:
        if self._updater is None:
            return {
                "success": True,
                "enabled": False,
                "current_version": APP_VERSION,
                "update_available": False,
                "version": None,
                "release_notes": "",
                "message": (
                    "Yangilanish serveri "
                    "sozlanmagan."
                ),
            }

        with self._lock:
            try:
                result = (
                    self._updater
                    .check_for_update()
                )

                manifest = result.manifest

                return {
                    "success": True,
                    "enabled": True,
                    "current_version": APP_VERSION,
                    "update_available": (
                        result.update_available
                    ),
                    "version": manifest.version,
                    "release_notes": (
                        manifest.release_notes
                    ),
                    "message": (
                        "Yangi versiya mavjud."
                        if result.update_available
                        else (
                            "Siz eng so‘nggi "
                            "versiyadan "
                            "foydalanyapsiz."
                        )
                    ),
                }

            except Exception as exc:
                return {
                    "success": False,
                    "enabled": True,
                    "current_version": APP_VERSION,
                    "update_available": False,
                    "version": None,
                    "release_notes": "",
                    "message": (
                        "Yangilanishni tekshirib "
                        f"bo‘lmadi: {exc}"
                    ),
                }

    def prepare_update(self) -> dict[str, Any]:
        if self._updater is None:
            return {
                "success": False,
                "message": (
                    "Yangilanish serveri "
                    "sozlanmagan."
                ),
            }

        with self._lock:
            try:
                result = (
                    self._updater
                    .check_for_update()
                )

                prepared = (
                    self._updater
                    .prepare_update(result)
                )

                if prepared is None:
                    self._prepared = None

                    return {
                        "success": True,
                        "update_available": False,
                        "message": (
                            "Yangi versiya mavjud "
                            "emas."
                        ),
                    }

                self._prepared = prepared

                return {
                    "success": True,
                    "update_available": True,
                    "version": (
                        prepared.manifest.version
                    ),
                    "installer_path": str(
                        prepared.installer_path
                    ),
                    "message": (
                        "Yangilanish yuklandi "
                        "va o‘rnatishga tayyor."
                    ),
                }

            except Exception as exc:
                self._prepared = None

                return {
                    "success": False,
                    "update_available": False,
                    "message": (
                        "Yangilanishni yuklab "
                        f"bo‘lmadi: {exc}"
                    ),
                }

    def install_prepared_update(
        self,
    ) -> dict[str, Any]:
        if self._updater is None:
            return {
                "success": False,
                "message": (
                    "Yangilanish serveri "
                    "sozlanmagan."
                ),
            }

        with self._lock:
            if self._prepared is None:
                return {
                    "success": False,
                    "message": (
                        "O‘rnatishga tayyor "
                        "yangilanish yo‘q."
                    ),
                }

            try:
                execution = (
                    self._updater
                    .launch_update(
                        self._prepared
                    )
                )

                process_id = (
                    execution.launch.process_id
                )

                self._prepared = None

                return {
                    "success": True,
                    "process_id": process_id,
                    "message": (
                        "Yangilanish o‘rnatuvchisi "
                        "ishga tushirildi."
                    ),
                }

            except Exception as exc:
                return {
                    "success": False,
                    "message": (
                        "Yangilanishni o‘rnatib "
                        f"bo‘lmadi: {exc}"
                    ),
                }


__all__ = [
    "DesktopUpdateApi",
]
