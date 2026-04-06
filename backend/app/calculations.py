from .models import StockRow


def recalculate_fields(row: StockRow) -> None:
    if row.current_price is not None and row.shares_billion is not None:
        row.market_cap_billion_rub = row.current_price * row.shares_billion
    else:
        row.market_cap_billion_rub = None

    for year in (1, 2, 3):
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
            upside = ((forecast_price - row.current_price) / row.current_price) * 100
            setattr(row, upside_field, upside)
        else:
            setattr(row, upside_field, None)
