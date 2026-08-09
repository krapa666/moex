from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def function_source(source: str, start_marker: str, end_marker: str) -> str:
    return source.split(start_marker, 1)[1].split(end_marker, 1)[0]


def test_regular_and_comparison_rows_have_all_17_table_cells() -> None:
    source = (REPO_ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    comparison = function_source(
        source,
        "function createInlineComparisonRow(item)",
        "function median(values)",
    )
    consensus = function_source(
        source,
        "function createConsensusComparisonRow(items, ticker)",
        "function scheduleInlineComparisonHide",
    )
    regular = function_source(source, "function renderRows(rows)", "document.addEventListener")

    assert comparison.count("<td") == 17
    assert consensus.count("<td") == 17
    assert regular.count("<td") == 17
    assert 'data-field="dividends_year1"' in regular
    assert 'data-field="dividends_year2"' in regular
    assert 'data-cell="dividend_yield_year1"' in regular
    assert 'data-cell="dividend_yield_year2"' in regular
