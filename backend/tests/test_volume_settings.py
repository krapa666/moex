import pytest
from app.volume_api import NotificationEmailUpdate
from pydantic import ValidationError


def test_notification_email_is_normalized() -> None:
    payload = NotificationEmailUpdate(notification_email="  User@Example.com ")

    assert payload.notification_email == "User@Example.com"


def test_empty_notification_email_disables_notifications() -> None:
    payload = NotificationEmailUpdate(notification_email="  ")

    assert payload.notification_email is None


def test_invalid_notification_email_is_rejected() -> None:
    with pytest.raises(ValidationError):
        NotificationEmailUpdate(notification_email="not-an-email")
