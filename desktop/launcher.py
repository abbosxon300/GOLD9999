from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


APP_TITLE = "Gold 9999"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
STARTUP_TIMEOUT_SECONDS = 20.0
SINGLE_INSTANCE_MUTEX_NAME = "Local\\Gold9999DesktopSingleInstance"
ERROR_ALREADY_EXISTS = 183


def _acquire_single_instance_mutex():
    if sys.platform != "win32":
        return object()

    import ctypes

    kernel32 = ctypes.windll.kernel32

    mutex_handle = kernel32.CreateMutexW(
        None,
        False,
        SINGLE_INSTANCE_MUTEX_NAME,
    )

    if not mutex_handle:
        raise OSError(
            "Single-instance mutex yaratilmadi"
        )

    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(mutex_handle)
        return None

    return mutex_handle



class NativeStartupSplash:
    def __init__(self) -> None:
        self._thread = None
        self._ready = threading.Event()
        self._hwnd = None

    def start(self) -> None:
        if sys.platform != "win32":
            return

        self._thread = threading.Thread(
            target=self._run,
            name="gold9999-native-splash",
            daemon=True,
        )
        self._thread.start()

        self._ready.wait(timeout=1.0)

    def close(self) -> None:
        if (
            sys.platform == "win32"
            and self._hwnd
        ):
            import ctypes

            WM_CLOSE = 0x0010

            ctypes.windll.user32.PostMessageW(
                self._hwnd,
                WM_CLOSE,
                0,
                0,
            )

    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        gdi32 = ctypes.windll.gdi32

        WS_EX_TOPMOST = 0x00000008
        WS_EX_TOOLWINDOW = 0x00000080

        WS_POPUP = 0x80000000
        WS_VISIBLE = 0x10000000
        WS_BORDER = 0x00800000

        SS_CENTER = 0x00000001
        SS_NOTIFY = 0x00000100

        SW_SHOW = 5
        WM_SETFONT = 0x0030

        DEFAULT_CHARSET = 1
        OUT_DEFAULT_PRECIS = 0
        CLIP_DEFAULT_PRECIS = 0
        CLEARTYPE_QUALITY = 5
        DEFAULT_PITCH = 0
        FF_DONTCARE = 0

        width = 470
        height = 190

        screen_width = user32.GetSystemMetrics(0)
        screen_height = user32.GetSystemMetrics(1)

        left = max(
            0,
            int((screen_width - width) / 2),
        )
        top = max(
            0,
            int((screen_height - height) / 2),
        )

        user32.CreateWindowExW.restype = (
            wintypes.HWND
        )

        kernel32.GetModuleHandleW.restype = (
            wintypes.HMODULE
        )

        instance = kernel32.GetModuleHandleW(
            None
        )

        window_text = (
            "GOLD 9999\r\n\r\n"
            "Ilova ishga tushmoqda..."
        )

        hwnd = user32.CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
            "STATIC",
            window_text,
            (
                WS_POPUP
                | WS_VISIBLE
                | WS_BORDER
                | SS_CENTER
                | SS_NOTIFY
            ),
            left,
            top,
            width,
            height,
            None,
            None,
            instance,
            None,
        )

        if not hwnd:
            self._ready.set()
            return

        self._hwnd = hwnd

        gdi32.CreateFontW.restype = (
            wintypes.HANDLE
        )

        font = gdi32.CreateFontW(
            -26,
            0,
            0,
            0,
            600,
            False,
            False,
            False,
            DEFAULT_CHARSET,
            OUT_DEFAULT_PRECIS,
            CLIP_DEFAULT_PRECIS,
            CLEARTYPE_QUALITY,
            DEFAULT_PITCH | FF_DONTCARE,
            "Segoe UI",
        )

        if font:
            user32.SendMessageW(
                hwnd,
                WM_SETFONT,
                font,
                True,
            )

        user32.ShowWindow(
            hwnd,
            SW_SHOW,
        )
        user32.UpdateWindow(hwnd)

        self._ready.set()

        message = wintypes.MSG()

        while user32.GetMessageW(
            ctypes.byref(message),
            None,
            0,
            0,
        ) > 0:
            user32.TranslateMessage(
                ctypes.byref(message)
            )
            user32.DispatchMessageW(
                ctypes.byref(message)
            )

        if font:
            gdi32.DeleteObject(font)

        self._hwnd = None


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _default_data_directory() -> Path:
    if sys.platform == "win32":
        local_app_data = str(
            os.environ.get("LOCALAPPDATA", "")
        ).strip()

        if local_app_data:
            return (
                Path(local_app_data)
                / "Gold9999"
            ).resolve()

        return (
            Path.home()
            / "AppData"
            / "Local"
            / "Gold9999"
        ).resolve()

    return (
        Path.home()
        / ".local"
        / "share"
        / "Gold9999"
    ).resolve()


def configure_desktop_environment(
    data_directory: Path | None = None,
) -> Path:
    selected = (
        Path(data_directory)
        if data_directory is not None
        else _default_data_directory()
    ).expanduser().resolve()

    selected.mkdir(
        parents=True,
        exist_ok=True,
    )

    os.environ.setdefault(
        "GOLD9999_DATA_DIR",
        str(selected),
    )

    os.environ.setdefault(
        "SECRET_KEY",
        "GOLD9999_DESKTOP_LOCAL_2026",
    )

    project_root = str(_project_root())

    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    return selected


def _load_flask_application():
    import app as gold_app

    return gold_app.app


def _port_is_available(
    host: str,
    port: int,
) -> bool:
    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    ) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False

    return True


def _serve_application(
    flask_application,
    *,
    host: str,
    port: int,
) -> None:
    from waitress import serve

    serve(
        flask_application,
        host=host,
        port=port,
        threads=8,
        clear_untrusted_proxy_headers=True,
    )


def _wait_until_ready(
    url: str,
    *,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            with urlopen(
                url,
                timeout=2,
            ) as response:
                if response.status == 200:
                    return

        except Exception as exc:
            last_error = exc
            time.sleep(0.2)

    raise RuntimeError(
        "Desktop lokal server ishga tushmadi"
    ) from last_error


def run_server_smoke(
    *,
    host: str,
    port: int,
) -> None:
    if not _port_is_available(host, port):
        raise RuntimeError(
            f"Port band: {host}:{port}"
        )

    flask_application = (
        _load_flask_application()
    )

    thread = threading.Thread(
        target=_serve_application,
        kwargs={
            "flask_application": (
                flask_application
            ),
            "host": host,
            "port": port,
        },
        name="gold9999-waitress",
        daemon=True,
    )
    thread.start()

    login_url = (
        f"http://{host}:{port}/login"
    )

    _wait_until_ready(
        login_url,
        timeout_seconds=(
            STARTUP_TIMEOUT_SECONDS
        ),
    )

    with urlopen(
        login_url,
        timeout=5,
    ) as response:
        body = response.read()

        if response.status != 200:
            raise RuntimeError(
                "Desktop login HTTP xato"
            )

        if b"Gold" not in body:
            raise RuntimeError(
                "Desktop login sahifasi "
                "tekshiruvi o‘tmadi"
            )

    print("DESKTOP WAITRESS SMOKE OK")
    print("URL:", login_url)


def run_contract_check() -> None:
    flask_application = (
        _load_flask_application()
    )

    client = flask_application.test_client()

    root = client.get("/")
    login = client.get("/login")

    print("APP:", flask_application.name)
    print("ROOT STATUS:", root.status_code)
    print(
        "ROOT LOCATION:",
        root.headers.get("Location"),
    )
    print("LOGIN STATUS:", login.status_code)
    print("LOGIN SIZE:", len(login.data))

    if root.status_code != 302:
        raise RuntimeError(
            "Desktop root redirect xato"
        )

    if (
        root.headers.get("Location")
        != "/login"
    ):
        raise RuntimeError(
            "Desktop login redirect xato"
        )

    if login.status_code != 200:
        raise RuntimeError(
            "Desktop login sahifasi xato"
        )

    print("DESKTOP APP CONTRACT OK")



def create_update_api():
    from desktop.update_api import DesktopUpdateApi
    from desktop.update_config import (
        get_update_manifest_url,
    )
    from desktop.updater import (
        create_desktop_updater,
    )

    manifest_url = get_update_manifest_url()

    updater = (
        create_desktop_updater(manifest_url)
        if manifest_url is not None
        else None
    )

    return DesktopUpdateApi(updater)


def attach_python_update_prompt(
    window,
    update_api,
) -> None:
    state = {
        "running": False,
        "shown": False,
    }
    state_lock = threading.Lock()

    def run_check() -> None:
        try:
            result = update_api.check_for_update()

            if not (
                result.get("success")
                and result.get("enabled")
                and result.get("update_available")
            ):
                return

            payload = json.dumps(
                result,
                ensure_ascii=False,
            )

            script = f"""
            (() => {{
              if (
                typeof window.gold9999ShowUpdateModal
                !== "function"
              ) {{
                return false;
              }}

              window.gold9999ShowUpdateModal(
                {payload}
              );

              return true;
            }})()
            """

            displayed = bool(
                window.evaluate_js(script)
            )

            if displayed:
                with state_lock:
                    state["shown"] = True

                print(
                    "PYTHON UPDATE MODAL SHOWN:",
                    result.get("current_version"),
                    "->",
                    result.get("version"),
                    flush=True,
                )
            else:
                print(
                    "PYTHON UPDATE MODAL WAITING:"
                    " sahifada modal hali tayyor emas",
                    flush=True,
                )

        except Exception as exc:
            print(
                "PYTHON UPDATE CHECK FAILED:",
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )

        finally:
            with state_lock:
                state["running"] = False

    def on_loaded() -> None:
        with state_lock:
            if state["shown"] or state["running"]:
                return

            state["running"] = True

        threading.Thread(
            target=run_check,
            name="Gold9999UpdatePrompt",
            daemon=True,
        ).start()

    window.events.loaded += on_loaded


def run_desktop(
    *,
    host: str,
    port: int,
    data_directory: Path,
    startup_splash=None,
) -> None:
    if not _port_is_available(host, port):
        raise RuntimeError(
            f"Desktop port band: {host}:{port}"
        )

    try:
        import webview
    except ImportError as exc:
        raise RuntimeError(
            "PyWebView o‘rnatilmagan. "
            "requirements-desktop.txt "
            "o‘rnatilishi kerak."
        ) from exc

    def start_local_server() -> None:
        flask_application = (
            _load_flask_application()
        )

        _serve_application(
            flask_application=flask_application,
            host=host,
            port=port,
        )

    server_thread = threading.Thread(
        target=start_local_server,
        name="gold9999-waitress",
        daemon=True,
    )
    server_thread.start()

    login_url = (
        f"http://{host}:{port}/login"
    )

    startup_html = """
<!doctype html>
<html lang="uz">
<head>
  <meta charset="utf-8">
  <meta
    name="viewport"
    content="width=device-width, initial-scale=1"
  >
  <title>Gold 9999</title>
  <style>
    * {
      box-sizing: border-box;
    }

    html,
    body {
      width: 100%;
      height: 100%;
      margin: 0;
    }

    body {
      display: flex;
      align-items: center;
      justify-content: center;
      background:
        radial-gradient(
          circle at top,
          #fff8d8 0%,
          #f3ead0 42%,
          #e6dcc0 100%
        );
      color: #332a16;
      font-family:
        "Segoe UI",
        Arial,
        sans-serif;
    }

    .startup {
      text-align: center;
    }

    .startup-logo {
      margin-bottom: 16px;
      font-size: 42px;
      font-weight: 800;
      letter-spacing: 2px;
    }

    .startup-spinner {
      width: 38px;
      height: 38px;
      margin: 0 auto 18px;
      border: 4px solid rgba(51, 42, 22, 0.16);
      border-top-color: #94711d;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }

    .startup-text {
      font-size: 16px;
      font-weight: 600;
    }

    @keyframes spin {
      to {
        transform: rotate(360deg);
      }
    }
  </style>
</head>
<body>
  <main class="startup">
    <div class="startup-logo">GOLD 9999</div>
    <div class="startup-spinner"></div>
    <div class="startup-text">
      Ilova ishga tushmoqda...
    </div>
  </main>
</body>
</html>
"""

    update_api = create_update_api()

    sync_worker = None
    sync_env_file = (
        Path(data_directory)
        / "offline.env"
    )

    if sync_env_file.is_file():
        try:
            from desktop.sync_worker import (
                create_default_worker,
            )

            sync_worker = create_default_worker(
                data_directory=Path(
                    data_directory
                )
            )
            sync_worker.start()

            print(
                "WINDOWS AUTO SYNC STARTED:",
                sync_env_file,
                flush=True,
            )

        except Exception as exc:
            print(
                "WINDOWS AUTO SYNC START FAILED:",
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )
    else:
        print(
            "WINDOWS AUTO SYNC DISABLED:",
            f"config topilmadi: {sync_env_file}",
            flush=True,
        )

    window = webview.create_window(
        APP_TITLE,
        html=startup_html,
        js_api=update_api,
        width=1440,
        height=900,
        min_size=(1050, 680),
        resizable=True,
        maximized=True,
        text_select=True,
    )

    update_api.set_exit_callback(
        window.destroy
    )

    attach_python_update_prompt(
        window,
        update_api,
    )

    webview_storage_path = os.path.join(
        os.environ.get(
            "LOCALAPPDATA",
            os.path.expanduser("~"),
        ),
        "Gold9999",
        "webview",
    )

    os.makedirs(
        webview_storage_path,
        exist_ok=True,
    )

    def finish_startup() -> None:
        if startup_splash is not None:
            startup_splash.close()

        try:
            _wait_until_ready(
                login_url,
                timeout_seconds=(
                    STARTUP_TIMEOUT_SECONDS
                ),
            )

            window.load_url(login_url)

        except Exception as exc:
            error_message = (
                f"{type(exc).__name__}: {exc}"
            )

            print(
                "DESKTOP STARTUP FAILED:",
                error_message,
                file=sys.stderr,
                flush=True,
            )

            window.load_html(
                """
<!doctype html>
<html lang="uz">
<head>
  <meta charset="utf-8">
  <title>Gold 9999</title>
  <style>
    body {
      margin: 0;
      padding: 48px;
      background: #f6f0df;
      color: #3a2f18;
      font-family: "Segoe UI", Arial, sans-serif;
      text-align: center;
    }

    h1 {
      margin-top: 80px;
    }
  </style>
</head>
<body>
  <h1>Ilovani ishga tushirib bo'lmadi</h1>
  <p>Iltimos, ilovani yopib qayta oching.</p>
</body>
</html>
                """
            )

    try:
        webview.start(
            finish_startup,
            debug=False,
            private_mode=False,
            storage_path=webview_storage_path,
        )
    finally:
        if sync_worker is not None:
            sync_worker.stop()

            print(
                "WINDOWS AUTO SYNC STOPPED",
                flush=True,
            )


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "GOLD9999 Windows desktop launcher."
        )
    )

    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Flask desktop contractini "
            "tekshiradi."
        ),
    )

    parser.add_argument(
        "--server-smoke",
        action="store_true",
        help=(
            "Waitress lokal HTTP serverini "
            "sinaydi."
        ),
    )

    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help=(
            "Desktop data.db saqlanadigan "
            "papka."
        ),
    )

    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
    )

    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
    )

    return parser


def main() -> int:
    arguments = _argument_parser().parse_args()
    mutex_handle = None
    startup_splash = None

    if (
        not arguments.check
        and not arguments.server_smoke
    ):
        mutex_handle = (
            _acquire_single_instance_mutex()
        )

        if mutex_handle is None:
            print(
                "GOLD9999 ALLAQACHON ISHLAYAPTI",
                flush=True,
            )
            return 0

        startup_splash = (
            NativeStartupSplash()
        )
        startup_splash.start()

    try:
        data_directory = (
            configure_desktop_environment(
                arguments.data_dir
            )
        )

        print(
            "DESKTOP DATA DIRECTORY:",
            data_directory,
        )

        if arguments.check:
            run_contract_check()
            return 0

        if arguments.server_smoke:
            run_server_smoke(
                host=arguments.host,
                port=arguments.port,
            )
            return 0

        run_desktop(
            host=arguments.host,
            port=arguments.port,
            data_directory=data_directory,
            startup_splash=startup_splash,
        )

    except (
        RuntimeError,
        OSError,
        URLError,
        ValueError,
    ) as exc:
        print(
            "GOLD9999 DESKTOP FAILED:",
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    finally:
        if startup_splash is not None:
            startup_splash.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
