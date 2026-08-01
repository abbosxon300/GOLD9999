from pathlib import Path

from flask import jsonify, render_template

from services.offline.status import ConnectionStatus
from services.offline.status_service import OfflineStatusService
from services.offline.sync_runner import create_connection_factory


def _status_payload(status) -> dict:
    connection = status.connection.value

    if (
        status.connection
        in {
            ConnectionStatus.OFFLINE,
            ConnectionStatus.ERROR,
        }
        or status.failed_count > 0
        or status.conflict_count > 0
    ):
        indicator = "offline"
        label = (
            "Offline"
            if status.connection == ConnectionStatus.OFFLINE
            else "Xatolik mavjud"
        )
    elif (
        status.connection == ConnectionStatus.SYNCING
        or status.syncing_count > 0
        or status.pending_count > 0
    ):
        indicator = "syncing"
        label = "Sinxronlanmoqda"
    else:
        indicator = "online"
        label = "Online"

    return {
        "connection": connection,
        "indicator": indicator,
        "label": label,
        "pending_count": status.pending_count,
        "syncing_count": status.syncing_count,
        "failed_count": status.failed_count,
        "conflict_count": status.conflict_count,
        "last_sync_at": status.last_sync_at,
        "message": status.message or "",
    }


def register_offline_status_routes(
    app,
    *,
    login_required,
    db_path: str,
):
    connection_factory = create_connection_factory(
        Path(db_path)
    )
    status_service = OfflineStatusService(
        connection_factory
    )

    @app.get("/api/offline/status")
    @login_required
    def offline_status_api():
        status = status_service.get_status()
        return jsonify(_status_payload(status))

    @app.get("/offline/status")
    @login_required
    def offline_status_page():
        status = status_service.get_status()

        return render_template(
            "offline_status.html",
            title="Ulanish holati",
            offline_status=_status_payload(status),
        )
