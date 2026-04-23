from .models import StockRow


def recalculate_fields(row: StockRow) -> None:
    if row.current_price is not None and row.shares_billion is not None:
        row.market_cap_billion_rub = row.current_price * row.shares_billion
    else:
        row.market_cap_billion_rub = None

    for year in (1, 2, 3, 4):
        profit = getattr(row, f"forecast_profit_year{year}_billion_rub")
        dividends = getattr(row, f"dividends_year{year}", None)
        price_field = f"forecast_price_year{year}"
        upside_field = f"upside_percent_year{year}"
        potential_pe_field = f"potential_pe_year{year}"
        dividend_yield_field = f"dividend_yield_percent_year{year}"

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

        if row.current_price is not None and row.current_price > 0 and dividends is not None:
            dividend_yield = (dividends / row.current_price) * 100
            setattr(row, dividend_yield_field, dividend_yield)
        else:
            setattr(row, dividend_yield_field, None)

        if (
            forecast_price is not None
            and row.current_price is not None
            and row.current_price > 0
        ):
            upside = ((forecast_price - row.current_price) / row.current_price) * 100
            dividend_yield = getattr(row, dividend_yield_field, None)
            if dividend_yield is not None:
                upside += dividend_yield
            setattr(row, upside_field, upside)
        else:
            setattr(row, upside_field, None)

        if (
            row.market_cap_billion_rub is not None
            and profit is not None
            and profit > 0
        ):
            setattr(row, potential_pe_field, row.market_cap_billion_rub / profit)
        else:
            setattr(row, potential_pe_field, None)
