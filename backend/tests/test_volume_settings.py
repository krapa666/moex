import pytest
from app.volume_api import VolumeMonitorSettingsUpdate
from app.volume_config import VolumeSettings
from pydantic import ValidationError


def test_notification_scope_and_baseline_are_validated() -> None:
    payload = VolumeMonitorSettingsUpdate(notification_scope="all", baseline_sessions=60)

    assert payload.notification_scope == "all"
    assert payload.baseline_sessions == 60

    with pytest.raises(ValidationError):
        VolumeMonitorSettingsUpdate(notification_scope="unknown")
    with pytest.raises(ValidationError):
        VolumeMonitorSettingsUpdate(baseline_sessions=9)


def test_default_collection_schedule_has_three_close_time_runs(monkeypatch) -> None:
    monkeypatch.delenv("VOLUME_SCHEDULE_MINUTES", raising=False)

    settings = VolumeSettings.from_env()

    assert settings.schedule_hour == 18
    assert settings.schedule_minutes == (20, 35, 45)
    assert settings.schedule_label == "18:20, 18:35, 18:45"


def test_collection_schedule_rejects_duplicate_minutes(monkeypatch) -> None:
    monkeypatch.setenv("VOLUME_SCHEDULE_MINUTES", "20,20")

    with pytest.raises(ValueError, match="unique minutes"):
        VolumeSettings.from_env()
