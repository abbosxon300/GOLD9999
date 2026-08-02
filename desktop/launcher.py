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

    flask_application = (
        _load_flask_application()
    )

    server_thread = threading.Thread(
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
    server_thread.start()

    login_url = (
        f"http://{host}:{port}/login"
    )

    _wait_until_ready(
        login_url,
        timeout_seconds=(
            STARTUP_TIMEOUT_SECONDS
        ),
    )

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
        login_url,
        js_api=update_api,
        width=1440,
        height=900,
        min_size=(1050, 680),
        resizable=True,
        maximized=True,
        text_select=True,
    )

    attach_python_update_prompt(
        window,
        update_api,
    )

    try:
        webview.start(
            debug=False,
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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
