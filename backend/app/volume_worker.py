import asyncio
import logging
import signal
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

from .volume_collector import collect_once
from .volume_config import VolumeSettings, get_volume_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _startup_notifications_allowed(local_now: datetime, settings: VolumeSettings) -> bool:
    current_minutes = local_now.hour * 60 + local_now.minute
    return local_now.weekday() < 5 and any(
        0
        <= current_minutes - (settings.schedule_hour * 60 + scheduled_minute)
        <= 15
        for scheduled_minute in settings.schedule_minutes
    )


def _collection_trigger(settings: VolumeSettings, timezone: ZoneInfo) -> CronTrigger:
    return CronTrigger(
        day_of_week="mon-fri",
        hour=settings.schedule_hour,
        minute=",".join(str(minute) for minute in settings.schedule_minutes),
        timezone=timezone,
    )


async def main() -> None:
    settings = get_volume_settings()
    timezone = ZoneInfo(settings.schedule_timezone)
    scheduler = AsyncIOScheduler(timezone=timezone)
    scheduler.add_job(
        collect_once,
        _collection_trigger(settings, timezone),
        kwargs={"settings": settings, "allow_notifications": True},
        id="daily-moex-volume-collection",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=900,
    )
    scheduler.start()
    logger.info(
        "Volume worker scheduled at %s %s on weekdays",
        settings.schedule_label,
        settings.schedule_timezone,
    )

    if settings.run_on_startup:
        local_now = datetime.now(timezone)
        notification_window = _startup_notifications_allowed(local_now, settings)
        await collect_once(settings, allow_notifications=notification_window)

    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopped.set)
    await stopped.wait()
    scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
