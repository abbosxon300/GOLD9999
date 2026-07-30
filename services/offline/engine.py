from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from services.offline.api import SyncApi
from services.offline.conflict import (
    SyncConflictEntry,
    SyncConflictStore,
)
from services.offline.constants import (
    DIRECTION_PUSH,
    SYNC_STATUS_CONFLICT,
    SYNC_STATUS_FAILED,
    SYNC_STATUS_SYNCED,
)
from services.offline.log import (
    SyncLogEntry,
    SyncLogStore,
)
from services.offline.models import (
    SyncRecord,
    SyncResult,
)
from services.offline.queue import SyncQueue


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _result_payload(
    result: SyncResult,
) -> Mapping[str, Any]:
    payload: dict[str, Any] = {
        "success": result.success,
        "status": result.status,
        "message": result.message,
        "remote_version": result.remote_version,
        "remote_device_uuid": (
            result.remote_device_uuid
        ),
        "local_version": result.local_version,
    }

    if result.remote_payload is not None:
        payload["remote_payload"] = dict(
            result.remote_payload
        )

    return payload


@dataclass(slots=True)
class SyncEngine:
    queue: SyncQueue
    api: SyncApi
    log: SyncLogStore | None = None
    conflicts: SyncConflictStore | None = None

    def push_pending(
        self,
        *,
        limit: int = 100,
    ) -> int:
        if not isinstance(limit, int):
            raise TypeError(
                "limit integer bo‘lishi kerak"
            )

        if isinstance(limit, bool):
            raise TypeError(
                "limit integer bo‘lishi kerak"
            )

        if limit <= 0:
            raise ValueError(
                "limit musbat bo‘lishi kerak"
            )

        records = self.queue.claim_pending(
            limit=limit
        )

        if not records:
            return 0

        batch_started_at = _utc_now()

        try:
            results = self.api.push(records)
        except Exception as exc:
            self._mark_batch_failed(
                records,
                error_message=str(exc),
                started_at=batch_started_at,
            )
            raise

        if len(results) != len(records):
            error_message = (
                "Sync API natijalari soni yuborilgan "
                "yozuvlar soniga teng emas"
            )

            self._mark_batch_failed(
                records,
                error_message=error_message,
                started_at=batch_started_at,
            )

            raise RuntimeError(error_message)

        try:
            self._validate_batch_results(
                records,
                results,
            )
        except Exception as exc:
            self._mark_batch_failed(
                records,
                error_message=str(exc),
                started_at=batch_started_at,
            )
            raise

        synced_count = 0

        for record, result in zip(
            records,
            results,
            strict=True,
        ):
            started_at = _utc_now()

            if (
                result.success
                and result.status
                == SYNC_STATUS_SYNCED
            ):
                self.queue.mark_synced(
                    record.entity_uuid
                )
                synced_count += 1

            elif (
                result.status
                == SYNC_STATUS_CONFLICT
            ):
                self._record_conflict(
                    record,
                    result,
                )

                self.queue.mark_conflict(
                    record.entity_uuid,
                    result.message,
                )

            else:
                self.queue.mark_failed(
                    record.entity_uuid,
                    result.message,
                )

            self._record_log(
                record=record,
                result=result,
                started_at=started_at,
                finished_at=_utc_now(),
            )

        return synced_count

    def _record_conflict(
        self,
        record: SyncRecord,
        result: SyncResult,
    ) -> None:
        if self.conflicts is None:
            raise RuntimeError(
                "Conflict store preflightdan "
                "o‘tmagan"
            )

        if result.remote_payload is None:
            raise RuntimeError(
                "Conflict payload preflightdan "
                "o‘tmagan"
            )

        self.conflicts.record(
            SyncConflictEntry(
                entity_type=record.entity_type,
                entity_uuid=record.entity_uuid,
                local_payload=record.payload,
                remote_payload=(
                    result.remote_payload
                ),
                local_device_uuid=(
                    record.device_uuid
                ),
                detected_at=_utc_now(),
                remote_device_uuid=(
                    result.remote_device_uuid
                ),
                local_version=(
                    result.local_version
                ),
                remote_version=(
                    result.remote_version
                ),
            )
        )

    def _record_log(
        self,
        *,
        record: SyncRecord,
        result: SyncResult,
        started_at: datetime,
        finished_at: datetime,
    ) -> None:
        if self.log is None:
            return

        self.log.record(
            SyncLogEntry(
                direction=DIRECTION_PUSH,
                device_uuid=record.device_uuid,
                success=(
                    result.success
                    and result.status
                    == SYNC_STATUS_SYNCED
                ),
                started_at=started_at,
                finished_at=finished_at,
                entity_type=record.entity_type,
                entity_uuid=record.entity_uuid,
                message=result.message,
                request_payload=record.payload,
                response_payload=(
                    _result_payload(result)
                ),
            )
        )

    def _mark_batch_failed(
        self,
        records: tuple[SyncRecord, ...],
        *,
        error_message: str,
        started_at: datetime,
    ) -> None:
        message = (
            error_message.strip()
            or "Sync API xatosi"
        )

        for record in records:
            self.queue.mark_failed(
                record.entity_uuid,
                message,
            )

            if self.log is not None:
                self.log.record(
                    SyncLogEntry(
                        direction=DIRECTION_PUSH,
                        device_uuid=(
                            record.device_uuid
                        ),
                        success=False,
                        started_at=started_at,
                        finished_at=_utc_now(),
                        entity_type=(
                            record.entity_type
                        ),
                        entity_uuid=(
                            record.entity_uuid
                        ),
                        message=message,
                        request_payload=(
                            record.payload
                        ),
                    )
                )

    def _validate_batch_results(
        self,
        records: tuple[SyncRecord, ...],
        results: tuple[SyncResult, ...],
    ) -> None:
        for record, result in zip(
            records,
            results,
            strict=True,
        ):
            self._validate_result(result)

            if (
                result.status
                == SYNC_STATUS_CONFLICT
            ):
                if self.conflicts is None:
                    raise RuntimeError(
                        "Conflict natijasi uchun "
                        "SyncConflictStore kerak"
                    )

                if (
                    result.remote_payload
                    is None
                ):
                    raise ValueError(
                        "Conflict natijasida "
                        "remote_payload kerak: "
                        f"{record.entity_uuid}"
                    )

    @staticmethod
    def _validate_result(
        result: SyncResult,
    ) -> None:
        if not isinstance(
            result,
            SyncResult,
        ):
            raise TypeError(
                "API natijasi SyncResult "
                "bo‘lishi kerak"
            )

        if result.status not in {
            SYNC_STATUS_SYNCED,
            SYNC_STATUS_FAILED,
            SYNC_STATUS_CONFLICT,
        }:
            raise ValueError(
                "API noto‘g‘ri sync status "
                f"qaytardi: {result.status}"
            )

        if (
            result.success
            and result.status
            != SYNC_STATUS_SYNCED
        ):
            raise ValueError(
                "success=True faqat synced "
                "status bilan mumkin"
            )

        if (
            not result.success
            and result.status
            == SYNC_STATUS_SYNCED
        ):
            raise ValueError(
                "synced status uchun "
                "success=True bo‘lishi kerak"
            )

        if not isinstance(
            result.message,
            str,
        ):
            raise TypeError(
                "result.message matn "
                "bo‘lishi kerak"
            )

        if not result.message.strip():
            raise ValueError(
                "result.message bo‘sh "
                "bo‘lishi mumkin emas"
            )
