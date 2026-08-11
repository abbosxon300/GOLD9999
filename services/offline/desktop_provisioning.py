from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_ACTIVATION_TIMEOUT_SECONDS = 10.0

PROVISIONING_FILE_NAME = "provisioning.json"


class DesktopProvisioningError(RuntimeError):
    pass


class ActivationRequestError(DesktopProvisioningError):
    pass


class ProvisioningStateError(DesktopProvisioningError):
    pass


@dataclass(frozen=True, slots=True)
class ProvisioningState:
    base_url: str
    installation_uuid: str
    device_credential: str


def _required_text(
    value: object,
    *,
    field_name: str,
) -> str:
    if not isinstance(value, str):
        raise DesktopProvisioningError(
            f"{field_name} matn bo‘lishi kerak"
        )

    normalized = value.strip()

    if not normalized:
        raise DesktopProvisioningError(
            f"{field_name} bo‘sh bo‘lmasligi kerak"
        )

    return normalized


def provisioning_path(
    data_directory: str | Path,
) -> Path:
    return (
        Path(data_directory)
        .expanduser()
        .resolve()
        / PROVISIONING_FILE_NAME
    )


def activate_device(
    *,
    base_url: str,
    activation_code: str,
    installation_uuid: str,
    timeout_seconds: float = (
        DEFAULT_ACTIVATION_TIMEOUT_SECONDS
    ),
    opener: Callable[..., object] = urlopen,
) -> ProvisioningState:
    normalized_url = _required_text(
        base_url,
        field_name="base_url",
    ).rstrip("/")

    normalized_code = _required_text(
        activation_code,
        field_name="activation_code",
    )

    normalized_uuid = _required_text(
        installation_uuid,
        field_name="installation_uuid",
    )

    timeout = float(timeout_seconds)

    if timeout <= 0:
        raise ValueError(
            "timeout_seconds musbat bo‘lishi kerak"
        )

    payload = json.dumps(
        {
            "activation_code": normalized_code,
            "installation_uuid": normalized_uuid,
        }
    ).encode("utf-8")

    request = Request(
        normalized_url + "/api/offline/activate",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    try:
        response = opener(
            request,
            timeout=timeout,
        )

        try:
            raw = response.read()
        finally:
            close = getattr(
                response,
                "close",
                None,
            )

            if callable(close):
                close()

    except HTTPError as exc:
        try:
            body = exc.read()
        except Exception:
            body = b""

        message = (
            f"Activation HTTP xato: {exc.code}"
        )

        try:
            parsed = json.loads(
                body.decode("utf-8")
            )

            server_message = parsed.get(
                "message"
            )

            if isinstance(
                server_message,
                str,
            ) and server_message.strip():
                message = server_message.strip()

        except Exception:
            pass

        raise ActivationRequestError(
            message
        ) from exc

    except (
        URLError,
        TimeoutError,
        OSError,
    ) as exc:
        raise ActivationRequestError(
            "Activation serveriga ulanib bo‘lmadi"
        ) from exc

    try:
        body = json.loads(
            raw.decode("utf-8")
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise ActivationRequestError(
            "Activation server javobi noto‘g‘ri"
        ) from exc

    if not isinstance(body, dict):
        raise ActivationRequestError(
            "Activation server javobi object emas"
        )

    if body.get("success") is not True:
        message = body.get(
            "message"
        )

        raise ActivationRequestError(
            str(
                message
                or "Activation muvaffaqiyatsiz"
            )
        )

    returned_uuid = _required_text(
        body.get(
            "installation_uuid"
        ),
        field_name="installation_uuid",
    )

    if returned_uuid != normalized_uuid:
        raise ActivationRequestError(
            "Server installation_uuid mos emas"
        )

    credential = _required_text(
        body.get(
            "device_credential"
        ),
        field_name="device_credential",
    )

    return ProvisioningState(
        base_url=normalized_url,
        installation_uuid=returned_uuid,
        device_credential=credential,
    )


def write_provisioning_state(
    *,
    data_directory: str | Path,
    state: ProvisioningState,
) -> Path:
    if not isinstance(
        state,
        ProvisioningState,
    ):
        raise TypeError(
            "state ProvisioningState bo‘lishi kerak"
        )

    path = provisioning_path(
        data_directory
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = json.dumps(
        {
            "version": 1,
            "base_url": state.base_url,
            "installation_uuid": (
                state.installation_uuid
            ),
            "device_credential": (
                state.device_credential
            ),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ) + "\n"

    fd, temp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )

    temp_path = Path(
        temp_name
    )

    try:
        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as handle:
            handle.write(
                payload
            )

            handle.flush()
            os.fsync(
                handle.fileno()
            )

        os.replace(
            temp_path,
            path,
        )

    except Exception:
        try:
            temp_path.unlink(
                missing_ok=True
            )
        except Exception:
            pass

        raise

    return path


def load_provisioning_state(
    data_directory: str | Path,
) -> ProvisioningState | None:
    path = provisioning_path(
        data_directory
    )

    if not path.is_file():
        return None

    try:
        raw = path.read_text(
            encoding="utf-8-sig"
        )

        body = json.loads(
            raw
        )

    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise ProvisioningStateError(
            "Provisioning config o‘qilmadi"
        ) from exc

    if not isinstance(body, dict):
        raise ProvisioningStateError(
            "Provisioning config object emas"
        )

    if body.get("version") != 1:
        raise ProvisioningStateError(
            "Provisioning config versiyasi noto‘g‘ri"
        )

    return ProvisioningState(
        base_url=_required_text(
            body.get(
                "base_url"
            ),
            field_name="base_url",
        ),
        installation_uuid=_required_text(
            body.get(
                "installation_uuid"
            ),
            field_name="installation_uuid",
        ),
        device_credential=_required_text(
            body.get(
                "device_credential"
            ),
            field_name="device_credential",
        ),
    )


__all__ = [
    "DEFAULT_ACTIVATION_TIMEOUT_SECONDS",
    "PROVISIONING_FILE_NAME",
    "ActivationRequestError",
    "DesktopProvisioningError",
    "ProvisioningState",
    "ProvisioningStateError",
    "activate_device",
    "load_provisioning_state",
    "provisioning_path",
    "write_provisioning_state",
]
