from dataclasses import replace
from datetime import datetime

from app.volume_config import VolumeSettings
from app.volume_worker import (
    _collection_trigger,
    _scheduled_collection_modes,
    _startup_notifications_allowed,
)
from zoneinfo import ZoneInfo


def test_startup_notifications_are_allowed_after_each_scheduled_run() -> None:
    settings = replace(
        VolumeSettings.from_env(),
        schedule_hour=18,
        schedule_minutes=(20, 35, 45),
    )
    timezone = ZoneInfo("Europe/Moscow")

    assert _startup_notifications_allowed(
        datetime(2026, 8, 10, 18, 20, tzinfo=timezone),
        settings,
    )
    assert _startup_notifications_allowed(
        datetime(2026, 8, 10, 18, 59, tzinfo=timezone),
        settings,
    )
    assert not _startup_notifications_allowed(
        datetime(2026, 8, 10, 19, 1, tzinfo=timezone),
        settings,
    )
    assert not _startup_notifications_allowed(
        datetime(2026, 8, 9, 18, 45, tzinfo=timezone),
        settings,
    )


def test_collection_trigger_runs_three_times_on_weekdays() -> None:
    settings = replace(
        VolumeSettings.from_env(),
        schedule_hour=18,
        schedule_minutes=(20, 35, 45),
    )
    timezone = ZoneInfo("Europe/Moscow")
    first = _collection_trigger(settings, timezone, 20)
    second = _collection_trigger(settings, timezone, 35)
    third = _collection_trigger(settings, timezone, 45)

    assert first.get_next_fire_time(
        None,
        datetime(2026, 8, 10, 18, 19, tzinfo=timezone),
    ) == datetime(2026, 8, 10, 18, 20, tzinfo=timezone)
    assert second.get_next_fire_time(
        None,
        datetime(2026, 8, 10, 18, 21, tzinfo=timezone),
    ) == datetime(2026, 8, 10, 18, 35, tzinfo=timezone)
    assert third.get_next_fire_time(
        None,
        datetime(2026, 8, 10, 18, 36, tzinfo=timezone),
    ) == datetime(2026, 8, 10, 18, 45, tzinfo=timezone)

    assert _scheduled_collection_modes(settings) == [
        (20, True),
        (35, False),
        (45, False),
    ]
