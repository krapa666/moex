import asyncio
import logging
import os
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .arsagera_sync import sync_arsagera_once

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
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        sync_arsagera_once,
        IntervalTrigger(hours=interval_hours),
        id="arsagera-forecast-sync",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info("Arsagera worker scheduled every %.1f hours", interval_hours)

    if run_on_startup:
        try:
            await sync_arsagera_once()
        except Exception:
            logger.exception("Initial Arsagera synchronization failed")

    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopped.set)
    await stopped.wait()
    scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
