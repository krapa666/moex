import pytest
from app.volume_api import VolumeMonitorSettingsUpdate
from pydantic import ValidationError


def test_notification_scope_and_baseline_are_validated() -> None:
    payload = VolumeMonitorSettingsUpdate(notification_scope="all", baseline_sessions=60)

    assert payload.notification_scope == "all"
    assert payload.baseline_sessions == 60

    with pytest.raises(ValidationError):
        VolumeMonitorSettingsUpdate(notification_scope="unknown")
    with pytest.raises(ValidationError):
        VolumeMonitorSettingsUpdate(baseline_sessions=9)
