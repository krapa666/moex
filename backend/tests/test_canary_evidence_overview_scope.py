from datetime import datetime, timezone

from app.canary_evidence import CanaryEvidenceSnapshot, build_canary_evidence_overview
from app.consensus_canary import ConsensusCanarySettings
from app.database import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def _snapshot(ticker: str, row_id: int, now: datetime) -> CanaryEvidenceSnapshot:
    return CanaryEvidenceSnapshot(
        id=row_id,
        ticker=ticker,
        target_year=2027,
        captured_at=now,
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


def test_overview_excludes_removed_ticker_but_keeps_per_ticker_history_in_database() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)

    with Session(engine) as db:
        db.add(
            ConsensusCanarySettings(
                id=1,
                enabled=True,
                tickers=["AAA"],
                updated_by="test",
                updated_at=now,
            )
        )
        db.add_all([
            _snapshot("AAA", 1, now),
            _snapshot("OLD", 2, now),
        ])
        db.commit()

        result = build_canary_evidence_overview(db, days=30)

    assert result.configured_tickers == 1
    assert [item.ticker for item in result.items] == ["AAA"]
    assert result.tickers_with_evidence == 1
    assert result.current_weighted_tickers == 1
    assert result.current_unknown_tickers == 0


def test_overview_marks_configured_ticker_without_snapshot_as_unknown() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)

    with Session(engine) as db:
        db.add(
            ConsensusCanarySettings(
                id=1,
                enabled=True,
                tickers=["AAA"],
                updated_by="test",
                updated_at=now,
            )
        )
        db.commit()

        result = build_canary_evidence_overview(db, days=30)

    assert result.tickers_with_evidence == 0
    assert result.current_weighted_tickers == 0
    assert result.current_fallback_tickers == 0
    assert result.current_median_tickers == 0
    assert result.current_unknown_tickers == 1
    assert result.items[0].current_configured_mode is None
