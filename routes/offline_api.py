from __future__ import annotations

import hmac
from collections.abc import Callable
from typing import Any

from flask import (
    Flask,
    jsonify,
    request,
)

from services.device_identity import (
    ensure_database_identity,
)
from services.offline.pull_service import (
    DEFAULT_PULL_LIMIT,
    InvalidPullRequestError,
    build_pull_response,
    pull_response_to_dict,
)
from services.offline.push_service import (
    InvalidPushRequestError,
    apply_push_batch,
    sync_result_to_dict,
)


def _bearer_token() -> str | None:
    authorization = str(
        request.headers.get(
            "Authorization",
            "",
        )
    ).strip()

    prefix = "Bearer "

    if not authorization.startswith(prefix):
        return None

    token = authorization[len(prefix):].strip()

    return token or None


def register_offline_api_routes(
    app: Flask,
    *,
    get_db: Callable[[], Any],
) -> None:
    if not callable(get_db):
        raise TypeError(
            "get_db callable bo‘lishi kerak"
        )

    @app.get("/api/offline/pull")
    def offline_pull():
        expected_token = str(
            app.config.get(
                "OFFLINE_SYNC_TOKEN",
                "",
            )
        ).strip()

        if not expected_token:
            return jsonify({
                "success": False,
                "message": (
                    "OFFLINE_SYNC_TOKEN "
                    "serverda sozlanmagan"
                ),
            }), 503

        supplied_token = _bearer_token()

        if (
            supplied_token is None
            or not hmac.compare_digest(
                supplied_token,
                expected_token,
            )
        ):
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), 401

        cursor = request.args.get("cursor")

        try:
            limit = int(
                request.args.get(
                    "limit",
                    DEFAULT_PULL_LIMIT,
                )
            )

            db = get_db()

            response = build_pull_response(
                db,
                cursor=cursor,
                limit=limit,
                device_uuid=(
                    ensure_database_identity(db)
                ),
            )

        except (
            InvalidPullRequestError,
            TypeError,
            ValueError,
        ) as exc:
            return jsonify({
                "success": False,
                "message": str(exc),
            }), 400

        except Exception:
            app.logger.exception(
                "Offline pull endpoint failed"
            )

            return jsonify({
                "success": False,
                "message": (
                    "Offline pull server xatosi"
                ),
            }), 500

        return jsonify(
            pull_response_to_dict(response)
        )


    @app.post("/api/offline/push")
    def offline_push():
        expected_token = str(
            app.config.get(
                "OFFLINE_SYNC_TOKEN",
                "",
            )
        ).strip()

        if not expected_token:
            return jsonify({
                "success": False,
                "message": (
                    "OFFLINE_SYNC_TOKEN "
                    "serverda sozlanmagan"
                ),
            }), 503

        supplied_token = _bearer_token()

        if (
            supplied_token is None
            or not hmac.compare_digest(
                supplied_token,
                expected_token,
            )
        ):
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), 401

        if not request.is_json:
            return jsonify({
                "success": False,
                "message": (
                    "Content-Type application/json "
                    "bo‘lishi kerak"
                ),
            }), 415

        body = request.get_json(
            silent=True
        )

        if not isinstance(body, dict):
            return jsonify({
                "success": False,
                "message": (
                    "Request body JSON object "
                    "bo‘lishi kerak"
                ),
            }), 400

        if set(body) != {"records"}:
            return jsonify({
                "success": False,
                "message": (
                    "Request faqat records "
                    "maydoniga ega bo‘lishi kerak"
                ),
            }), 400

        try:
            db = get_db()

            results = apply_push_batch(
                db,
                body["records"],
            )

        except InvalidPushRequestError as exc:
            return jsonify({
                "success": False,
                "message": str(exc),
            }), 400

        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

            app.logger.exception(
                "Offline push endpoint failed"
            )

            return jsonify({
                "success": False,
                "message": (
                    "Offline push server xatosi"
                ),
            }), 500

        return jsonify({
            "results": [
                sync_result_to_dict(result)
                for result in results
            ]
        })


__all__ = [
    "register_offline_api_routes",
]
