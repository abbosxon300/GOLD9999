from __future__ import annotations

from flask import Flask, jsonify, request

from services.offline.saas_provisioning import (
    InactiveUserError,
    InvalidLoginError,
    SaasProvisioningError,
    TenantError,
    provision_device_by_login,
)


def register_saas_provisioning_routes(
    app: Flask,
    *,
    get_db,
) -> None:
    if not callable(get_db):
        raise TypeError(
            "get_db callable bo‘lishi kerak"
        )

    @app.post(
        "/api/offline/login-provision"
    )
    def offline_login_provision():
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

        if not isinstance(
            body,
            dict,
        ):
            return jsonify({
                "success": False,
                "message": (
                    "Request body JSON object "
                    "bo‘lishi kerak"
                ),
            }), 400

        expected = {
            "username",
            "password",
            "installation_uuid",
        }

        if set(body) != expected:
            return jsonify({
                "success": False,
                "message": (
                    "username, password va "
                    "installation_uuid kerak"
                ),
            }), 400

        db = get_db()

        try:
            result = provision_device_by_login(
                db,
                username=body["username"],
                password=body["password"],
                installation_uuid=(
                    body["installation_uuid"]
                ),
            )

            db.commit()

        except InvalidLoginError:
            db.rollback()

            return jsonify({
                "success": False,
                "message": (
                    "Login yoki parol noto‘g‘ri"
                ),
            }), 401

        except (
            InactiveUserError,
            TenantError,
        ) as exc:
            db.rollback()

            return jsonify({
                "success": False,
                "message": str(exc),
            }), 403

        except (
            SaasProvisioningError,
            TypeError,
            ValueError,
        ) as exc:
            db.rollback()

            return jsonify({
                "success": False,
                "message": str(exc),
            }), 400

        except Exception:
            db.rollback()
            raise

        return jsonify({
            "success": True,
            "tenant_id": result.tenant_id,
            "user_id": result.user_id,
            "username": result.username,
            "installation_uuid": (
                result.installation_uuid
            ),
            "device_credential": (
                result.credential
            ),
        })
