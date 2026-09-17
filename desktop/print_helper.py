from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, request

from desktop.printer_api import (
    list_windows_printers,
    load_printer_settings,
)
from desktop.printer_service import print_receipt


HOST = "127.0.0.1"
PORT = 8766

ALLOWED_ORIGINS = {
    "https://gold9999.pythonanywhere.com",
    "http://127.0.0.1:8765",
    "http://localhost:8765",
}


def _origin_allowed() -> bool:
    origin = str(
        request.headers.get("Origin") or ""
    ).strip()

    return (
        not origin
        or origin in ALLOWED_ORIGINS
    )


def _effective_settings() -> dict[str, Any]:
    settings = load_printer_settings()

    printer_name = str(
        settings.get("printer_name") or ""
    ).strip()

    if not printer_name:
        info = list_windows_printers()

        printer_name = str(
            info.get("default_printer") or ""
        ).strip()

    if not printer_name:
        raise RuntimeError(
            "Windows default printer topilmadi"
        )

    settings = dict(settings)
    settings["printer_name"] = printer_name

    return settings


def create_print_helper_app() -> Flask:
    app = Flask("gold9999_print_helper")

    @app.before_request
    def check_origin():
        if not _origin_allowed():
            return jsonify({
                "ok": False,
                "error": "Origin ruxsat etilmagan",
            }), 403

        return None

    @app.after_request
    def cors(response):
        origin = str(
            request.headers.get("Origin") or ""
        ).strip()

        if origin in ALLOWED_ORIGINS:
            response.headers[
                "Access-Control-Allow-Origin"
            ] = origin

            response.headers[
                "Access-Control-Allow-Methods"
            ] = "GET, POST, OPTIONS"

            response.headers[
                "Access-Control-Allow-Headers"
            ] = (
                "Content-Type, "
                "X-Gold9999-Print"
            )

            response.headers[
                "Access-Control-Allow-Private-Network"
            ] = "true"

            response.headers["Vary"] = "Origin"

        return response

    @app.route(
        "/health",
        methods=["GET", "OPTIONS"],
    )
    def health():
        if request.method == "OPTIONS":
            return "", 204

        return jsonify({
            "ok": True,
            "service": "gold9999-print-helper",
        })

    @app.route(
        "/print",
        methods=["POST", "OPTIONS"],
    )
    def print_sale():
        if request.method == "OPTIONS":
            return "", 204

        if (
            request.headers.get(
                "X-Gold9999-Print"
            )
            != "1"
        ):
            return jsonify({
                "ok": False,
                "error": "Print header noto‘g‘ri",
            }), 403

        payload = request.get_json(
            silent=True
        )

        if not isinstance(payload, dict):
            return jsonify({
                "ok": False,
                "error": "Chek ma’lumoti noto‘g‘ri",
            }), 400

        try:
            settings = _effective_settings()

            result = print_receipt(
                payload,
                settings,
            )

            return jsonify({
                "ok": True,
                **result,
            })

        except Exception as exc:
            return jsonify({
                "ok": False,
                "error": str(exc),
            }), 500

    return app


def run_print_helper() -> None:
    from waitress import serve

    serve(
        create_print_helper_app(),
        host=HOST,
        port=PORT,
        threads=4,
    )


__all__ = [
    "HOST",
    "PORT",
    "create_print_helper_app",
    "run_print_helper",
]
