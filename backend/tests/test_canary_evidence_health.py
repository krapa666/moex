from datetime import datetime, timedelta, timezone

import pytest
from app.canary_evidence import CanaryEvidenceSnapshot
from app.canary_evidence_health import (
    _build_ticker_health_from_rows,
    build_canary_evidence_health,
)
from app.consensus_canary import ConsensusCanarySettings
from app.database import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def _snapshot(
    *,
    row_id: int,
    ticker: str,
    captured_at: datetime,
    target_year: int = 2027,
) -> CanaryEvidenceSnapshot:
    return CanaryEvidenceSnapshot(
        id=row_id,
        ticker=ticker,
        target_year=target_year,
        captured_at=captured_at,
        canary_enabled=True,
        in_allowlist=True,
        configured_mode="weighted_canary",
        effective_mode="weighted",
        active_available=True,
        safety_status="stable",
        fallback_reason=None,
        sources=3,
        current_price=100.0,
        median_target_price=110.0,
        weighted_target_price=112.0,
        active_target_price=112.0,
        median_expected_return_percent=10.0,
        weighted_expected_return_percent=12.0,
        active_expected_return_percent=12.0,
    )


def test_regular_capture_series_is_healthy() -> None:
    now = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)
    rows = [
        _snapshot(row_id=1, ticker="AAA", captured_at=now - timedelta(hours=12)),
        _snapshot(row_id=2, ticker="AAA", captured_at=now - timedelta(hours=6)),
        _snapshot(row_id=3, ticker="AAA", captured_at=now),
    ]

    result = _build_ticker_health_from_rows(
        ticker="AAA",
        rows=rows,
        expected_interval_hours=6.0,
        now=now,
    )

    assert result.status == "healthy"
    assert result.reasons == []
    assert result.missed_cycles_estimate == 0
    assert result.gap_violations == 0
    assert result.longest_gap_hours == pytest.approx(6.0)
    assert result.continuity_percent == pytest.approx(100.0)
    assert result.latest_age_hours == pytest.approx(0.0)


def test_large_gap_marks_degraded_and_estimates_missed_cycle() -> None:
    now = datetime(2026, 9, 6, 18, tzinfo=timezone.utc)
    rows = [
        _snapshot(row_id=1, ticker="AAA", captured_at=now - timedelta(hours=18)),
        _snapshot(row_id=2, ticker="AAA", captured_at=now - timedelta(hours=6)),
        _snapshot(row_id=3, ticker="AAA", captured_at=now),
    ]

    result = _build_ticker_health_from_rows(
        ticker="AAA",
        rows=rows,
        expected_interval_hours=6.0,
        now=now,
    )

    assert result.status == "degraded"
    assert "capture_gaps_detected" in result.reasons
    assert result.gap_violations == 1
    assert result.missed_cycles_estimate == 1
    assert result.longest_gap_hours == pytest.approx(12.0)
    assert result.continuity_percent == pytest.approx(66.6666667)


def test_stale_latest_snapshot_has_priority_over_gap_degradation() -> None:
    now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    rows = [
        _snapshot(row_id=1, ticker="AAA", captured_at=now - timedelta(hours=24)),
        _snapshot(row_id=2, ticker="AAA", captured_at=now - timedelta(hours=18)),
    ]

    result = _build_ticker_health_from_rows(
        ticker="AAA",
        rows=rows,
        expected_interval_hours=6.0,
        now=now,
    )

    assert result.status == "stale"
    assert result.reasons == ["latest_snapshot_stale"]
    assert result.latest_age_hours == pytest.approx(18.0)


def test_target_year_rollover_is_not_counted_as_capture_gap() -> None:
    now = datetime(2027, 1, 1, 12, tzinfo=timezone.utc)
    rows = [
        _snapshot(
            row_id=1,
            ticker="AAA",
            captured_at=now - timedelta(hours=18),
            target_year=2027,
        ),
        _snapshot(
            row_id=2,
            ticker="AAA",
            captured_at=now - timedelta(hours=6),
            target_year=2028,
        ),
        _snapshot(
            row_id=3,
            ticker="AAA",
            captured_at=now,
            target_year=2028,
        ),
    ]

    result = _build_ticker_health_from_rows(
        ticker="AAA",
        rows=rows,
        expected_interval_hours=6.0,
        now=now,
    )

    assert result.status == "healthy"
    assert result.observed_intervals == 1
    assert result.missed_cycles_estimate == 0
    assert result.longest_gap_hours == pytest.approx(6.0)


def test_overview_scopes_to_current_allowlist_and_reports_warming_ticker(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)
    monkeypatch.setenv("SHADOW_HISTORY_INTERVAL_HOURS", "6")

    with Session(engine) as db:
        db.add(
            ConsensusCanarySettings(
                id=1,
                enabled=True,
                tickers=["AAA", "BBB"],
                updated_by="test",
                updated_at=now,
            )
        )
        db.add_all(
            [
                _snapshot(row_id=1, ticker="AAA", captured_at=now - timedelta(hours=6)),
                _snapshot(row_id=2, ticker="AAA", captured_at=now),
                _snapshot(row_id=3, ticker="OLD", captured_at=now),
            ]
        )
        db.commit()

        result = build_canary_evidence_health(db, days=30, now=now)

    assert result.status == "warming_up"
    assert result.configured_tickers == 2
    assert result.tickers_with_evidence == 1
    assert result.healthy_tickers == 1
    assert result.warming_up_tickers == 1
    assert result.stale_tickers == 0
    assert result.missed_cycles_estimate == 0
    assert [item.ticker for item in result.items] == ["BBB", "AAA"]
    assert "OLD" not in {item.ticker for item in result.items}


def test_overview_without_configured_tickers_is_explicitly_not_configured(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)
    monkeypatch.setenv("SHADOW_HISTORY_INTERVAL_HOURS", "6")

    with Session(engine) as db:
        result = build_canary_evidence_health(db, days=30, now=now)

    assert result.status == "not_configured"
    assert result.configured_tickers == 0
    assert result.items == []
    assert result.latest_capture_at is None
    assert result.median_continuity_percent is None
