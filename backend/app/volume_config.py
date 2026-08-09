from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float_env(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass(frozen=True)
class VolumeSettings:
    schedule_hour: int
    schedule_minute: int
    schedule_timezone: str
    run_on_startup: bool
    baseline_sessions: int
    display_sessions: int
    min_baseline_sessions: int
    signal_min_ratio: float
    signal_max_ratio: float
    moex_timeout_seconds: float
    moex_concurrency: int
    moex_history_rows: int
    smtp_enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_from: str
    smtp_starttls: bool
    smtp_ssl: bool
    public_base_url: str

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_enabled and self.smtp_host and self.smtp_from)

    @classmethod
    def from_env(cls) -> "VolumeSettings":
        settings = cls(
            schedule_hour=_int_env("VOLUME_SCHEDULE_HOUR", 18),
            schedule_minute=_int_env("VOLUME_SCHEDULE_MINUTE", 40),
            schedule_timezone=os.getenv("VOLUME_SCHEDULE_TIMEZONE", "Europe/Moscow"),
            run_on_startup=_bool_env("VOLUME_RUN_ON_STARTUP", True),
            baseline_sessions=_int_env("VOLUME_BASELINE_SESSIONS", 60),
            display_sessions=_int_env("VOLUME_DISPLAY_SESSIONS", 60),
            min_baseline_sessions=_int_env("VOLUME_MIN_BASELINE_SESSIONS", 60),
            signal_min_ratio=_float_env("VOLUME_SIGNAL_MIN_RATIO", 3.6),
            signal_max_ratio=_float_env("VOLUME_SIGNAL_MAX_RATIO", 6.5),
            moex_timeout_seconds=_float_env("VOLUME_MOEX_TIMEOUT_SECONDS", 20.0),
            moex_concurrency=_int_env("VOLUME_MOEX_CONCURRENCY", 8),
            moex_history_rows=_int_env("VOLUME_MOEX_HISTORY_ROWS", 140),
            smtp_enabled=_bool_env("VOLUME_SMTP_ENABLED", False),
            smtp_host=os.getenv("VOLUME_SMTP_HOST", ""),
            smtp_port=_int_env("VOLUME_SMTP_PORT", 587),
            smtp_username=os.getenv("VOLUME_SMTP_USERNAME", ""),
            smtp_password=os.getenv("VOLUME_SMTP_PASSWORD", ""),
            smtp_from=os.getenv("VOLUME_SMTP_FROM", ""),
            smtp_starttls=_bool_env("VOLUME_SMTP_STARTTLS", True),
            smtp_ssl=_bool_env("VOLUME_SMTP_SSL", False),
            public_base_url=os.getenv("VOLUME_PUBLIC_BASE_URL", ""),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not 0 <= self.schedule_hour <= 23 or not 0 <= self.schedule_minute <= 59:
            raise ValueError("VOLUME_SCHEDULE_HOUR/MINUTE contain an invalid time")
        if not 5 <= self.baseline_sessions <= 250:
            raise ValueError("VOLUME_BASELINE_SESSIONS must be between 5 and 250")
        if not 10 <= self.display_sessions <= 250:
            raise ValueError("VOLUME_DISPLAY_SESSIONS must be between 10 and 250")
        if not 5 <= self.min_baseline_sessions <= 250:
            raise ValueError("VOLUME_MIN_BASELINE_SESSIONS must be between 5 and 250")
        if self.min_baseline_sessions > self.baseline_sessions:
            raise ValueError("VOLUME_MIN_BASELINE_SESSIONS cannot exceed the baseline")
        if self.signal_min_ratio <= 1 or self.signal_max_ratio <= 1:
            raise ValueError("Volume signal ratios must be greater than 1")
        if self.signal_min_ratio >= self.signal_max_ratio:
            raise ValueError("VOLUME_SIGNAL_MIN_RATIO must be less than the maximum")
        if not 1 <= self.moex_concurrency <= 32:
            raise ValueError("VOLUME_MOEX_CONCURRENCY must be between 1 and 32")
        if not 0 < self.moex_timeout_seconds <= 120:
            raise ValueError("VOLUME_MOEX_TIMEOUT_SECONDS must be between 0 and 120")
        if self.moex_history_rows < self.baseline_sessions + self.display_sessions:
            raise ValueError("VOLUME_MOEX_HISTORY_ROWS must cover baseline and displayed sessions")
        if not 1 <= self.smtp_port <= 65535:
            raise ValueError("VOLUME_SMTP_PORT is invalid")
        if self.smtp_ssl and self.smtp_starttls:
            raise ValueError("VOLUME_SMTP_SSL and VOLUME_SMTP_STARTTLS cannot both be enabled")
        if self.smtp_enabled and not self.smtp_configured:
            raise ValueError("Enabled SMTP requires VOLUME_SMTP_HOST and VOLUME_SMTP_FROM")


@lru_cache
def get_volume_settings() -> VolumeSettings:
    return VolumeSettings.from_env()
