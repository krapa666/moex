from app.application import app
from app.consensus_robustness_api import get_consensus_backtest_robustness
from app.models import Base
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_shadow_consensus_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/analytics/shadow-consensus" in paths
    assert "/api/analytics/shadow-consensus/history" in paths
    assert "/api/analytics/shadow-consensus/drift" in paths
    assert "/api/analytics/shadow-consensus/capture" in paths
    assert "/api/analytics/consensus-readiness" in paths


def test_shadow_capture_requires_explicit_local_scope() -> None:
    client = TestClient(app)
    response = client.post("/api/analytics/shadow-consensus/capture")
    assert response.status_code == 403


def test_robustness_response_reuses_same_calculation_for_readiness() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        result = get_consensus_backtest_robustness(
            snapshot="pre_year",
            min_sources=2,
            db=db,
        )

    readiness = result["readiness"]
    assert readiness.ready is False
    assert readiness.gates_passed == 0
    assert readiness.gates_total == 11
