from app.application import app


def test_shadow_consensus_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/analytics/shadow-consensus" in paths
    assert "/api/analytics/consensus-readiness" in paths
