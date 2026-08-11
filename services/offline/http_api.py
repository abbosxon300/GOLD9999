from __future__ import annotations

import json
import socket
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import (
    OpenerDirector,
    Request,
    build_opener,
)

from services.offline.models import (
    PullBatch,
    RemoteChange,
    SyncRecord,
    SyncResult,
)


DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 0.25

_RETRYABLE_STATUS_CODES = frozenset(
    {
        408,
        425,
        429,
        500,
        502,
        503,
        504,
    }
)


class HttpSyncApiError(RuntimeError):
    """HTTP sync transport bazaviy xatosi."""


class HttpSyncTransportError(HttpSyncApiError):
    """Server bilan HTTP aloqa o‘rnatilmadi."""


class HttpSyncResponseError(HttpSyncApiError):
    """Server noto‘g‘ri HTTP yoki JSON javob qaytardi."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code


def _required_text(
    value: object,
    *,
    field_name: str,
) -> str:
    if not isinstance(value, str):
        raise TypeError(
            f"{field_name} matn bo‘lishi kerak"
        )

    normalized = value.strip()

    if not normalized:
        raise ValueError(
            f"{field_name} bo‘sh bo‘lishi mumkin emas"
        )

    return normalized


def _positive_float(
    value: object,
    *,
    field_name: str,
) -> float:
    if isinstance(value, bool):
        raise TypeError(
            f"{field_name} musbat son bo‘lishi kerak"
        )

    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"{field_name} musbat son bo‘lishi kerak"
        ) from exc

    if normalized <= 0:
        raise ValueError(
            f"{field_name} musbat son bo‘lishi kerak"
        )

    return normalized


def _positive_integer(
    value: object,
    *,
    field_name: str,
) -> int:
    if isinstance(value, bool):
        raise TypeError(
            f"{field_name} musbat integer bo‘lishi kerak"
        )

    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"{field_name} musbat integer bo‘lishi kerak"
        ) from exc

    if normalized <= 0:
        raise ValueError(
            f"{field_name} musbat integer bo‘lishi kerak"
        )

    return normalized


def _non_negative_float(
    value: object,
    *,
    field_name: str,
) -> float:
    if isinstance(value, bool):
        raise TypeError(
            f"{field_name} manfiy bo‘lmagan son "
            "bo‘lishi kerak"
        )

    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"{field_name} manfiy bo‘lmagan son "
            "bo‘lishi kerak"
        ) from exc

    if normalized < 0:
        raise ValueError(
            f"{field_name} manfiy bo‘lmasligi kerak"
        )

    return normalized


def _datetime_to_wire(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise TypeError(
            "occurred_at datetime bo‘lishi kerak"
        )

    normalized = value

    if normalized.tzinfo is None:
        normalized = normalized.replace(
            tzinfo=timezone.utc
        )

    return normalized.isoformat(
        timespec="microseconds"
    )


def _datetime_from_wire(
    value: object,
    *,
    field_name: str,
) -> datetime:
    normalized = _required_text(
        value,
        field_name=field_name,
    )

    try:
        parsed = datetime.fromisoformat(
            normalized
        )
    except ValueError as exc:
        raise HttpSyncResponseError(
            f"{field_name} noto‘g‘ri datetime"
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed


def _optional_integer(
    value: object,
    *,
    field_name: str,
) -> int | None:
    if value is None:
        return None

    return _positive_integer(
        value,
        field_name=field_name,
    )


def _optional_text(
    value: object,
    *,
    field_name: str,
) -> str | None:
    if value is None:
        return None

    return _required_text(
        value,
        field_name=field_name,
    )


def _mapping(
    value: object,
    *,
    field_name: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise HttpSyncResponseError(
            f"{field_name} JSON object bo‘lishi kerak"
        )

    return dict(value)


class HttpSyncApi:
    """
    SyncApi protokolining HTTP implementatsiyasi.

    Server kontrakti:

    POST /api/offline/push
    {
        "records": [...]
    }

    {
        "results": [...]
    }

    GET /api/offline/pull?cursor=...&limit=100

    {
        "changes": [...],
        "next_cursor": "...",
        "batch_id": "...",
        "has_more": false
    }
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        installation_uuid: str | None = None,
        timeout_seconds: float = (
            DEFAULT_TIMEOUT_SECONDS
        ),
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_backoff_seconds: float = (
            DEFAULT_RETRY_BACKOFF_SECONDS
        ),
        opener: OpenerDirector | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        normalized_base_url = _required_text(
            base_url,
            field_name="base_url",
        ).rstrip("/")

        if not normalized_base_url.startswith(
            ("http://", "https://")
        ):
            raise ValueError(
                "base_url http:// yoki https:// "
                "bilan boshlanishi kerak"
            )

        self._base_url = normalized_base_url
        self._token = _required_text(
            token,
            field_name="token",
        )
        self._installation_uuid = str(
            installation_uuid or ""
        ).strip()
        self._timeout_seconds = _positive_float(
            timeout_seconds,
            field_name="timeout_seconds",
        )
        self._max_attempts = _positive_integer(
            max_attempts,
            field_name="max_attempts",
        )
        self._retry_backoff_seconds = (
            _non_negative_float(
                retry_backoff_seconds,
                field_name=(
                    "retry_backoff_seconds"
                ),
            )
        )

        if opener is not None and not hasattr(
            opener,
            "open",
        ):
            raise TypeError(
                "opener open() metodiga ega "
                "bo‘lishi kerak"
            )

        if not callable(sleep):
            raise TypeError(
                "sleep callable bo‘lishi kerak"
            )

        self._opener = opener or build_opener()
        self._sleep = sleep

    def push(
        self,
        records: tuple[SyncRecord, ...],
    ) -> tuple[SyncResult, ...]:
        if not isinstance(records, tuple):
            raise TypeError(
                "records tuple bo‘lishi kerak"
            )

        for record in records:
            if not isinstance(record, SyncRecord):
                raise TypeError(
                    "records ichidagi har bir yozuv "
                    "SyncRecord bo‘lishi kerak"
                )

        if not records:
            return ()

        response = self._request_json(
            method="POST",
            path="/api/offline/push",
            payload={
                "records": [
                    self._record_to_wire(record)
                    for record in records
                ]
            },
        )

        raw_results = response.get("results")

        if not isinstance(raw_results, list):
            raise HttpSyncResponseError(
                "Push javobida results ro‘yxati kerak"
            )

        results = tuple(
            self._sync_result_from_wire(
                raw_result
            )
            for raw_result in raw_results
        )

        if len(results) != len(records):
            raise HttpSyncResponseError(
                "Push results soni records soniga "
                "teng emas"
            )

        return results

    def pull(
        self,
        *,
        cursor: str | None,
        limit: int = 100,
    ) -> PullBatch:
        normalized_limit = _positive_integer(
            limit,
            field_name="limit",
        )

        query: dict[str, str] = {
            "limit": str(normalized_limit),
        }

        if cursor is not None:
            query["cursor"] = _required_text(
                cursor,
                field_name="cursor",
            )

        response = self._request_json(
            method="GET",
            path=(
                "/api/offline/pull?"
                + urlencode(query)
            ),
        )

        raw_changes = response.get("changes")

        if not isinstance(raw_changes, list):
            raise HttpSyncResponseError(
                "Pull javobida changes ro‘yxati kerak"
            )

        has_more = response.get("has_more")

        if not isinstance(has_more, bool):
            raise HttpSyncResponseError(
                "Pull javobida has_more boolean kerak"
            )

        next_cursor = response.get("next_cursor")

        if next_cursor is not None:
            next_cursor = _required_text(
                next_cursor,
                field_name="next_cursor",
            )

        return PullBatch(
            changes=tuple(
                self._remote_change_from_wire(
                    raw_change
                )
                for raw_change in raw_changes
            ),
            next_cursor=next_cursor,
            batch_id=_required_text(
                response.get("batch_id"),
                field_name="batch_id",
            ),
            has_more=has_more,
        )

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"

        body: bytes | None = None

        if payload is not None:
            body = json.dumps(
                dict(payload),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")

        headers = {
            "Accept": "application/json",
            "Authorization": (
                f"Bearer {self._token}"
            ),
            "Content-Type": "application/json",
            "User-Agent": (
                "Gold9999-OfflineSync/1"
            ),
        }

        if self._installation_uuid:
            headers[
                "X-Gold9999-Installation-UUID"
            ] = self._installation_uuid

        request = Request(
            url=url,
            data=body,
            method=method,
            headers=headers,
        )

        for attempt in range(
            1,
            self._max_attempts + 1,
        ):
            try:
                with self._opener.open(
                    request,
                    timeout=self._timeout_seconds,
                ) as response:
                    status_code = int(
                        response.getcode()
                    )
                    raw_body = response.read()

                if not 200 <= status_code < 300:
                    raise HttpSyncResponseError(
                        "Sync server HTTP xatosi: "
                        f"{status_code}",
                        status_code=status_code,
                    )

                return self._decode_response(
                    raw_body,
                    status_code=status_code,
                )

            except HTTPError as exc:
                status_code = int(exc.code)

                try:
                    raw_error = exc.read()
                except Exception:
                    raw_error = b""

                message = self._error_message(
                    raw_error,
                    fallback=(
                        "Sync server HTTP xatosi: "
                        f"{status_code}"
                    ),
                )

                if (
                    status_code
                    in _RETRYABLE_STATUS_CODES
                    and attempt < self._max_attempts
                ):
                    self._retry_sleep(attempt)
                    continue

                raise HttpSyncResponseError(
                    message,
                    status_code=status_code,
                ) from exc

            except (
                URLError,
                TimeoutError,
                socket.timeout,
                OSError,
            ) as exc:
                if attempt < self._max_attempts:
                    self._retry_sleep(attempt)
                    continue

                raise HttpSyncTransportError(
                    "Sync server bilan aloqa "
                    "o‘rnatilmadi"
                ) from exc

        raise HttpSyncTransportError(
            "Sync HTTP urinishlari tugadi"
        )

    def _retry_sleep(
        self,
        attempt: int,
    ) -> None:
        delay = (
            self._retry_backoff_seconds
            * (2 ** (attempt - 1))
        )

        if delay > 0:
            self._sleep(delay)

    @staticmethod
    def _decode_response(
        raw_body: bytes,
        *,
        status_code: int,
    ) -> dict[str, Any]:
        if not raw_body:
            raise HttpSyncResponseError(
                "Sync server bo‘sh javob qaytardi",
                status_code=status_code,
            )

        try:
            decoded = json.loads(
                raw_body.decode("utf-8")
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise HttpSyncResponseError(
                "Sync server noto‘g‘ri JSON "
                "qaytardi",
                status_code=status_code,
            ) from exc

        if not isinstance(decoded, Mapping):
            raise HttpSyncResponseError(
                "Sync server JSON object "
                "qaytarishi kerak",
                status_code=status_code,
            )

        return dict(decoded)

    @staticmethod
    def _error_message(
        raw_body: bytes,
        *,
        fallback: str,
    ) -> str:
        if not raw_body:
            return fallback

        try:
            decoded = json.loads(
                raw_body.decode("utf-8")
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            return fallback

        if isinstance(decoded, Mapping):
            message = decoded.get("message")

            if isinstance(message, str):
                normalized = message.strip()

                if normalized:
                    return normalized

        return fallback

    @staticmethod
    def _record_to_wire(
        record: SyncRecord,
    ) -> dict[str, Any]:
        if not isinstance(record.payload, Mapping):
            raise TypeError(
                "SyncRecord payload Mapping "
                "bo‘lishi kerak"
            )

        return {
            "entity_type": _required_text(
                record.entity_type,
                field_name="entity_type",
            ),
            "entity_uuid": _required_text(
                record.entity_uuid,
                field_name="entity_uuid",
            ),
            "operation": _required_text(
                record.operation,
                field_name="operation",
            ),
            "payload": dict(record.payload),
            "device_uuid": _required_text(
                record.device_uuid,
                field_name="device_uuid",
            ),
            "occurred_at": _datetime_to_wire(
                record.occurred_at
            ),
        }

    @staticmethod
    def _sync_result_from_wire(
        raw_result: object,
    ) -> SyncResult:
        result = _mapping(
            raw_result,
            field_name="result",
        )

        success = result.get("success")

        if not isinstance(success, bool):
            raise HttpSyncResponseError(
                "result.success boolean bo‘lishi kerak"
            )

        remote_payload = result.get(
            "remote_payload"
        )

        if remote_payload is not None:
            remote_payload = _mapping(
                remote_payload,
                field_name="remote_payload",
            )

        return SyncResult(
            success=success,
            status=_required_text(
                result.get("status"),
                field_name="result.status",
            ),
            message=_required_text(
                result.get("message"),
                field_name="result.message",
            ),
            remote_version=_optional_integer(
                result.get("remote_version"),
                field_name="remote_version",
            ),
            remote_payload=remote_payload,
            remote_device_uuid=_optional_text(
                result.get(
                    "remote_device_uuid"
                ),
                field_name="remote_device_uuid",
            ),
            local_version=_optional_integer(
                result.get("local_version"),
                field_name="local_version",
            ),
        )

    @staticmethod
    def _remote_change_from_wire(
        raw_change: object,
    ) -> RemoteChange:
        change = _mapping(
            raw_change,
            field_name="change",
        )

        payload = _mapping(
            change.get("payload"),
            field_name="change.payload",
        )

        return RemoteChange(
            entity_type=_required_text(
                change.get("entity_type"),
                field_name="change.entity_type",
            ),
            entity_uuid=_required_text(
                change.get("entity_uuid"),
                field_name="change.entity_uuid",
            ),
            operation=_required_text(
                change.get("operation"),
                field_name="change.operation",
            ),
            payload=payload,
            version=_positive_integer(
                change.get("version"),
                field_name="change.version",
            ),
            device_uuid=_required_text(
                change.get("device_uuid"),
                field_name="change.device_uuid",
            ),
            occurred_at=_datetime_from_wire(
                change.get("occurred_at"),
                field_name="change.occurred_at",
            ),
        )


__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_RETRY_BACKOFF_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "HttpSyncApi",
    "HttpSyncApiError",
    "HttpSyncResponseError",
    "HttpSyncTransportError",
]
