from prometheus_client import Gauge
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
    "Unix timestamp of the latest IMOEX volume collection start",
)
LAST_SUCCESS_TIMESTAMP = Gauge(
    "moex_volume_last_success_timestamp_seconds",
    "Unix timestamp of the latest successful IMOEX volume collection finish",
)
SECURITIES_TOTAL = Gauge(
    "moex_volume_securities_total",
    "Number of IMOEX securities expected in the latest volume collection",
)
SECURITIES_UPDATED = Gauge(
    "moex_volume_securities_updated",
    "Number of securities updated in the latest volume collection",
)
ACTIVE_SECURITIES = Gauge(
    "moex_volume_active_securities",
    "Number of active IMOEX securities stored by the volume monitor",
)
SIGNALS_FOUND = Gauge(
    "moex_volume_signals_found",
    "Number of signals found in the latest volume collection",
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
    ACTIVE_SECURITIES.set(active_count or 0)
    SMTP_CONFIGURED.set(1 if get_volume_settings().smtp_configured else 0)
    RECIPIENT_CONFIGURED.set(
        1 if stored_settings is not None and stored_settings.notification_email else 0
    )
