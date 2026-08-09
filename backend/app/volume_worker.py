import asyncio
import logging
import signal
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

from .volume_collector import collect_once
from .volume_config import get_volume_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_volume_settings()
    timezone = ZoneInfo(settings.schedule_timezone)
    scheduler = AsyncIOScheduler(timezone=timezone)
    scheduler.add_job(
        collect_once,
        CronTrigger(
            day_of_week="mon-fri",
            hour=settings.schedule_hour,
            minute=settings.schedule_minute,
            timezone=timezone,
        ),
        kwargs={"settings": settings, "allow_notifications": True},
        id="daily-moex-volume-collection",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=900,
    )
    scheduler.start()
    logger.info(
        "Volume worker scheduled at %02d:%02d %s",
        settings.schedule_hour,
        settings.schedule_minute,
        settings.schedule_timezone,
    )

    if settings.run_on_startup:
        local_now = datetime.now(timezone)
        scheduled_minutes = settings.schedule_hour * 60 + settings.schedule_minute
        current_minutes = local_now.hour * 60 + local_now.minute
        notification_window = (
            local_now.weekday() < 5 and 0 <= current_minutes - scheduled_minutes <= 15
        )
        await collect_once(settings, allow_notifications=notification_window)

    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopped.set)
    await stopped.wait()
    scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
