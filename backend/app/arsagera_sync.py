from __future__ import annotations

import os

from .arsagera_source import ArsageraClient
from .forecast_source_sync import (
    ForecastSyncResult,
    merge_future_values as _merge_future_values,
    sync_forecast_source_once,
)

DEFAULT_ANALYST_NAME = "Арсагера"
DEFAULT_CONCURRENCY = 4
SOURCE_COMMENT = "Арсагера — автоматическая синхронизация"
ArsageraSyncResult = ForecastSyncResult


async def sync_arsagera_once(
    *,
    analyst_name: str | None = None,
    concurrency: int | None = None,
    client: ArsageraClient | None = None,
) -> ArsageraSyncResult:
    target_name = (analyst_name or os.getenv("ARSAGERA_ANALYST_NAME") or DEFAULT_ANALYST_NAME).strip()
    effective_concurrency = concurrency or int(
        os.getenv("ARSAGERA_SYNC_CONCURRENCY", str(DEFAULT_CONCURRENCY))
    )
    return await sync_forecast_source_once(
        analyst_name=target_name,
        source_comment=SOURCE_COMMENT,
        changed_by="arsagera-sync",
        client=client or ArsageraClient(),
        concurrency=effective_concurrency,
        create_table_if_missing=False,
    )
