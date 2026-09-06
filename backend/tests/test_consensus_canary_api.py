from fastapi.testclient import TestClient

from app.application import app


def test_consensus_canary_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/analytics/consensus-canary" in paths
    assert "/api/analytics/consensus-canary/rollback" in paths
    assert "/api/analytics/consensus-canary/events" in paths
    assert "/api/analytics/active-consensus" in paths


def test_consensus_canary_write_requires_explicit_local_scope() -> None:
    client = TestClient(app)
    response = client.put(
        "/api/analytics/consensus-canary",
        json={"enabled": False, "tickers": []},
    )
    assert response.status_code == 403


def test_consensus_canary_rollback_requires_explicit_local_scope() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/analytics/consensus-canary/rollback",
        json={"note": "test"},
    )
    assert response.status_code == 403


def test_consensus_canary_events_require_explicit_local_scope() -> None:
    client = TestClient(app)
    response = client.get("/api/analytics/consensus-canary/events")
    assert response.status_code == 403
