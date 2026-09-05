from app.arsagera_source import parse_catalog_gids, parse_forecast_csv


def test_catalog_maps_existing_tickers_to_sheet_gid() -> None:
    html = """
    <table>
      <tr><td>Сбербанк</td><td>SBER, SBERP</td>
          <td><a href="/spreadsheets/d/e/example/pubhtml?gid=12345&single=true">Расчёт</a></td></tr>
      <tr><td>Лукойл</td><td>LKOH</td>
          <td><a href="/spreadsheets/d/e/example/pubhtml?gid=67890&single=true">Расчёт</a></td></tr>
    </table>
    """

    mapping, errors = parse_catalog_gids(html, ["SBER", "SBERP", "LKOH", "GAZP"])

    assert mapping == {"LKOH": "67890", "SBER": "12345", "SBERP": "12345"}
    assert errors == {"GAZP": "тикер не найден в каталоге Арсагеры"}


def test_forecast_parser_extracts_profit_in_billions_and_full_year_dividends() -> None:
    content = """Показатель,2025,2026,2027,2028
\"Чистая прибыль, млн руб.\",1000000,1200000,1350000,1500000
\"Дивиденды, руб./акц.\",25.5,31.2,36.4,40
"""

    forecast = parse_forecast_csv("SBER", "12345", content)

    assert forecast.net_profit_billion_rub == {
        "2025": 1000.0,
        "2026": 1200.0,
        "2027": 1350.0,
        "2028": 1500.0,
    }
    assert forecast.dividends_per_share_rub == {
        "2025": 25.5,
        "2026": 31.2,
        "2027": 36.4,
        "2028": 40.0,
    }


def test_forecast_parser_prefers_ticker_specific_dividend_row() -> None:
    content = """Показатель,2026,2027
\"Чистая прибыль, млрд руб.\",1800,1950
\"Дивиденды SBER, руб./акц.\",40,44
\"Дивиденды SBERP, руб./акц.\",41,45
"""

    forecast = parse_forecast_csv("SBERP", "12345", content)

    assert forecast.dividends_per_share_rub == {"2026": 41.0, "2027": 45.0}
