from datetime import datetime, timezone

from .models import StockRow


def _remaining_dividend_totals(
    row: StockRow,
    dividend_totals_by_year_index: dict[int, float],
) -> dict[int, float]:
    """Convert full-year forecasts to dividend cash flows still receivable today."""

    current_year = str(datetime.now(timezone.utc).year)
    forecast_map = row.dividend_year_map or {}
    paid_map = row.paid_dividend_year_map or {}

    full_current_year = max(float(forecast_map.get(current_year) or 0.0), 0.0)
    paid_current_year = max(float(paid_map.get(current_year) or 0.0), 0.0)
    already_consumed = min(full_current_year, paid_current_year)

    if already_consumed <= 0:
        return dividend_totals_by_year_index

    return {
        year_index: max(float(total) - already_consumed, 0.0)
        for year_index, total in dividend_totals_by_year_index.items()
    }


def recalculate_fields(
    row: StockRow,
    dividend_totals_by_year_index: dict[int, float] | None = None,
) -> None:
    if row.current_price is not None and row.shares_billion is not None:
        row.market_cap_billion_rub = row.current_price * row.shares_billion
    else:
        row.market_cap_billion_rub = None

    default_dividend_totals: dict[int, float] = {}
    cumulative_dividends = 0.0
    for year in (1, 2):
        cumulative_dividends += getattr(row, f"dividends_year{year}") or 0.0
        default_dividend_totals[year] = cumulative_dividends

    dividend_totals = _remaining_dividend_totals(
        row,
        dividend_totals_by_year_index or default_dividend_totals,
    )

    for year in (1, 2, 3, 4):
        profit = getattr(row, f"forecast_profit_year{year}_billion_rub")
        price_field = f"forecast_price_year{year}"
        upside_field = f"upside_percent_year{year}"

        if (
            profit is not None
            and row.pe_avg_5y is not None
            and row.shares_billion is not None
            and row.shares_billion > 0
        ):
            forecast_price = profit * row.pe_avg_5y / row.shares_billion
            setattr(row, price_field, forecast_price)
        else:
            setattr(row, price_field, None)
            forecast_price = None

        if (
            forecast_price is not None
            and row.current_price is not None
            and row.current_price > 0
        ):
            dividends_for_upside = dividend_totals.get(year, 0.0)
            upside = ((forecast_price - row.current_price + dividends_for_upside) / row.current_price) * 100
            setattr(row, upside_field, upside)
        else:
            setattr(row, upside_field, None)
