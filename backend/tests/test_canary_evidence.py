from datetime import datetime, timedelta, timezone

import pytest
from app.canary_evidence import (
    CanaryEvidenceSnapshot,
    _build_ticker_evidence_from_rows,
    build_canary_evidence_overview,
    capture_canary_evidence,
)
from app.consensus_canary import ActiveConsensusResult, ConsensusCanarySettings
from app.database import Base
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def _snapshot(
    *,
    row_id: int,
    ticker: str,
    captured_at: datetime,
    target_year: int = 2027,
    enabled: bool = True,
    configured_mode: str = "weighted_canary",
    effective_mode: str = "weighted",
    fallback_reason: str | None = None,
) -> CanaryEvidenceSnapshot:
    return CanaryEvidenceSnapshot(
        id=row_id,
        ticker=ticker,
        target_year=target_year,
        captured_at=captured_at,
        canary_enabled=enabled,
        in_allowlist=True,
        configured_mode=configured_mode,
        effective_mode=effective_mode,
        active_available=True,
        safety_status="stable" if effective_mode == "weighted" else "watch",
        fallback_reason=fallback_reason,
        sources=3,
        current_price=100.0,
        median_target_price=110.0,
        weighted_target_price=112.0,
        active_target_price=112.0 if effective_mode == "weighted" else 110.0,
        median_expected_return_percent=10.0,
        weighted_expected_return_percent=12.0,
        active_expected_return_percent=12.0 if effective_mode == "weighted" else 10.0,
    )


def test_time_weighted_metrics_count_fallback_and_recovery() -> None:
    start = datetime(2026, 9, 6, tzinfo=timezone.utc)
    rows = [
        _snapshot(row_id=1, ticker="AAA", captured_at=start),
        _snapshot(row_id=2, ticker="AAA", captured_at=start + timedelta(hours=2)),
        _snapshot(
            row_id=3,
            ticker="AAA",
            captured_at=start + timedelta(hours=8),
            effective_mode="median",
            fallback_reason="drift_watch",
        ),
        _snapshot(row_id=4, ticker="AAA", captured_at=start + timedelta(hours=10)),
        _snapshot(row_id=5, ticker="AAA", captured_at=start + timedelta(hours=14)),
    ]

    result = _build_ticker_evidence_from_rows(ticker="AAA", days=30, rows=rows)

    assert result.configured_weighted_hours == pytest.approx(14.0)
    assert result.weighted_hours == pytest.approx(12.0)
    assert result.fallback_hours == pytest.approx(2.0)
    assert result.weighted_uptime_percent == pytest.approx(85.7142857)
    assert result.fallback_incidents == 1
    assert result.recoveries == 1
    assert result.longest_weighted_run_hours == pytest.approx(8.0)
    assert result.longest_fallback_run_hours == pytest.approx(2.0)
    assert result.fallback_reason_counts == {"drift_watch": 1}
    assert result.history_span_hours == pytest.approx(14.0)
    assert result.current_effective_mode == "weighted"


def test_target_year_rollover_does_not_create_false_recovery() -> None:
    start = datetime(2026, 12, 31, 18, tzinfo=timezone.utc)
    rows = [
        _snapshot(
            row_id=1,
            ticker="AAA",
            captured_at=start,
            target_year=2027,
            effective_mode="median",
            fallback_reason="drift_watch",
        ),
        _snapshot(
            row_id=2,
            ticker="AAA",
            captured_at=start + timedelta(hours=6),
            target_year=2028,
            effective_mode="weighted",
        ),
    ]

    result = _build_ticker_evidence_from_rows(ticker="AAA", days=30, rows=rows)

    assert result.target_years == [2027, 2028]
    assert result.latest_target_year == 2028
    assert result.recoveries == 0
    assert result.fallback_incidents == 1
    assert result.configured_weighted_hours == 0.0


def test_overview_aggregates_current_modes_and_prioritizes_fallback() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)

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
                _snapshot(row_id=3, ticker="BBB", captured_at=now - timedelta(hours=6)),
                _snapshot(
                    row_id=4,
                    ticker="BBB",
                    captured_at=now,
                    effective_mode="median",
                    fallback_reason="live_divergence_watch",
                ),
            ]
        )
        db.commit()

        result = build_canary_evidence_overview(db, days=30)

    assert result.configured_tickers == 2
    assert result.tickers_with_evidence == 2
    assert result.snapshots == 4
    assert result.current_weighted_tickers == 1
    assert result.current_fallback_tickers == 1
    assert result.current_median_tickers == 0
    assert [item.ticker for item in result.items] == ["BBB", "AAA"]


def test_capture_records_disabled_configured_ticker_for_rollback_boundary(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    current = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)

    with Session(engine) as db:
        db.add(
            ConsensusCanarySettings(
                id=1,
                enabled=False,
                tickers=["AAA"],
                updated_by="test",
                updated_at=current,
            )
        )
        db.commit()

        monkeypatch.setattr(
            "app.canary_evidence.build_active_consensus",
            lambda _db, ticker: ActiveConsensusResult(
                ticker=ticker,
                target_year=2027,
                active_available=True,
                reason=None,
                canary_enabled=False,
                in_allowlist=True,
                configured_mode="median",
                effective_mode="median",
                safety_status=None,
                fallback_reason=None,
                sources=3,
                current_price=100.0,
                median_target_price=110.0,
                weighted_target_price=112.0,
                active_target_price=110.0,
                median_expected_return_percent=10.0,
                weighted_expected_return_percent=12.0,
                active_expected_return_percent=10.0,
            ),
        )

        result = capture_canary_evidence(db, captured_at=current, retention_days=30)
        stored = db.scalars(select(CanaryEvidenceSnapshot)).one()

    assert result.configured_tickers == 1
    assert result.snapshots_created == 1
    assert stored.canary_enabled is False
    assert stored.configured_mode == "median"
    assert stored.effective_mode == "median"
    assert stored.active_target_price == pytest.approx(110.0)
