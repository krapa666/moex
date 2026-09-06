from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from .forecast_accuracy import ActualNetProfit

MAX_BACKFILL_BYTES = 2_000_000
MAX_BACKFILL_ROWS = 5_000
_REQUIRED_COLUMNS = {
    "ticker",
    "fiscal_year",
    "net_profit_billion_rub",
    "source_name",
    "source_url",
    "reported_at",
}
_OPTIONAL_COLUMNS = {"source_comment"}
_TICKER_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class ActualBackfillCandidate:
    row_number: int
    ticker: str
    fiscal_year: int
    net_profit_billion_rub: float
    source_name: str
    source_url: str
    source_comment: str | None
    reported_at: datetime


@dataclass(frozen=True)
class ActualBackfillIssue:
    row_number: int
    ticker: str | None
    fiscal_year: int | None
    message: str


def _parse_reported_at(value: str) -> datetime:
    text = value.strip()
    if not text:
        raise ValueError("reported_at is required")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _validate_source_url(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("source_url is required")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("source_url must be an absolute http(s) URL")
    if len(text) > 1024:
        raise ValueError("source_url is longer than 1024 characters")
    return text


def _detect_dialect(text: str) -> csv.Dialect:
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        return csv.excel


def parse_actual_result_csv(
    content: bytes,
    *,
    now: datetime | None = None,
) -> tuple[list[ActualBackfillCandidate], list[ActualBackfillIssue]]:
    if not content:
        return [], [ActualBackfillIssue(1, None, None, "CSV file is empty")]
    if len(content) > MAX_BACKFILL_BYTES:
        return [], [
            ActualBackfillIssue(
                1,
                None,
                None,
                f"CSV file exceeds {MAX_BACKFILL_BYTES} bytes",
            )
        ]

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], [ActualBackfillIssue(1, None, None, "CSV must be UTF-8 encoded")]

    reader = csv.DictReader(io.StringIO(text), dialect=_detect_dialect(text))
    if not reader.fieldnames:
        return [], [ActualBackfillIssue(1, None, None, "CSV header is missing")]

    normalized_fields = [str(name or "").strip().lower() for name in reader.fieldnames]
    missing = sorted(_REQUIRED_COLUMNS - set(normalized_fields))
    unknown = sorted(set(normalized_fields) - _REQUIRED_COLUMNS - _OPTIONAL_COLUMNS)
    if missing:
        return [], [
            ActualBackfillIssue(
                1,
                None,
                None,
                f"CSV is missing required columns: {', '.join(missing)}",
            )
        ]
    if unknown:
        return [], [
            ActualBackfillIssue(
                1,
                None,
                None,
                f"CSV has unsupported columns: {', '.join(unknown)}",
            )
        ]

    field_map = {original: normalized for original, normalized in zip(reader.fieldnames, normalized_fields)}
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    completed_year = current_time.year - 1
    candidates: list[ActualBackfillCandidate] = []
    issues: list[ActualBackfillIssue] = []
    seen: set[tuple[str, int]] = set()

    for index, raw_row in enumerate(reader, start=2):
        if index - 1 > MAX_BACKFILL_ROWS:
            issues.append(
                ActualBackfillIssue(
                    index,
                    None,
                    None,
                    f"CSV exceeds {MAX_BACKFILL_ROWS} data rows",
                )
            )
            break

        row = {
            field_map[key]: (value or "").strip()
            for key, value in raw_row.items()
            if key in field_map
        }
        if not any(row.values()):
            continue

        ticker = row.get("ticker", "").upper()
        fiscal_year: int | None = None
        try:
            if not ticker or not _TICKER_RE.fullmatch(ticker):
                raise ValueError("ticker has unsupported characters")

            fiscal_year = int(row.get("fiscal_year", ""))
            if fiscal_year < 2000 or fiscal_year > completed_year:
                raise ValueError(
                    f"fiscal_year must be between 2000 and {completed_year} (completed years only)"
                )

            value_text = row.get("net_profit_billion_rub", "").replace(",", ".")
            net_profit = float(value_text)
            if not math.isfinite(net_profit):
                raise ValueError("net_profit_billion_rub must be finite")

            source_name = row.get("source_name", "")
            if not source_name:
                raise ValueError("source_name is required")
            if len(source_name) > 255:
                raise ValueError("source_name is longer than 255 characters")

            source_url = _validate_source_url(row.get("source_url", ""))
            source_comment = row.get("source_comment", "") or None
            if source_comment is not None and len(source_comment) > 512:
                raise ValueError("source_comment is longer than 512 characters")

            reported_at = _parse_reported_at(row.get("reported_at", ""))
            if reported_at > current_time:
                raise ValueError("reported_at must not be in the future")

            key = (ticker, fiscal_year)
            if key in seen:
                raise ValueError("duplicate ticker + fiscal_year in the same CSV")
            seen.add(key)

            candidates.append(
                ActualBackfillCandidate(
                    row_number=index,
                    ticker=ticker,
                    fiscal_year=fiscal_year,
                    net_profit_billion_rub=net_profit,
                    source_name=source_name,
                    source_url=source_url,
                    source_comment=source_comment,
                    reported_at=reported_at,
                )
            )
        except (TypeError, ValueError) as exc:
            issues.append(
                ActualBackfillIssue(
                    row_number=index,
                    ticker=ticker or None,
                    fiscal_year=fiscal_year,
                    message=str(exc) or exc.__class__.__name__,
                )
            )

    return candidates, issues


def _same_datetime(left: datetime | None, right: datetime) -> bool:
    if left is None:
        return False
    if left.tzinfo is None:
        left = left.replace(tzinfo=timezone.utc)
    return left.astimezone(timezone.utc) == right.astimezone(timezone.utc)


def _candidate_matches(candidate: ActualBackfillCandidate, row: ActualNetProfit) -> bool:
    return (
        abs(float(row.net_profit_billion_rub) - candidate.net_profit_billion_rub) <= 1e-9
        and (row.source_name or "").strip() == candidate.source_name
        and (row.source_url or "").strip() == candidate.source_url
        and (row.source_comment or "").strip() == (candidate.source_comment or "").strip()
        and _same_datetime(row.reported_at, candidate.reported_at)
    )


def evaluate_actual_result_backfill(
    db: Session,
    candidates: list[ActualBackfillCandidate],
    issues: list[ActualBackfillIssue],
    *,
    apply: bool = False,
) -> dict[str, object]:
    keys = {(candidate.ticker, candidate.fiscal_year) for candidate in candidates}
    existing_rows = list(db.scalars(select(ActualNetProfit)).all()) if keys else []
    existing = {
        (row.ticker.strip().upper(), int(row.fiscal_year)): row
        for row in existing_rows
        if (row.ticker.strip().upper(), int(row.fiscal_year)) in keys
    }

    items: list[dict[str, object]] = [
        {
            "row_number": issue.row_number,
            "ticker": issue.ticker,
            "fiscal_year": issue.fiscal_year,
            "action": "invalid",
            "message": issue.message,
        }
        for issue in issues
    ]

    create_candidates: list[ActualBackfillCandidate] = []
    unchanged = protected = 0
    for candidate in candidates:
        key = (candidate.ticker, candidate.fiscal_year)
        row = existing.get(key)
        if row is None:
            create_candidates.append(candidate)
            items.append(
                {
                    "row_number": candidate.row_number,
                    "ticker": candidate.ticker,
                    "fiscal_year": candidate.fiscal_year,
                    "action": "create",
                    "message": "new canonical actual result",
                }
            )
            continue
        if _candidate_matches(candidate, row):
            unchanged += 1
            items.append(
                {
                    "row_number": candidate.row_number,
                    "ticker": candidate.ticker,
                    "fiscal_year": candidate.fiscal_year,
                    "action": "unchanged",
                    "message": "same canonical actual result already exists",
                }
            )
            continue

        protected += 1
        items.append(
            {
                "row_number": candidate.row_number,
                "ticker": candidate.ticker,
                "fiscal_year": candidate.fiscal_year,
                "action": "protected",
                "message": (
                    f"existing {row.source_key or 'manual'} result is protected; "
                    "bulk import never overwrites canonical facts"
                ),
            }
        )

    created = 0
    applied = False
    if apply and not issues:
        for candidate in create_candidates:
            db.add(
                ActualNetProfit(
                    ticker=candidate.ticker,
                    fiscal_year=candidate.fiscal_year,
                    source_key="manual",
                    net_profit_billion_rub=candidate.net_profit_billion_rub,
                    source_name=candidate.source_name,
                    source_url=candidate.source_url,
                    source_comment=candidate.source_comment,
                    reported_at=candidate.reported_at,
                )
            )
        db.commit()
        created = len(create_candidates)
        applied = True

    items.sort(key=lambda item: int(item["row_number"]))
    return {
        "applied": applied,
        "rows_total": len(candidates) + len(issues),
        "valid_rows": len(candidates),
        "create_rows": len(create_candidates),
        "unchanged_rows": unchanged,
        "protected_rows": protected,
        "invalid_rows": len(issues),
        "created_rows": created,
        "items": items,
    }
