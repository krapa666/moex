from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .database import get_db
from .models import (
    VolumeCollectionRun,
    VolumeMonitorSettings,
    VolumeObservation,
    VolumeSecurity,
)
from .volume_collector import collect_once
from .volume_config import get_volume_settings
from .volume_mailer import send_test_email
from .volume_metrics import TEST_EMAIL_ATTEMPTS

router = APIRouter(prefix="/api/volume", tags=["volume-monitor"])
manual_collection_task: asyncio.Task | None = None
logger = logging.getLogger(__name__)


class VolumeMonitorSettingsUpdate(BaseModel):
    notification_scope: Literal["imoex", "all"] | None = None
    baseline_sessions: int | None = Field(default=None, ge=10, le=250)


class VolumeSettingsRead(BaseModel):
    notification_scope: Literal["imoex", "all"]
    baseline_sessions: int
    smtp_configured: bool
    notifications_enabled: bool
    schedule: str


def require_local_access(request: Request) -> None:
    if (request.headers.get("x-moex-access-scope") or "").strip().lower() != "local":
        raise HTTPException(status_code=403, detail="Доступ только из локальной сети")


def _serialize_observation(observation: VolumeObservation | None) -> dict | None:
    if observation is None:
        return None
    return {
        "trade_date": observation.trade_date,
        "turnover_rub": observation.turnover_rub,
        "volume_units": observation.volume_units,
        "close_price": observation.close_price,
        "baseline_average_rub": observation.baseline_average_rub,
        "baseline_count": observation.baseline_count,
        "ratio": observation.ratio,
        "signal_status": observation.signal_status,
        "is_final": observation.is_final,
        "source": observation.source,
        "observed_at": observation.observed_at,
    }


def _serialize_run(run: VolumeCollectionRun | None) -> dict | None:
    if run is None:
        return None
    return {
        "id": run.id,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "status": run.status,
        "securities_total": run.securities_total,
        "securities_updated": run.securities_updated,
        "signals_found": run.signals_found,
        "imoex_anomalies_found": run.imoex_anomalies_found,
        "notifications_suppressed": run.notifications_suppressed,
        "notifications_sent": run.notifications_sent,
        "error_message": run.error_message,
    }


@router.get("/config")
def get_public_config(db: Session = Depends(get_db)) -> dict[str, object]:
    settings = get_volume_settings()
    stored = db.get(VolumeMonitorSettings, 1)
    baseline_sessions = stored.baseline_sessions if stored else settings.baseline_sessions
    return {
        "baseline_sessions": baseline_sessions,
        "display_sessions": settings.display_sessions,
        "signal_min_ratio": settings.signal_min_ratio,
        "signal_max_ratio": settings.signal_max_ratio,
        "broad_market_signal_threshold": settings.broad_market_signal_threshold,
        "schedule_hour": settings.schedule_hour,
        "schedule_minutes": settings.schedule_minutes,
        "schedule_timezone": settings.schedule_timezone,
        "smtp_configured": settings.smtp_configured,
    }


@router.get("/overview")
def get_overview(db: Session = Depends(get_db)) -> list[dict]:
    latest_observation_id = (
        select(VolumeObservation.id)
        .where(VolumeObservation.security_id == VolumeSecurity.id)
        .order_by(desc(VolumeObservation.trade_date))
        .limit(1)
        .correlate(VolumeSecurity)
        .scalar_subquery()
    )
    rows = db.execute(
        select(VolumeSecurity, VolumeObservation)
        .outerjoin(VolumeObservation, VolumeObservation.id == latest_observation_id)
        .where(VolumeSecurity.active.is_(True))
        .order_by(VolumeSecurity.ticker.asc())
    ).all()
    result = []
    for security, latest in rows:
        result.append(
            {
                "ticker": security.ticker,
                "short_name": security.short_name,
                "security_type": security.security_type,
                "is_imoex": security.is_imoex,
                "weight": security.weight,
                "latest": _serialize_observation(latest),
            }
        )
    return result


@router.get("/securities/{ticker}/observations")
def get_observations(
    ticker: str,
    limit: int = Query(default=60, ge=1, le=250),
    db: Session = Depends(get_db),
) -> dict:
    security = db.scalar(
        select(VolumeSecurity).where(VolumeSecurity.ticker == ticker.strip().upper())
    )
    if security is None:
        raise HTTPException(status_code=404, detail="Тикер не найден")
    observations = db.scalars(
        select(VolumeObservation)
        .where(VolumeObservation.security_id == security.id)
        .order_by(desc(VolumeObservation.trade_date))
        .limit(limit)
    ).all()
    return {
        "ticker": security.ticker,
        "short_name": security.short_name,
        "security_type": security.security_type,
        "is_imoex": security.is_imoex,
        "weight": security.weight,
        "observations": [_serialize_observation(item) for item in observations],
    }


@router.get("/runs/latest")
def get_latest_run(db: Session = Depends(get_db)) -> dict | None:
    run = db.scalar(
        select(VolumeCollectionRun).order_by(desc(VolumeCollectionRun.started_at)).limit(1)
    )
    return _serialize_run(run)


def _settings_response(stored: VolumeMonitorSettings | None) -> VolumeSettingsRead:
    settings = get_volume_settings()
    notification_scope = (
        stored.notification_scope
        if stored and stored.notification_scope in {"imoex", "all"}
        else "imoex"
    )
    baseline_sessions = (
        stored.baseline_sessions
        if stored and 10 <= stored.baseline_sessions <= 250
        else settings.baseline_sessions
    )
    return VolumeSettingsRead(
        notification_scope=notification_scope,
        baseline_sessions=baseline_sessions,
        smtp_configured=settings.smtp_configured,
        notifications_enabled=bool(settings.smtp_configured and settings.notification_email),
        schedule=f"{settings.schedule_label} {settings.schedule_timezone}",
    )


@router.get("/settings", response_model=VolumeSettingsRead)
def get_notification_settings(
    _access: None = Depends(require_local_access),
    db: Session = Depends(get_db),
) -> VolumeSettingsRead:
    return _settings_response(db.get(VolumeMonitorSettings, 1))


@router.put("/settings", response_model=VolumeSettingsRead)
def update_notification_settings(
    payload: VolumeMonitorSettingsUpdate,
    _access: None = Depends(require_local_access),
    db: Session = Depends(get_db),
) -> VolumeSettingsRead:
    stored = db.get(VolumeMonitorSettings, 1)
    if stored is None:
        stored = VolumeMonitorSettings(id=1)
        db.add(stored)
    if payload.notification_scope is not None:
        stored.notification_scope = payload.notification_scope
    if payload.baseline_sessions is not None:
        stored.baseline_sessions = payload.baseline_sessions
    db.commit()
    db.refresh(stored)
    return _settings_response(stored)


@router.post("/notifications/test")
async def send_test_notification(
    _access: None = Depends(require_local_access),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    stored = db.get(VolumeMonitorSettings, 1)
    settings = get_volume_settings()
    recipient = settings.notification_email
    if not recipient:
        raise HTTPException(status_code=400, detail="Задайте VOLUME_NOTIFICATION_EMAIL в .env")
    if not settings.smtp_configured:
        raise HTTPException(status_code=400, detail="SMTP не настроен в .env")
    notification_scope = (
        stored.notification_scope
        if stored and stored.notification_scope in {"imoex", "all"}
        else "imoex"
    )
    try:
        await asyncio.to_thread(send_test_email, settings, recipient, notification_scope)
    except Exception as exc:
        TEST_EMAIL_ATTEMPTS.labels(result="failed").inc()
        logger.exception("Test volume notification email failed")
        raise HTTPException(
            status_code=502,
            detail="Письмо не отправлено. Проверьте SMTP-реквизиты и логи backend.",
        ) from exc
    TEST_EMAIL_ATTEMPTS.labels(result="success").inc()
    return {"status": "sent", "detail": "Тестовое письмо отправлено"}


async def _run_manual_collection() -> None:
    global manual_collection_task
    try:
        await collect_once(get_volume_settings(), allow_notifications=True)
    finally:
        manual_collection_task = None


@router.post("/collect", status_code=status.HTTP_202_ACCEPTED)
async def start_manual_collection(
    _access: None = Depends(require_local_access),
) -> dict[str, str]:
    global manual_collection_task
    if manual_collection_task is not None and not manual_collection_task.done():
        raise HTTPException(status_code=409, detail="Сбор уже выполняется")
    manual_collection_task = asyncio.create_task(_run_manual_collection())
    return {"status": "accepted", "detail": "Сбор данных запущен"}
