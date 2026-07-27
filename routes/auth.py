from flask import (
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash


def register_auth_routes(
    app,
    *,
    app_name,
    init_db,
    q1,
    login_required,
    build_home_context,
):
    @app.route(
        "/login",
        methods=["GET", "POST"],
        endpoint="login",
    )
    def login():
        init_db()

        if request.method == "POST":
            username = (
                request.form.get("username") or ""
            ).strip()
            password = request.form.get("password") or ""

            user = q1("""
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
            """, (username,))

            valid = (
                user
                and int(user["is_active"] or 0) == 1
                and check_password_hash(
                    user["password_hash"],
                    password,
                )
            )

            if not valid:
                flash(
                    "Login yoki parol noto‘g‘ri",
                    "danger",
                )
                return render_template(
                    "login.html",
                    app_name=app_name,
                )

            session.clear()
            session["user_id"] = int(user["id"])
            session["username"] = user["username"]
            session["full_name"] = (
                user["full_name"] or user["username"]
            )
            session["role"] = user["role"]
            session["cart"] = {"items": {}}

            return redirect(url_for("home"))

        return render_template(
            "login.html",
            app_name=app_name,
        )

    @app.route("/logout", endpoint="logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/", endpoint="home")
    @app.route("/home")
    @login_required
    def home():
        result = build_home_context()

        # build_home_context admin uchun template context,
        # agent uchun esa /sales redirect Response qaytaradi.
        if not isinstance(result, dict):
            return result

        return render_template(
            "home.html",
            **result,
        )
