from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.consensus_canary import (
    CanaryPolicyError,
    ConsensusCanarySettings,
    build_active_consensus,
    configure_canary,
    get_canary_settings,
    list_canary_events,
    rollback_canary,
)
from app.models import AnalystTable, Base, StockRow
from app.shadow_consensus import ShadowConsensusResult


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _seed_ticker(db: Session, ticker: str = "AAA") -> None:
    for index, (profit, expected_return) in enumerate(
        [(100.0, 5.0), (110.0, 10.0), (125.0, 15.0)], start=1
    ):
        table = AnalystTable(
            analyst_name=f"Source {index}",
            sort_order=index,
            year_offset=1,
            forecast_start_year=2027,
        )
        db.add(table)
        db.flush()
        db.add(
            StockRow(
                table_id=table.id,
                ticker=ticker,
                current_price=100.0,
                shares_billion=10.0,
                pe_avg_5y=10.0,
                net_profit_year_map={"2027": profit},
                forecast_profit_year1_billion_rub=profit,
                upside_percent_year1=expected_return,
            )
        )
    db.commit()


def _shadow(**overrides) -> ShadowConsensusResult:
    values = {
        "ticker": "AAA",
        "target_year": 2027,
        "training_snapshot": "pre_year",
        "as_of": __import__("datetime").datetime(2026, 9, 6, tzinfo=__import__("datetime").timezone.utc),
        "shadow_available": True,
        "reason": None,
        "sources": 3,
        "sources_with_training_history": 2,
        "training_samples": 8,
        "weighting_uses_history": True,
        "max_source_weight_percent": 40.0,
        "min_source_weight_percent": 25.0,
        "median_net_profit_billion_rub": 110.0,
        "mean_net_profit_billion_rub": 111.6667,
        "weighted_net_profit_billion_rub": 112.0,
        "median_target_price": 110.0,
        "mean_target_price": 111.6667,
        "weighted_target_price": 112.0,
        "weighted_vs_median_target_delta_rub": 2.0,
        "weighted_vs_median_target_delta_percent": 1.8181818,
        "current_price": 100.0,
        "median_market_gap_percent": 10.0,
        "weighted_market_gap_percent": 12.0,
    }
    values.update(overrides)
    return ShadowConsensusResult(**values)


def test_canary_defaults_to_disabled_without_persisted_state() -> None:
    with Session(_engine()) as db:
        result = get_canary_settings(db)

    assert result.enabled is False
    assert result.tickers == []
    assert result.max_tickers == 5


def test_enable_requires_ready_promotion(monkeypatch) -> None:
    with Session(_engine()) as db:
        _seed_ticker(db)
        monkeypatch.setattr(
            "app.consensus_canary.build_production_impact",
            lambda *_args, **_kwargs: SimpleNamespace(
                promotion=SimpleNamespace(status="NOT_READY")
            ),
        )

        with pytest.raises(CanaryPolicyError, match="NOT_READY"):
            configure_canary(
                db,
                enabled=True,
                tickers=["AAA"],
                actor="local-network",
            )


def test_enable_and_rollback_are_audited(monkeypatch) -> None:
    with Session(_engine()) as db:
        _seed_ticker(db)
        monkeypatch.setattr(
            "app.consensus_canary.build_production_impact",
            lambda *_args, **_kwargs: SimpleNamespace(
                promotion=SimpleNamespace(status="READY_FOR_MANUAL_PROMOTION")
            ),
        )
        monkeypatch.setattr(
            "app.consensus_canary.build_shadow_consensus_batch",
            lambda *_args, **_kwargs: [_shadow()],
        )
        monkeypatch.setattr(
            "app.consensus_canary.build_shadow_drift_overview",
            lambda *_args, **_kwargs: SimpleNamespace(
                items=[SimpleNamespace(ticker="AAA", status="stable")]
            ),
        )

        enabled = configure_canary(
            db,
            enabled=True,
            tickers=["aaa"],
            actor="local-network",
            note="controlled start",
        )
        assert enabled.enabled is True
        assert enabled.tickers == ["AAA"]
        events = list_canary_events(db)
        assert events[0].action == "enable"
        assert events[0].promotion_status == "READY_FOR_MANUAL_PROMOTION"

        rolled_back = rollback_canary(
            db,
            actor="local-network",
            note="operator rollback",
        )
        assert rolled_back.enabled is False
        events = list_canary_events(db)
        assert events[0].action == "rollback"
        assert events[0].previous_enabled is True
        assert events[0].new_enabled is False


def test_enable_rejects_ticker_without_real_weight_history(monkeypatch) -> None:
    with Session(_engine()) as db:
        _seed_ticker(db)
        monkeypatch.setattr(
            "app.consensus_canary.build_production_impact",
            lambda *_args, **_kwargs: SimpleNamespace(
                promotion=SimpleNamespace(status="READY_FOR_MANUAL_PROMOTION")
            ),
        )
        monkeypatch.setattr(
            "app.consensus_canary.build_shadow_consensus_batch",
            lambda *_args, **_kwargs: [
                _shadow(weighting_uses_history=False, sources_with_training_history=0)
            ],
        )

        with pytest.raises(CanaryPolicyError, match="insufficient_weight_history"):
            configure_canary(
                db,
                enabled=True,
                tickers=["AAA"],
                actor="local-network",
            )


def test_active_consensus_uses_weighted_only_for_stable_guarded_canary(monkeypatch) -> None:
    with Session(_engine()) as db:
        _seed_ticker(db)
        db.add(
            ConsensusCanarySettings(
                id=1,
                enabled=True,
                tickers=["AAA"],
                updated_by="local-network",
            )
        )
        db.commit()
        monkeypatch.setattr(
            "app.consensus_canary.build_shadow_consensus",
            lambda *_args, **_kwargs: _shadow(),
        )
        monkeypatch.setattr(
            "app.consensus_canary.build_shadow_drift",
            lambda *_args, **_kwargs: SimpleNamespace(status="stable"),
        )

        result = build_active_consensus(db, ticker="aaa")

    assert result.configured_mode == "weighted_canary"
    assert result.effective_mode == "weighted"
    assert result.median_target_price == pytest.approx(110.0)
    assert result.weighted_target_price == pytest.approx(112.0)
    assert result.active_target_price == pytest.approx(112.0)
    assert result.median_expected_return_percent == pytest.approx(10.0)
    assert result.weighted_expected_return_percent == pytest.approx(12.0)
    assert result.active_expected_return_percent == pytest.approx(12.0)


def test_active_consensus_falls_back_to_median_on_live_or_forward_guard(monkeypatch) -> None:
    with Session(_engine()) as db:
        _seed_ticker(db)
        db.add(
            ConsensusCanarySettings(
                id=1,
                enabled=True,
                tickers=["AAA"],
                updated_by="local-network",
            )
        )
        db.commit()

        monkeypatch.setattr(
            "app.consensus_canary.build_shadow_consensus",
            lambda *_args, **_kwargs: _shadow(weighted_vs_median_target_delta_percent=12.0),
        )
        live_blocked = build_active_consensus(db, ticker="AAA")
        assert live_blocked.effective_mode == "median"
        assert live_blocked.fallback_reason == "live_divergence_watch"
        assert live_blocked.active_target_price == pytest.approx(110.0)

        monkeypatch.setattr(
            "app.consensus_canary.build_shadow_consensus",
            lambda *_args, **_kwargs: _shadow(),
        )
        monkeypatch.setattr(
            "app.consensus_canary.build_shadow_drift",
            lambda *_args, **_kwargs: SimpleNamespace(status="watch"),
        )
        forward_blocked = build_active_consensus(db, ticker="AAA")
        assert forward_blocked.effective_mode == "median"
        assert forward_blocked.fallback_reason == "drift_watch"
        assert forward_blocked.active_target_price == pytest.approx(110.0)
