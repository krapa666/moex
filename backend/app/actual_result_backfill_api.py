from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .actual_result_backfill import (
    MAX_BACKFILL_BYTES,
    evaluate_actual_result_backfill,
    parse_actual_result_csv,
)
from .actual_result_worklist import (
    build_actual_result_worklist,
    render_actual_result_worklist_csv,
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


class ActualWorklistMissingRead(BaseModel):
    ticker: str
    fiscal_year: int


class ActualWorklistYearRead(BaseModel):
    fiscal_year: int
    expected_pairs: int
    existing_pairs: int
    missing_pairs: int
    coverage_percent: float


class ActualWorklistRead(BaseModel):
    primary_table_id: int | None
    start_year: int
    end_year: int
    years: int
    primary_tickers: int
    expected_pairs: int
    existing_pairs: int
    missing_pairs: int
    coverage_percent: float
    by_year: list[ActualWorklistYearRead]
    missing: list[ActualWorklistMissingRead]


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


def _completed_end_year(end_year: int | None) -> int:
    completed_year = datetime.now(timezone.utc).year - 1
    resolved = completed_year if end_year is None else int(end_year)
    if resolved > completed_year:
        raise HTTPException(
            status_code=422,
            detail="Actual-result worklist is limited to completed fiscal years",
        )
    if resolved < 2000:
        raise HTTPException(status_code=422, detail="end_year must be 2000 or later")
    return resolved


@router.get(
    "/actual-net-profits/backfill/worklist",
    response_model=ActualWorklistRead,
)
def get_actual_result_worklist(
    request: Request,
    years: int = Query(5, ge=1, le=20),
    end_year: int | None = Query(None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    require_local_access(request)
    return build_actual_result_worklist(
        db,
        years=years,
        end_year=_completed_end_year(end_year),
    )


@router.get("/actual-net-profits/backfill/worklist.csv")
def download_actual_result_worklist(
    request: Request,
    years: int = Query(5, ge=1, le=20),
    end_year: int | None = Query(None),
    db: Session = Depends(get_db),
) -> Response:
    require_local_access(request)
    worklist = build_actual_result_worklist(
        db,
        years=years,
        end_year=_completed_end_year(end_year),
    )
    filename = f"actual-results-worklist-{worklist['start_year']}-{worklist['end_year']}.csv"
    return Response(
        content=render_actual_result_worklist_csv(worklist),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
