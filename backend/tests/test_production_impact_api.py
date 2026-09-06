from datetime import datetime, timezone

import app.production_impact_api as api_module
from app.application import app
from app.production_impact import (
    ProductionImpactResult,
    ProductionImpactSummary,
    PromotionDossier,
)
from fastapi.testclient import TestClient


def _result() -> ProductionImpactResult:
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    impact = ProductionImpactSummary(
        generated_at=now,
        top_n=10,
        universe_tickers=20,
        comparable_tickers=18,
        comparable_coverage_percent=90.0,
        median_abs_target_delta_percent=3.0,
        max_abs_target_delta_percent=8.0,
        median_abs_expected_return_delta_pp=2.0,
        return_sign_flip_tickers=1,
        return_sign_flip_percent=5.0,
        rank_correlation_spearman=0.96,
        mean_abs_rank_change=1.2,
        max_abs_rank_change=4,
        top_n_overlap_tickers=9,
        top_n_overlap_percent=90.0,
        top_n_entered=["AAA"],
        top_n_exited=["BBB"],
        mean_abs_watchlist_score_delta=3.0,
        items=[],
    )
    promotion = PromotionDossier(
        generated_at=now,
        status="OBSERVE",
        gates_passed=8,
        gates_total=10,
        historical_snapshot="mid_year",
        historical_readiness=True,
        forward_history_days=30,
        gates=[],
    )
    return ProductionImpactResult(impact=impact, promotion=promotion)


def test_production_impact_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/analytics/production-impact" in paths
    assert "/api/analytics/promotion-dossier" in paths


def test_public_production_impact_response_does_not_require_local_scope(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "build_production_impact", lambda *_args, **_kwargs: _result())
    client = TestClient(app)

    response = client.get("/api/analytics/production-impact?top_n=10&history_days=30")

    assert response.status_code == 200
    payload = response.json()
    assert payload["promotion"]["status"] == "OBSERVE"
    assert payload["impact"]["rank_correlation_spearman"] == 0.96
    assert "analyst_name" not in response.text
    assert "source_weight" not in response.text
