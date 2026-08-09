from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
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

router = APIRouter(prefix="/api/volume", tags=["volume-monitor"])
manual_collection_task: asyncio.Task | None = None
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class NotificationEmailUpdate(BaseModel):
    notification_email: str | None = Field(default=None, max_length=320)

    @field_validator("notification_email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        normalized = (value or "").strip()
        if not normalized:
            return None
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("Введите корректный email")
        return normalized


class VolumeSettingsRead(BaseModel):
    notification_email: str | None
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
        "error_message": run.error_message,
    }


@router.get("/config")
def get_public_config() -> dict[str, int | float | str | bool]:
    settings = get_volume_settings()
    return {
        "baseline_sessions": settings.baseline_sessions,
        "display_sessions": settings.display_sessions,
        "signal_min_ratio": settings.signal_min_ratio,
        "signal_max_ratio": settings.signal_max_ratio,
        "schedule_hour": settings.schedule_hour,
        "schedule_minute": settings.schedule_minute,
        "schedule_timezone": settings.schedule_timezone,
        "smtp_configured": settings.smtp_configured,
    }


@router.get("/overview")
def get_overview(db: Session = Depends(get_db)) -> list[dict]:
    securities = db.scalars(
        select(VolumeSecurity)
        .where(VolumeSecurity.active.is_(True))
        .order_by(VolumeSecurity.ticker.asc())
    ).all()
    result = []
    for security in securities:
        latest = db.scalar(
            select(VolumeObservation)
            .where(VolumeObservation.security_id == security.id)
            .order_by(desc(VolumeObservation.trade_date))
            .limit(1)
        )
        result.append(
            {
                "ticker": security.ticker,
                "short_name": security.short_name,
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
    recipient = stored.notification_email if stored else None
    return VolumeSettingsRead(
        notification_email=recipient,
        smtp_configured=settings.smtp_configured,
        notifications_enabled=bool(settings.smtp_configured and recipient),
        schedule=(
            f"{settings.schedule_hour:02d}:{settings.schedule_minute:02d} "
            f"{settings.schedule_timezone}"
        ),
    )


@router.get("/settings", response_model=VolumeSettingsRead)
def get_notification_settings(
    _access: None = Depends(require_local_access),
    db: Session = Depends(get_db),
) -> VolumeSettingsRead:
    return _settings_response(db.get(VolumeMonitorSettings, 1))


@router.put("/settings", response_model=VolumeSettingsRead)
def update_notification_settings(
    payload: NotificationEmailUpdate,
    _access: None = Depends(require_local_access),
    db: Session = Depends(get_db),
) -> VolumeSettingsRead:
    stored = db.get(VolumeMonitorSettings, 1)
    if stored is None:
        stored = VolumeMonitorSettings(id=1)
        db.add(stored)
    stored.notification_email = payload.notification_email
    db.commit()
    db.refresh(stored)
    return _settings_response(stored)


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
