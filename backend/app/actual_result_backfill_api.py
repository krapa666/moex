from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .actual_result_backfill import (
    MAX_BACKFILL_BYTES,
    evaluate_actual_result_backfill,
    parse_actual_result_csv,
)
from .database import get_db
from .forecast_api import require_local_access

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


class ActualBackfillItemRead(BaseModel):
    row_number: int
    ticker: str | None
    fiscal_year: int | None
    action: str
    message: str


class ActualBackfillResultRead(BaseModel):
    applied: bool
    rows_total: int
    valid_rows: int
    create_rows: int
    unchanged_rows: int
    protected_rows: int
    invalid_rows: int
    created_rows: int
    items: list[ActualBackfillItemRead]


async def _read_csv(file: UploadFile) -> bytes:
    filename = (file.filename or "").strip()
    if filename and not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=422, detail="Backfill file must have .csv extension")
    content = await file.read(MAX_BACKFILL_BYTES + 1)
    if len(content) > MAX_BACKFILL_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Backfill CSV exceeds {MAX_BACKFILL_BYTES} bytes",
        )
    return content


@router.post(
    "/actual-net-profits/backfill/preview",
    response_model=ActualBackfillResultRead,
)
async def preview_actual_result_backfill(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_local_access(request)
    candidates, issues = parse_actual_result_csv(await _read_csv(file))
    return evaluate_actual_result_backfill(db, candidates, issues, apply=False)


@router.post(
    "/actual-net-profits/backfill",
    response_model=ActualBackfillResultRead,
)
async def apply_actual_result_backfill(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_local_access(request)
    candidates, issues = parse_actual_result_csv(await _read_csv(file))
    if issues:
        result = evaluate_actual_result_backfill(db, candidates, issues, apply=False)
        result["applied"] = False
        return result
    return evaluate_actual_result_backfill(db, candidates, issues, apply=True)
