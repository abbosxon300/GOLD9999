from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")

    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, Decimal):
        return str(value)

    raise TypeError(
        f"JSON serializatsiya qilinmaydigan tur: "
        f"{type(value).__name__}"
    )


def serialize_payload(
    payload: Mapping[str, Any],
) -> str:
    if not isinstance(payload, Mapping):
        raise TypeError("payload Mapping bo‘lishi kerak")

    return json.dumps(
        dict(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=_json_default,
    )


def deserialize_payload(
    payload_json: str,
) -> dict[str, Any]:
    if not isinstance(payload_json, str):
        raise TypeError("payload_json matn bo‘lishi kerak")

    value = json.loads(payload_json)

    if not isinstance(value, dict):
        raise ValueError(
            "Sync payload JSON object bo‘lishi kerak"
        )

    return value
