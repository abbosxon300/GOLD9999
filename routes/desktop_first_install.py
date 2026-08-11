from __future__ import annotations

import os

from flask import (
    abort,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.security import check_password_hash

from routes.auth import _start_user_session
from services.device_identity import (
    ensure_installation_identity,
)
from services.offline.desktop_provisioning import (
    ActivationRequestError,
    login_provision_device,
    write_offline_environment,
    write_provisioning_state,
)
from services.offline.first_install_runner import (
    run_first_install_setup,
)
from services.runtime_paths import data_directory


DEFAULT_SAAS_URL = (
    "https://gold9999.pythonanywhere.com"
)


def _desktop_runtime() -> bool:
    return (
        str(
            os.environ.get(
                "GOLD9999_DESKTOP_RUNTIME",
                "",
            )
        ).strip()
        == "1"
    )


def _saas_url() -> str:
    return (
        str(
            os.environ.get(
                "GOLD9999_SAAS_URL",
                DEFAULT_SAAS_URL,
            )
        )
        .strip()
        .rstrip("/")
    )


def register_desktop_first_install_routes(
    app,
    *,
    get_db,
) -> None:
    if not callable(get_db):
        raise TypeError(
            "get_db callable bo‘lishi kerak"
        )

    @app.route(
        "/desktop/first-install",
        methods=["GET", "POST"],
    )
    def desktop_first_install():
        if not _desktop_runtime():
            abort(404)

        runtime_dir = data_directory()

        offline_env = (
            runtime_dir
            / "offline.env"
        )

        if (
            request.method == "GET"
            and offline_env.is_file()
        ):
            return redirect(
                url_for("login")
            )

        error = None
        username = ""

        if request.method == "POST":
            username = str(
                request.form.get(
                    "username",
                    "",
                )
            ).strip()

            password = str(
                request.form.get(
                    "password",
                    "",
                )
            )

            if not username or not password:
                error = (
                    "Login va parolni kiriting"
                )

            else:
                db = get_db()

                try:
                    identity = (
                        ensure_installation_identity(
                            db
                        )
                    )

                    state = login_provision_device(
                        base_url=_saas_url(),
                        username=username,
                        password=password,
                        installation_uuid=(
                            identity.installation_uuid
                        ),
                        timeout_seconds=20,
                    )

                    run_first_install_setup(
                        db,
                        base_url=state.base_url,
                        token=(
                            state.device_credential
                        ),
                        installation_uuid=(
                            state.installation_uuid
                        ),
                    )

                    user = db.execute(
                        """
                        SELECT
                            id,
                            username,
                            password_hash,
                            full_name,
                            role,
                            is_active
                        FROM users
                        WHERE username=?
                        LIMIT 1
                        """,
                        (username,),
                    ).fetchone()

                    if (
                        user is None
                        or int(
                            user["is_active"] or 0
                        ) != 1
                        or not check_password_hash(
                            user["password_hash"],
                            password,
                        )
                    ):
                        raise RuntimeError(
                            "Lokal foydalanuvchi "
                            "tayyorlanmadi"
                        )

                    write_provisioning_state(
                        data_directory=runtime_dir,
                        state=state,
                    )

                    write_offline_environment(
                        data_directory=runtime_dir,
                        state=state,
                    )

                    session_user = {
                        "user_id": int(
                            user["id"]
                        ),
                        "username": str(
                            user["username"]
                        ),
                        "full_name": (
                            None
                            if user["full_name"]
                            is None
                            else str(
                                user["full_name"]
                            )
                        ),
                        "role": str(
                            user["role"]
                        ),
                    }

                    _start_user_session(
                        session_user
                    )

                    db.commit()

                    return redirect(
                        url_for("home")
                    )

                except ActivationRequestError as exc:
                    try:
                        db.rollback()
                    except Exception:
                        pass

                    error = str(exc)

                except Exception as exc:
                    try:
                        db.rollback()
                    except Exception:
                        pass

                    error = (
                        f"Tizimni tayyorlab "
                        f"bo‘lmadi: {exc}"
                    )

        return render_template(
            "desktop_first_install.html",
            app_name="Gold 9999",
            entered_username=username,
            error=error,
        )


__all__ = [
    "register_desktop_first_install_routes",
]
