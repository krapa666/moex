from datetime import datetime, timezone
from types import SimpleNamespace

import app.production_impact as impact_module
from app.database import Base
from app.models import AnalystTable
from app.production_impact import (
    ProductionImpactSummary,
    _score,
    _spearman,
    build_production_impact_summary,
    build_promotion_dossier,
)
from app.shadow_consensus import ShadowConsensusResult
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def _shadow(
    ticker: str,
    *,
    median_target: float,
    weighted_target: float,
    current_price: float = 100.0,
) -> ShadowConsensusResult:
    delta = weighted_target - median_target
    return ShadowConsensusResult(
        ticker=ticker,
        target_year=2026,
        training_snapshot="mid_year",
        as_of=datetime(2026, 9, 6, tzinfo=timezone.utc),
        shadow_available=True,
        reason=None,
        sources=3,
        sources_with_training_history=3,
        training_samples=20,
        weighting_uses_history=True,
        max_source_weight_percent=45.0,
        min_source_weight_percent=25.0,
        median_net_profit_billion_rub=100.0,
        mean_net_profit_billion_rub=101.0,
        weighted_net_profit_billion_rub=102.0,
        median_target_price=median_target,
        mean_target_price=(median_target + weighted_target) / 2,
        weighted_target_price=weighted_target,
        weighted_vs_median_target_delta_rub=delta,
        weighted_vs_median_target_delta_percent=100.0 * delta / median_target,
        current_price=current_price,
        median_market_gap_percent=100.0 * (median_target / current_price - 1.0),
        weighted_market_gap_percent=100.0 * (weighted_target / current_price - 1.0),
    )


def _impact_summary(**overrides) -> ProductionImpactSummary:
    values = {
        "generated_at": datetime(2026, 9, 6, tzinfo=timezone.utc),
        "top_n": 10,
        "universe_tickers": 20,
        "comparable_tickers": 18,
        "comparable_coverage_percent": 90.0,
        "median_abs_target_delta_percent": 3.0,
        "max_abs_target_delta_percent": 8.0,
        "median_abs_expected_return_delta_pp": 2.5,
        "return_sign_flip_tickers": 1,
        "return_sign_flip_percent": 5.0,
        "rank_correlation_spearman": 0.96,
        "mean_abs_rank_change": 1.2,
        "max_abs_rank_change": 4,
        "top_n_overlap_tickers": 9,
        "top_n_overlap_percent": 90.0,
        "top_n_entered": ["NEW"],
        "top_n_exited": ["OLD"],
        "mean_abs_watchlist_score_delta": 3.5,
        "items": [],
    }
    values.update(overrides)
    return ProductionImpactSummary(**values)


def test_watchlist_score_mirrors_frontend_60_25_15_policy() -> None:
    assert _score(100.0, 140.0, 50.0, "signal") == 72
    assert _score(100.0, 140.0, 50.0, "above_range") == 64
    assert _score(100.0, 200.0, 100.0, None) == 60
    assert _score(None, 140.0, 50.0, "signal") is None


def test_spearman_detects_identical_and_reversed_rankings() -> None:
    assert _spearman({"A": 30.0, "B": 20.0, "C": 10.0}, {"A": 5.0, "B": 4.0, "C": 3.0}) == 1.0
    assert _spearman({"A": 30.0, "B": 20.0, "C": 10.0}, {"A": 1.0, "B": 2.0, "C": 3.0}) == -1.0


def test_impact_changes_only_price_layer_and_preserves_dividend_layer(monkeypatch) -> None:
    shadows = [
        _shadow("AAA", median_target=120.0, weighted_target=130.0),
        _shadow("BBB", median_target=110.0, weighted_target=105.0),
        _shadow("CCC", median_target=150.0, weighted_target=160.0),
    ]
    monkeypatch.setattr(impact_module, "build_shadow_consensus_batch", lambda *_args, **_kwargs: shadows)
    monkeypatch.setattr(
        impact_module,
        "_load_median_returns",
        lambda *_args, **_kwargs: {"AAA": 30.0, "BBB": 15.0, "CCC": 50.0},
    )
    monkeypatch.setattr(
        impact_module,
        "_load_latest_volume_signals",
        lambda *_args, **_kwargs: {"AAA": "signal", "BBB": "normal", "CCC": "above_range"},
    )

    result = build_production_impact_summary(SimpleNamespace(), top_n=2)
    by_ticker = {item.ticker: item for item in result.items}

    # AAA median price potential is 20%, so the unchanged dividend layer is 10 pp.
    # Weighted price potential is 30%, hence weighted full return is 40%.
    assert by_ticker["AAA"].median_expected_return_percent == 30.0
    assert by_ticker["AAA"].weighted_expected_return_percent == 40.0
    assert by_ticker["AAA"].expected_return_delta_pp == 10.0
    assert by_ticker["AAA"].median_watchlist_score == 52
    assert by_ticker["AAA"].weighted_watchlist_score == 62
    assert result.comparable_coverage_percent == 100.0
    assert result.top_n == 2
    assert result.rank_correlation_spearman is not None


def _ready_result(ready: bool):
    return SimpleNamespace(
        ready=ready,
        gates_passed=11 if ready else 8,
        gates_total=11,
    )


def _overview(*, classified_coverage=90.0, alerts=0, actionable=1, classified=10, span=240.0):
    return SimpleNamespace(
        classified_coverage_percent=classified_coverage,
        alert_tickers=alerts,
        actionable_tickers=actionable,
        classified_tickers=classified,
        items=[SimpleNamespace(status="stable", history_span_hours=span) for _ in range(classified)],
    )


def test_promotion_dossier_requires_historical_and_forward_evidence(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(AnalystTable(analyst_name="Primary", forecast_start_year=2026, sort_order=1))
        db.commit()

        monkeypatch.setattr(impact_module, "build_consensus_readiness", lambda *_args, **_kwargs: _ready_result(True))
        monkeypatch.setattr(impact_module, "build_shadow_drift_overview", lambda *_args, **_kwargs: _overview())
        dossier = build_promotion_dossier(
            db,
            impact=_impact_summary(),
            history_days=30,
            as_of=datetime(2026, 9, 6, tzinfo=timezone.utc),
        )

    assert dossier.status == "READY_FOR_MANUAL_PROMOTION"
    assert dossier.gates_passed == dossier.gates_total == 10
    assert all(gate.passed for gate in dossier.gates)


def test_promotion_dossier_stays_not_ready_when_historical_readiness_fails(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(AnalystTable(analyst_name="Primary", forecast_start_year=2026, sort_order=1))
        db.commit()

        monkeypatch.setattr(impact_module, "build_consensus_readiness", lambda *_args, **_kwargs: _ready_result(False))
        monkeypatch.setattr(impact_module, "build_shadow_drift_overview", lambda *_args, **_kwargs: _overview())
        dossier = build_promotion_dossier(db, impact=_impact_summary())

    assert dossier.status == "NOT_READY"
    failed = {gate.key for gate in dossier.gates if not gate.passed}
    assert "historical_readiness" in failed


def test_promotion_dossier_observes_when_forward_coverage_is_weak(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(AnalystTable(analyst_name="Primary", forecast_start_year=2026, sort_order=1))
        db.commit()

        monkeypatch.setattr(impact_module, "build_consensus_readiness", lambda *_args, **_kwargs: _ready_result(True))
        monkeypatch.setattr(
            impact_module,
            "build_shadow_drift_overview",
            lambda *_args, **_kwargs: _overview(classified_coverage=50.0, span=48.0),
        )
        dossier = build_promotion_dossier(db, impact=_impact_summary())

    assert dossier.status == "OBSERVE"
    failed = {gate.key for gate in dossier.gates if not gate.passed}
    assert {"forward_classified_coverage", "forward_observation_span"} <= failed
