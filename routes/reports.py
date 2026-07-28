from flask import render_template

def register_reports_routes(
    app,
    *,
    app_name,
    login_required,
    admin_required,
):
    @app.route("/reports")
    @login_required
    @admin_required
    def reports():
        return render_template(
            "reports.html",
            app_name=app_name,
        )
