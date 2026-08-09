from prometheus_client import Counter, Gauge
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .models import (
    VolumeCollectionRun,
    VolumeMonitorSettings,
    VolumeSecurity,
)
from .volume_config import get_volume_settings

LAST_COLLECTION_TIMESTAMP = Gauge(
    "moex_volume_last_collection_timestamp_seconds",
    "Unix timestamp of the latest TQBR share volume collection start",
)
LAST_SUCCESS_TIMESTAMP = Gauge(
    "moex_volume_last_success_timestamp_seconds",
    "Unix timestamp of the latest successful TQBR share volume collection finish",
)
SECURITIES_TOTAL = Gauge(
    "moex_volume_securities_total",
    "Number of TQBR common/preferred shares expected in the latest volume collection",
)
SECURITIES_UPDATED = Gauge(
    "moex_volume_securities_updated",
    "Number of securities updated in the latest volume collection",
)
ACTIVE_SECURITIES = Gauge(
    "moex_volume_active_securities",
    "Number of active TQBR shares stored by the volume monitor",
)
IMOEX_SECURITIES = Gauge(
    "moex_volume_imoex_securities",
    "Number of active monitored shares that belong to IMOEX",
)
BASELINE_SESSIONS = Gauge(
    "moex_volume_baseline_sessions",
    "Configured number of completed sessions in the turnover baseline",
)
NOTIFICATION_SCOPE = Gauge(
    "moex_volume_notification_scope",
    "One-hot notification universe for volume alerts",
    ["scope"],
)
SIGNALS_FOUND = Gauge(
    "moex_volume_signals_found",
    "Number of turnover anomalies found in the latest volume collection",
)
IMOEX_ANOMALIES_FOUND = Gauge(
    "moex_volume_imoex_anomalies_found",
    "Number of IMOEX turnover anomalies found in the latest volume collection",
)
NOTIFICATIONS_SUPPRESSED = Gauge(
    "moex_volume_notifications_suppressed",
    "Number of high-ratio notifications suppressed by the broad-market rule",
)
NOTIFICATIONS_SENT = Gauge(
    "moex_volume_notifications_sent",
    "Number of security notifications included in the latest email digest",
)
COLLECTION_STATUS = Gauge(
    "moex_volume_collection_status",
    "One-hot status of the latest volume collection",
    ["status"],
)
SMTP_CONFIGURED = Gauge(
    "moex_volume_smtp_configured",
    "Whether SMTP transport is configured for volume alerts",
)
RECIPIENT_CONFIGURED = Gauge(
    "moex_volume_notification_recipient_configured",
    "Whether a notification recipient is configured (address is never exposed)",
)
TEST_EMAIL_ATTEMPTS = Counter(
    "moex_volume_test_email_attempts_total",
    "Number of test notification email attempts",
    ["result"],
)

KNOWN_STATUSES = ("running", "success", "partial", "failed")


def refresh_volume_metrics(db: Session) -> None:
    latest = db.scalar(
        select(VolumeCollectionRun).order_by(desc(VolumeCollectionRun.started_at)).limit(1)
    )
    latest_success = db.scalar(
        select(VolumeCollectionRun)
        .where(VolumeCollectionRun.status == "success")
        .order_by(desc(VolumeCollectionRun.finished_at))
        .limit(1)
    )
    stored_settings = db.get(VolumeMonitorSettings, 1)
    active_count = db.scalar(
        select(func.count(VolumeSecurity.id)).where(VolumeSecurity.active.is_(True))
    )
    imoex_count = db.scalar(
        select(func.count(VolumeSecurity.id)).where(
            VolumeSecurity.active.is_(True),
            VolumeSecurity.is_imoex.is_(True),
        )
    )

    for known_status in KNOWN_STATUSES:
        COLLECTION_STATUS.labels(status=known_status).set(
            1 if latest is not None and latest.status == known_status else 0
        )

    LAST_COLLECTION_TIMESTAMP.set(latest.started_at.timestamp() if latest else 0)
    LAST_SUCCESS_TIMESTAMP.set(
        latest_success.finished_at.timestamp()
        if latest_success is not None and latest_success.finished_at is not None
        else 0
    )
    SECURITIES_TOTAL.set(latest.securities_total if latest else 0)
    SECURITIES_UPDATED.set(latest.securities_updated if latest else 0)
    SIGNALS_FOUND.set(latest.signals_found if latest else 0)
    IMOEX_ANOMALIES_FOUND.set(latest.imoex_anomalies_found if latest else 0)
    NOTIFICATIONS_SUPPRESSED.set(latest.notifications_suppressed if latest else 0)
    NOTIFICATIONS_SENT.set(latest.notifications_sent if latest else 0)
    ACTIVE_SECURITIES.set(active_count or 0)
    IMOEX_SECURITIES.set(imoex_count or 0)
    baseline_sessions = (
        stored_settings.baseline_sessions
        if stored_settings is not None
        else get_volume_settings().baseline_sessions
    )
    BASELINE_SESSIONS.set(baseline_sessions)
    selected_scope = stored_settings.notification_scope if stored_settings else "imoex"
    for scope in ("imoex", "all"):
        NOTIFICATION_SCOPE.labels(scope=scope).set(1 if selected_scope == scope else 0)
    SMTP_CONFIGURED.set(1 if get_volume_settings().smtp_configured else 0)
    RECIPIENT_CONFIGURED.set(1 if get_volume_settings().notification_email else 0)
