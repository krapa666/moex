from app.consensus_backtest import ConsensusBacktestRobustnessResult
from app.consensus_readiness import evaluate_consensus_readiness


def _robustness(**overrides) -> ConsensusBacktestRobustnessResult:
    values = {
        "snapshot": "pre_year",
        "min_sources": 2,
        "observations": 40,
        "tickers": 12,
        "years": 3,
        "weighted_median_delta_pp": 2.0,
        "weighted_mean_delta_pp": 1.0,
        "positive_ticker_slices": 8,
        "ticker_slices": 12,
        "positive_year_slices": 2,
        "year_slices": 3,
        "ticker_jackknife_preserved": 10,
        "ticker_jackknife_cases": 12,
        "year_jackknife_preserved": 3,
        "year_jackknife_cases": 3,
        "positive_parameter_cases": 24,
        "parameter_cases": 27,
        "parameter_min_median_delta_pp": 0.4,
        "parameter_max_median_delta_pp": 3.2,
        "by_year": [],
        "by_ticker": [],
        "jackknife_year": [],
        "jackknife_ticker": [],
        "parameter_sweep": [],
    }
    values.update(overrides)
    return ConsensusBacktestRobustnessResult(**values)


def test_readiness_passes_only_when_every_policy_gate_passes() -> None:
    result = evaluate_consensus_readiness(_robustness())

    assert result.ready is True
    assert result.gates_passed == result.gates_total
    assert result.gates_total == 11
    assert all(gate.passed for gate in result.gates)


def test_readiness_reports_individual_failed_gates_without_promoting() -> None:
    result = evaluate_consensus_readiness(
        _robustness(
            observations=29,
            weighted_median_delta_pp=0.9,
            parameter_min_median_delta_pp=-0.1,
        )
    )

    failed = {gate.key for gate in result.gates if not gate.passed}
    assert result.ready is False
    assert {"observations", "median_improvement", "worst_parameter_case"} <= failed
    assert result.gates_passed == result.gates_total - len(failed)


def test_readiness_with_no_robustness_evidence_is_not_ready() -> None:
    result = evaluate_consensus_readiness(
        _robustness(
            observations=0,
            tickers=0,
            years=0,
            weighted_median_delta_pp=None,
            weighted_mean_delta_pp=None,
            positive_ticker_slices=0,
            ticker_slices=0,
            positive_year_slices=0,
            year_slices=0,
            ticker_jackknife_preserved=0,
            ticker_jackknife_cases=0,
            year_jackknife_preserved=0,
            year_jackknife_cases=0,
            positive_parameter_cases=0,
            parameter_cases=0,
            parameter_min_median_delta_pp=None,
            parameter_max_median_delta_pp=None,
        )
    )

    assert result.ready is False
    assert result.gates_passed == 0
    assert result.ticker_slice_positive_ratio == 0
    assert result.parameter_positive_ratio == 0
