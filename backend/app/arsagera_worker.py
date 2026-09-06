import asyncio
import logging
import os
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .arsagera_sync import sync_arsagera_once
from .dohod_source import sync_dohod_once
from .finvista_source import sync_finvista_once
from .forecast_sources import load_published_sheets_sources, sync_published_sheets_sources_once
from .moex_cci_actuals import get_moex_cci_settings, sync_moex_cci_actuals_once
from .shadow_history import (
    capture_shadow_consensus_once,
    get_shadow_history_settings,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


async def main() -> None:
    interval_hours = max(float(os.getenv("ARSAGERA_SYNC_INTERVAL_HOURS", "6")), 1.0)
    run_on_startup = _env_bool("ARSAGERA_RUN_ON_STARTUP", True)
    published_sources = load_published_sheets_sources()
    published_interval_hours = max(
        float(os.getenv("FORECAST_SHEETS_SYNC_INTERVAL_HOURS", "6")),
        1.0,
    )
    published_run_on_startup = _env_bool("FORECAST_SHEETS_RUN_ON_STARTUP", True)
    dohod_enabled = _env_bool("DOHOD_ENABLED", True)
    dohod_interval_hours = max(float(os.getenv("DOHOD_SYNC_INTERVAL_HOURS", "6")), 1.0)
    dohod_run_on_startup = _env_bool("DOHOD_RUN_ON_STARTUP", True)
    finvista_enabled = _env_bool("FINVISTA_ENABLED", False)
    finvista_interval_hours = max(float(os.getenv("FINVISTA_SYNC_INTERVAL_HOURS", "6")), 1.0)
    finvista_run_on_startup = _env_bool("FINVISTA_RUN_ON_STARTUP", True)
    cci_settings = get_moex_cci_settings()
    shadow_history_settings = get_shadow_history_settings()

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        sync_arsagera_once,
        IntervalTrigger(hours=interval_hours),
        id="arsagera-forecast-sync",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    logger.info("Arsagera worker scheduled every %.1f hours", interval_hours)

    if published_sources:
        scheduler.add_job(
            sync_published_sheets_sources_once,
            IntervalTrigger(hours=published_interval_hours),
            kwargs={"sources": published_sources},
            id="published-sheets-forecast-sync",
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
        logger.info(
            "Published Sheets forecast sync scheduled every %.1f hours for %d source(s)",
            published_interval_hours,
            len(published_sources),
        )

    if dohod_enabled:
        scheduler.add_job(
            sync_dohod_once,
            IntervalTrigger(hours=dohod_interval_hours),
            id="dohod-dividend-forecast-sync",
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
        logger.info("DOHOD dividend sync scheduled every %.1f hours", dohod_interval_hours)

    if finvista_enabled:
        scheduler.add_job(
            sync_finvista_once,
            IntervalTrigger(hours=finvista_interval_hours),
            id="finvista-forecast-sync",
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
        logger.info("fin-vista model sync scheduled every %.1f hours", finvista_interval_hours)

    if cci_settings.enabled:
        if cci_settings.configured:
            scheduler.add_job(
                sync_moex_cci_actuals_once,
                IntervalTrigger(hours=cci_settings.interval_hours),
                id="moex-cci-actual-result-sync",
                coalesce=True,
                max_instances=1,
                misfire_grace_time=3600,
            )
            logger.info(
                "MOEX CCI actual-result sync scheduled every %.1f hours",
                cci_settings.interval_hours,
            )
        else:
            logger.error("MOEX CCI actual-result sync enabled but credentials are not configured")

    if shadow_history_settings.enabled:
        scheduler.add_job(
            capture_shadow_consensus_once,
            IntervalTrigger(hours=shadow_history_settings.interval_hours),
            id="shadow-consensus-history-capture",
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
        logger.info(
            "Shadow consensus history scheduled every %.1f hours with %d-day retention",
            shadow_history_settings.interval_hours,
            shadow_history_settings.retention_days,
        )

    scheduler.start()

    if run_on_startup:
        try:
            await sync_arsagera_once()
        except Exception:
            logger.exception("Initial Arsagera synchronization failed")

    if published_sources and published_run_on_startup:
        try:
            await sync_published_sheets_sources_once(sources=published_sources)
        except Exception:
            logger.exception("Initial Published Sheets synchronization failed")

    if dohod_enabled and dohod_run_on_startup:
        try:
            await sync_dohod_once()
        except Exception:
            logger.exception("Initial DOHOD dividend synchronization failed")

    if finvista_enabled and finvista_run_on_startup:
        try:
            await sync_finvista_once()
        except Exception:
            logger.exception("Initial fin-vista model synchronization failed")

    if cci_settings.enabled and cci_settings.configured and cci_settings.run_on_startup:
        try:
            await sync_moex_cci_actuals_once()
        except Exception:
            logger.exception("Initial MOEX CCI actual-result synchronization failed")

    if shadow_history_settings.enabled and shadow_history_settings.run_on_startup:
        try:
            result = await asyncio.to_thread(capture_shadow_consensus_once)
            logger.info(
                "Initial shadow history capture created %d/%d snapshots; skipped=%d expired=%d",
                result.snapshots_created,
                result.tickers_total,
                result.skipped_unavailable,
                result.deleted_expired,
            )
        except Exception:
            logger.exception("Initial shadow consensus history capture failed")

    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopped.set)
    await stopped.wait()
    scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
