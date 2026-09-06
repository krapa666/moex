import asyncio
import logging
import os
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .arsagera_sync import sync_arsagera_once
from .dohod_source import sync_dohod_once
from .forecast_sources import load_published_sheets_sources, sync_published_sheets_sources_once

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

    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopped.set)
    await stopped.wait()
    scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
