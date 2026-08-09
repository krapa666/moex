from dataclasses import replace

from app.volume_config import VolumeSettings
from app.volume_mailer import send_test_email


class FakeSmtp:
    instance = None

    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.logged_in = None
        self.message = None
        FakeSmtp.instance = self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.logged_in = (username, password)

    def send_message(self, message):
        self.message = message


def test_test_email_uses_configured_smtp_without_creating_a_signal(monkeypatch) -> None:
    settings = replace(
        VolumeSettings.from_env(),
        smtp_enabled=True,
        smtp_host="smtp.example.com",
        smtp_username="smtp-user",
        smtp_password="smtp-secret",
        smtp_from="alerts@example.com",
    )
    monkeypatch.setattr("app.volume_mailer.smtplib.SMTP", FakeSmtp)

    send_test_email(settings, "recipient@example.com", "all")

    smtp = FakeSmtp.instance
    assert smtp.host == "smtp.example.com"
    assert smtp.started_tls
    assert smtp.logged_in == ("smtp-user", "smtp-secret")
    assert smtp.message["To"] == "recipient@example.com"
    assert smtp.message["Subject"] == "MOEX: проверка почтовых уведомлений"
    assert "все акции TQBR" in smtp.message.get_body(preferencelist=("plain",)).get_content()
