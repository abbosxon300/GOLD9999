from __future__ import annotations

from datetime import timedelta

from flask import (
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

from services.db import get_db
from services.device_identity import (
    ensure_installation_identity,
)
from services.remember_tokens import (
    issue_token,
    revoke_token,
    validate_token,
)


REMEMBER_COOKIE_NAME = "gold9999_remember_token"
REMEMBER_COOKIE_DAYS = 30
REMEMBER_COOKIE_SECONDS = (
    REMEMBER_COOKIE_DAYS * 24 * 60 * 60
)


def _start_user_session(user) -> None:
    session.clear()
    session["user_id"] = int(user["user_id"])
    session["username"] = user["username"]
    session["full_name"] = (
        user["full_name"]
        or user["username"]
    )
    session["role"] = user["role"]
    session["cart"] = {"items": {}}


def _cookie_options() -> dict[str, object]:
    return {
        "max_age": REMEMBER_COOKIE_SECONDS,
        "httponly": True,
        "secure": False,
        "samesite": "Lax",
        "path": "/",
    }


def register_auth_routes(
    app,
    *,
    app_name,
    init_db,
    q1,
    login_required,
    build_home_context,
):
    @app.before_request
    def restore_remembered_login():
        if session.get("user_id"):
            return None

        raw_token = str(
            request.cookies.get(
                REMEMBER_COOKIE_NAME,
                "",
            )
        ).strip()

        if not raw_token:
            return None

        init_db()
        connection = get_db()

        identity = ensure_installation_identity(
            connection
        )

        remembered_user = validate_token(
            connection,
            raw_token=raw_token,
            device_id=identity.installation_uuid,
        )

        if remembered_user is None:
            g.clear_remember_cookie = True
            return None

        connection.commit()

        _start_user_session(
            remembered_user
        )

        return None

    @app.after_request
    def clear_invalid_remember_cookie(response):
        if getattr(
            g,
            "clear_remember_cookie",
            False,
        ):
            response.delete_cookie(
                REMEMBER_COOKIE_NAME,
                path="/",
                samesite="Lax",
            )

        return response

    @app.route(
        "/login",
        methods=["GET", "POST"],
        endpoint="login",
    )
    def login():
        init_db()

        if session.get("user_id"):
            return redirect(
                url_for("home")
            )

        if request.method == "POST":
            username = (
                request.form.get("username")
                or ""
            ).strip()

            password = (
                request.form.get("password")
                or ""
            )

            remember_me = (
                request.form.get("remember_me")
                == "1"
            )

            user = q1(
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
            )

            valid = (
                user
                and int(
                    user["is_active"] or 0
                ) == 1
                and check_password_hash(
                    user["password_hash"],
                    password,
                )
            )

            if not valid:
                flash(
                    "Login yoki parol noto?g?ri",
                    "danger",
                )

                return render_template(
                    "login.html",
                    app_name=app_name,
                    entered_username=username,
                    remember_checked=remember_me,
                )

            session_user = {
                "user_id": int(user["id"]),
                "username": user["username"],
                "full_name": (
                    user["full_name"]
                    or user["username"]
                ),
                "role": user["role"],
            }

            _start_user_session(
                session_user
            )

            response = redirect(
                url_for("home")
            )

            if remember_me:
                connection = get_db()

                identity = (
                    ensure_installation_identity(
                        connection
                    )
                )

                connection.execute(
                    """
                    UPDATE remember_tokens
                    SET revoked_at=CURRENT_TIMESTAMP
                    WHERE user_id=?
                      AND device_id=?
                      AND revoked_at IS NULL
                    """,
                    (
                        int(user["id"]),
                        identity.installation_uuid,
                    ),
                )

                remember_token = issue_token(
                    connection,
                    user_id=int(user["id"]),
                    device_id=(
                        identity.installation_uuid
                    ),
                    valid_days=(
                        REMEMBER_COOKIE_DAYS
                    ),
                )

                connection.commit()

                response.set_cookie(
                    REMEMBER_COOKIE_NAME,
                    remember_token.raw_token,
                    **_cookie_options(),
                )
            else:
                response.delete_cookie(
                    REMEMBER_COOKIE_NAME,
                    path="/",
                    samesite="Lax",
                )

            return response

        return render_template(
            "login.html",
            app_name=app_name,
            entered_username="",
            remember_checked=False,
        )

    @app.route(
        "/logout",
        endpoint="logout",
    )
    def logout():
        raw_token = str(
            request.cookies.get(
                REMEMBER_COOKIE_NAME,
                "",
            )
        ).strip()

        if raw_token:
            try:
                connection = get_db()

                identity = (
                    ensure_installation_identity(
                        connection
                    )
                )

                revoke_token(
                    connection,
                    raw_token=raw_token,
                    device_id=(
                        identity.installation_uuid
                    ),
                )

                connection.commit()

            except Exception:
                connection = get_db()
                connection.rollback()

        session.clear()

        response = redirect(
            url_for("login")
        )

        response.delete_cookie(
            REMEMBER_COOKIE_NAME,
            path="/",
            samesite="Lax",
        )

        return response

    @app.route(
        "/",
        endpoint="home",
    )
    @app.route("/home")
    @login_required
    def home():
        result = build_home_context()

        # build_home_context admin uchun
        # template context, agent uchun esa
        # /sales redirect Response qaytaradi.
        if not isinstance(result, dict):
            return result

        return render_template(
            "home.html",
            **result,
        )
