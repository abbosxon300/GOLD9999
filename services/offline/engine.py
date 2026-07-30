from __future__ import annotations

from dataclasses import dataclass

from services.offline.api import SyncApi
from services.offline.queue import SyncQueue


@dataclass(slots=True)
class SyncEngine:
    queue: SyncQueue
    api: SyncApi

    def push_pending(
        self,
        *,
        limit: int = 100,
    ) -> int:
        if limit <= 0:
            raise ValueError("limit musbat bo‘lishi kerak")

        records = self.queue.claim_pending(limit=limit)

        if not records:
            return 0

        results = self.api.push(records)

        if len(results) != len(records):
            raise RuntimeError(
                "Sync API natijalari soni yuborilgan "
                "yozuvlar soniga teng emas"
            )

        synced_count = 0

        for record, result in zip(
            records,
            results,
            strict=True,
        ):
            if result.success:
                self.queue.mark_synced(
                    record.entity_uuid
                )
                synced_count += 1
            else:
                self.queue.mark_failed(
                    record.entity_uuid,
                    result.message,
                )

        return synced_count
