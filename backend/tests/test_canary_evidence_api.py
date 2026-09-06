from app.application import app
from fastapi.testclient import TestClient


def test_canary_evidence_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/analytics/consensus-canary/evidence" in paths
    assert "/api/analytics/consensus-canary/evidence/ticker" in paths
    assert "/api/analytics/consensus-canary/evidence/history" in paths
    assert "/api/analytics/consensus-canary/evidence/capture" in paths


def test_manual_canary_evidence_capture_requires_explicit_local_scope() -> None:
    client = TestClient(app)
    response = client.post("/api/analytics/consensus-canary/evidence/capture")
    assert response.status_code == 403
