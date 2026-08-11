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
from services.offline.provisioning import (
    ExpiredActivationCodeError,
    InvalidActivationCodeError,
    ProvisioningError,
    RevokedActivationCodeError,
    UsedActivationCodeError,
    provision_device,
    validate_device_credential,
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


def _offline_request_authorized(
    app: Flask,
    db,
) -> bool:
    supplied_token = _bearer_token()

    if supplied_token is None:
        return False

    expected_token = str(
        app.config.get(
            "OFFLINE_SYNC_TOKEN",
            "",
        )
    ).strip()

    if (
        expected_token
        and hmac.compare_digest(
            supplied_token,
            expected_token,
        )
    ):
        return True

    installation_uuid = str(
        request.headers.get(
            "X-Gold9999-Installation-UUID",
            "",
        )
    ).strip()

    if not installation_uuid:
        return False

    try:
        valid = validate_device_credential(
            db,
            installation_uuid=installation_uuid,
            credential=supplied_token,
        )

        if valid:
            db.commit()

        return bool(valid)

    except (
        ProvisioningError,
        TypeError,
        ValueError,
    ):
        try:
            db.rollback()
        except Exception:
            pass

        return False
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
        db = get_db()

        if not _offline_request_authorized(
            app,
            db,
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



    @app.get("/api/offline/bootstrap")
    def offline_bootstrap():
        db = get_db()

        if not _offline_request_authorized(
            app,
            db,
        ):
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), 401

        try:
            db = get_db()

            users = db.execute(
                """
                SELECT
                    username,
                    password_hash,
                    full_name,
                    role,
                    is_active,
                    created_at
                FROM users
                ORDER BY id
                """
            ).fetchall()

            agents = db.execute(
                """
                SELECT
                    id,
                    full_name,
                    phone,
                    is_active
                FROM agents
                ORDER BY id
                """
            ).fetchall()

            categories = db.execute(
                """
                SELECT
                    entity_uuid,
                    sync_version,
                    name,
                    sort_order,
                    is_active,
                    created_at
                FROM categories
                WHERE entity_uuid IS NOT NULL
                ORDER BY sort_order, id
                """
            ).fetchall()

            products = db.execute(
                """
                SELECT
                    p.entity_uuid,
                    p.sync_version,
                    p.name,
                    p.sell_price_default_uzs,
                    p.is_active,
                    p.created_at,
                    c.entity_uuid AS category_uuid
                FROM products p
                JOIN categories c
                  ON c.id=p.category_id
                WHERE p.entity_uuid IS NOT NULL
                  AND c.entity_uuid IS NOT NULL
                ORDER BY p.id
                """
            ).fetchall()

            database_uuid = (
                ensure_database_identity(db)
            )

        except Exception:
            app.logger.exception(
                "Offline bootstrap endpoint failed"
            )

            return jsonify({
                "success": False,
                "message": (
                    "Offline bootstrap server xatosi"
                ),
            }), 500

        return jsonify({
            "success": True,
            "schema_version": 1,
            "database_uuid": database_uuid,
            "users": [
                {
                    "username": str(
                        row["username"]
                    ),
                    "password_hash": str(
                        row["password_hash"]
                    ),
                    "full_name": (
                        None
                        if row["full_name"] is None
                        else str(row["full_name"])
                    ),
                    "role": str(row["role"]),
                    "is_active": int(
                        row["is_active"]
                    ),
                    "created_at": str(
                        row["created_at"]
                    ),
                }
                for row in users
            ],
            "agents": [
                {
                    "server_id": int(row["id"]),
                    "full_name": (
                        None
                        if row["full_name"] is None
                        else str(row["full_name"])
                    ),
                    "phone": (
                        None
                        if row["phone"] is None
                        else str(row["phone"])
                    ),
                    "is_active": int(
                        row["is_active"]
                    ),
                }
                for row in agents
            ],
            "categories": [
                {
                    "entity_uuid": str(
                        row["entity_uuid"]
                    ),
                    "sync_version": int(
                        row["sync_version"]
                    ),
                    "name": str(row["name"]),
                    "sort_order": int(
                        row["sort_order"]
                    ),
                    "is_active": int(
                        row["is_active"]
                    ),
                    "created_at": str(
                        row["created_at"]
                    ),
                }
                for row in categories
            ],
            "products": [
                {
                    "entity_uuid": str(
                        row["entity_uuid"]
                    ),
                    "sync_version": int(
                        row["sync_version"]
                    ),
                    "category_uuid": str(
                        row["category_uuid"]
                    ),
                    "name": str(row["name"]),
                    "sell_price_default_uzs": float(
                        row[
                            "sell_price_default_uzs"
                        ]
                    ),
                    "is_active": int(
                        row["is_active"]
                    ),
                    "created_at": str(
                        row["created_at"]
                    ),
                }
                for row in products
            ],
        })


    @app.post("/api/offline/activate")
    def offline_activate():
        if not request.is_json:
            return jsonify({
                "success": False,
                "message": (
                    "Content-Type application/json "
                    "bo?lishi kerak"
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
                    "bo?lishi kerak"
                ),
            }), 400

        expected_fields = {
            "activation_code",
            "installation_uuid",
        }

        if set(body) != expected_fields:
            return jsonify({
                "success": False,
                "message": (
                    "Request faqat activation_code "
                    "va installation_uuid "
                    "maydonlariga ega bo?lishi kerak"
                ),
            }), 400

        try:
            db = get_db()

            device = provision_device(
                db,
                activation_code=body[
                    "activation_code"
                ],
                installation_uuid=body[
                    "installation_uuid"
                ],
            )

            db.commit()

        except (
            InvalidActivationCodeError,
            ExpiredActivationCodeError,
            UsedActivationCodeError,
            RevokedActivationCodeError,
            ProvisioningError,
            TypeError,
            ValueError,
        ) as exc:
            try:
                db.rollback()
            except Exception:
                pass

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
                "Offline activation endpoint failed"
            )

            return jsonify({
                "success": False,
                "message": (
                    "Offline activation server xatosi"
                ),
            }), 500

        return jsonify({
            "success": True,
            "installation_uuid": (
                device.installation_uuid
            ),
            "device_credential": (
                device.credential
            ),
        })


    @app.post("/api/offline/push")
    def offline_push():
        db = get_db()

        if not _offline_request_authorized(
            app,
            db,
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
