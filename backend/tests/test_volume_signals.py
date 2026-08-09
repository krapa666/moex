from decimal import Decimal

from app.volume_collector import (
    _notification_matches_scope,
    _select_notification_candidates,
    _status_values,
)
from app.volume_config import VolumeSettings
from app.volume_signals import evaluate_turnover

BASELINE = [Decimal("100")] * 60


def evaluate(current: str):
    return evaluate_turnover(
        Decimal(current),
        BASELINE,
        minimum_count=60,
        min_ratio=Decimal("3.6"),
        max_ratio=Decimal("6.5"),
    )


def test_signal_boundaries_are_inclusive() -> None:
    assert evaluate("360").status == "signal"
    assert evaluate("650").status == "signal"


def test_value_above_upper_boundary_does_not_signal() -> None:
    result = evaluate("651")

    assert result.status == "above_range"
    assert result.ratio == Decimal("6.51")


def test_current_value_is_excluded_from_baseline() -> None:
    result = evaluate("400")

    assert result.average == Decimal("100")
    assert result.ratio == Decimal("4")


def test_insufficient_history_has_no_ratio() -> None:
    result = evaluate_turnover(
        Decimal("1000"),
        [Decimal("100")] * 59,
        minimum_count=60,
        min_ratio=Decimal("3.6"),
        max_ratio=Decimal("6.5"),
    )

    assert result.status == "insufficient"
    assert result.ratio is None


def test_notification_scope_can_include_all_tqbr_or_only_imoex() -> None:
    assert _notification_matches_scope("imoex", is_imoex=True)
    assert not _notification_matches_scope("imoex", is_imoex=False)
    assert _notification_matches_scope("all", is_imoex=False)


def test_stored_baseline_length_controls_signal_calculation() -> None:
    result = _status_values(
        VolumeSettings.from_env(),
        Decimal("360"),
        [Decimal("100")] * 10,
        baseline_sessions=10,
    )

    assert result.status == "signal"
    assert result.count == 10


def test_high_ratio_is_sent_without_broad_market_condition() -> None:
    candidates = [
        {"ticker": "SBER", "status": "signal"},
        {"ticker": "GAZP", "status": "above_range"},
    ]

    selected, suppressed = _select_notification_candidates(
        candidates,
        imoex_anomalies=10,
        broad_market_threshold=10,
    )

    assert selected == candidates
    assert suppressed == 0


def test_broad_market_condition_suppresses_only_high_ratio_candidates() -> None:
    ordinary = {"ticker": "SBER", "status": "signal"}
    high_ratio = {"ticker": "GAZP", "status": "above_range"}

    selected, suppressed = _select_notification_candidates(
        [ordinary, high_ratio],
        imoex_anomalies=11,
        broad_market_threshold=10,
    )

    assert selected == [ordinary]
    assert suppressed == 1
