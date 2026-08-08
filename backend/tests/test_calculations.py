from app.calculations import recalculate_fields
from app.models import StockRow


def test_recalculate_all_fields() -> None:
    row = StockRow(
        ticker="SBER",
        current_price=250.0,
        shares_billion=21.5,
        pe_avg_5y=6.0,
        forecast_profit_year1_billion_rub=1600.0,
        forecast_profit_year2_billion_rub=1700.0,
        forecast_profit_year3_billion_rub=1800.0,
        dividends_year1=25.0,
        dividends_year2=30.0,
    )

    recalculate_fields(row)

    assert row.market_cap_billion_rub == 5375.0
    assert round(row.forecast_price_year1 or 0, 2) == round((1600.0 * 6.0 / 21.5), 2)
    assert round(row.forecast_price_year2 or 0, 2) == round((1700.0 * 6.0 / 21.5), 2)
    assert round(row.forecast_price_year3 or 0, 2) == round((1800.0 * 6.0 / 21.5), 2)
    assert round(row.upside_percent_year1 or 0, 2) == round(
        (((row.forecast_price_year1 or 0) - 250.0 + 25.0) / 250.0) * 100, 2
    )
    assert round(row.upside_percent_year2 or 0, 2) == round(
        (((row.forecast_price_year2 or 0) - 250.0 + 25.0 + 30.0) / 250.0) * 100, 2
    )
    assert round(row.upside_percent_year3 or 0, 2) == round((((row.forecast_price_year3 or 0) - 250.0) / 250.0) * 100, 2)


def test_recalculate_handles_missing_values() -> None:
    row = StockRow(ticker="GAZP")

    recalculate_fields(row)

    assert row.market_cap_billion_rub is None
    assert row.forecast_price_year1 is None
    assert row.forecast_price_year2 is None
    assert row.forecast_price_year3 is None
    assert row.upside_percent_year1 is None
    assert row.upside_percent_year2 is None
    assert row.upside_percent_year3 is None


def test_second_year_upside_includes_dividends_from_both_forecast_years() -> None:
    row = StockRow(
        ticker="SBER",
        current_price=300.0,
        shares_billion=20.0,
        pe_avg_5y=5.0,
        forecast_profit_year1_billion_rub=1_200.0,
        forecast_profit_year2_billion_rub=1_400.0,
        dividends_year1=20.0,
        dividends_year2=30.0,
    )

    recalculate_fields(row)

    assert row.forecast_price_year1 == 300.0
    assert row.forecast_price_year2 == 350.0
    assert round(row.upside_percent_year1 or 0, 2) == round((20.0 / 300.0) * 100, 2)
    assert round(row.upside_percent_year2 or 0, 2) == round(((350.0 - 300.0 + 20.0 + 30.0) / 300.0) * 100, 2)
