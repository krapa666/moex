from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .consensus_canary import (
    ActiveConsensusResult,
    CanaryPolicyError,
    CanarySettingsResult,
    ConsensusCanaryEvent,
    build_active_consensus,
    configure_canary,
    get_canary_settings,
    list_canary_events,
    rollback_canary,
)
from .database import get_db

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


class CanarySettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    tickers: list[str]
    max_tickers: int
    safety_policy: str
    updated_by: str | None
    updated_at: datetime | None


class CanarySettingsUpdate(BaseModel):
    enabled: bool
    tickers: list[str] = Field(default_factory=list, max_length=5)
    note: str | None = Field(default=None, max_length=255)


class CanaryRollbackRequest(BaseModel):
    note: str | None = Field(default=None, max_length=255)


class CanaryEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    occurred_at: datetime
    action: str
    previous_enabled: bool
    new_enabled: bool
    previous_tickers: list[str]
    new_tickers: list[str]
    actor: str
    note: str | None
    promotion_status: str | None


class ActiveConsensusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    target_year: int | None
    active_available: bool
    reason: str | None
    canary_enabled: bool
    in_allowlist: bool
    configured_mode: str
    effective_mode: str
    safety_status: str | None
    fallback_reason: str | None
    sources: int
    current_price: float | None
    median_target_price: float | None
    weighted_target_price: float | None
    active_target_price: float | None
    median_expected_return_percent: float | None
    weighted_expected_return_percent: float | None
    active_expected_return_percent: float | None


def require_local_actor(request: Request) -> str:
    if (request.headers.get("x-moex-access-scope") or "").strip().lower() != "local":
        raise HTTPException(status_code=403, detail="Доступ только из локальной сети")
    return "local-network"


@router.get("/consensus-canary", response_model=CanarySettingsRead)
def get_consensus_canary(
    db: Session = Depends(get_db),
) -> CanarySettingsResult:
    return get_canary_settings(db)


@router.put("/consensus-canary", response_model=CanarySettingsRead)
def put_consensus_canary(
    payload: CanarySettingsUpdate,
    actor: str = Depends(require_local_actor),
    db: Session = Depends(get_db),
) -> CanarySettingsResult:
    try:
        return configure_canary(
            db,
            enabled=payload.enabled,
            tickers=payload.tickers,
            actor=actor,
            note=payload.note,
        )
    except CanaryPolicyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/consensus-canary/rollback", response_model=CanarySettingsRead)
def post_consensus_canary_rollback(
    payload: CanaryRollbackRequest,
    actor: str = Depends(require_local_actor),
    db: Session = Depends(get_db),
) -> CanarySettingsResult:
    return rollback_canary(db, actor=actor, note=payload.note)


@router.get("/consensus-canary/events", response_model=list[CanaryEventRead])
def get_consensus_canary_events(
    _actor: str = Depends(require_local_actor),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[ConsensusCanaryEvent]:
    return list_canary_events(db, limit=limit)


@router.get("/active-consensus", response_model=ActiveConsensusRead)
def get_active_consensus(
    ticker: str = Query(max_length=32, pattern=r"^[A-Za-z0-9._-]+$"),
    db: Session = Depends(get_db),
) -> ActiveConsensusResult:
    return build_active_consensus(db, ticker=ticker)
