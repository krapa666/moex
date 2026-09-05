import pytest
from app.arsagera_source import parse_catalog_gids, parse_forecast_csv


def test_catalog_maps_existing_tickers_to_sheet_gid() -> None:
    html = """
    <script>
    var items = [];
    items.push({name: "Каталог", pageUrl: "...gid=790995554", gid: "790995554",initialSheet: true});
    items.push({name: "SBER", pageUrl: "...gid=12345", gid: "12345"});
    items.push({name: "SBERP", pageUrl: "...gid=12346", gid: "12346"});
    items.push({name: "LKOH", pageUrl: "...gid=67890", gid: "67890"});
    </script>
    """

    mapping, errors = parse_catalog_gids(html, ["SBER", "SBERP", "LKOH", "GAZP"])

    assert mapping == {"LKOH": "67890", "SBER": "12345", "SBERP": "12346"}
    assert errors == {"GAZP": "тикер не найден среди листов Арсагеры"}


def test_catalog_keeps_legacy_explicit_link_fallback() -> None:
    html = """
    <table>
      <tr><td>Лукойл</td><td>LKOH</td>
          <td><a href="/spreadsheets/d/e/example/pubhtml?gid=67890&single=true">Расчёт</a></td></tr>
    </table>
    """

    mapping, errors = parse_catalog_gids(html, ["LKOH"])

    assert mapping == {"LKOH": "67890"}
    assert errors == {}


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


def test_forecast_parser_uses_latest_revision_block_only() -> None:
    content = """2 квартал 2026,,,,,
\"Прогноз финансовых показателей, тыс. руб.\",,2026П,2027П,2028П,2029П
Чистая прибыль,,1986448090,2157251823,2403912346,2704642949
\"Дивиденд на акцию ао, руб.\",,43.76,47.52,52.95,59.58
1 квартал 2026,,,,,
\"Прогноз финансовых показателей, тыс. руб.\",,2026П,2027П,2028П,2029П
Чистая прибыль,,1800000000,1900000000,2000000000,2100000000
\"Дивиденд на акцию ао, руб.\",,40,42,44,46
"""

    forecast = parse_forecast_csv("SBER", "12345", content)

    assert forecast.net_profit_billion_rub == pytest.approx(
        {
            "2026": 1986.44809,
            "2027": 2157.251823,
            "2028": 2403.912346,
            "2029": 2704.642949,
        }
    )
    assert forecast.dividends_per_share_rub == pytest.approx(
        {
            "2026": 43.76,
            "2027": 47.52,
            "2028": 52.95,
            "2029": 59.58,
        }
    )
