from app import finvista_source

RUBLE_HTML = """
<html><body>
<p>Денежные суммы указаны в млрд рублей, цена, дивиденд на акцию и EPS — в рублях.</p>
<table>
  <tr>
    <th>Показатель</th><th>2024</th><th>2025</th><th>2026 прогноз</th><th>2027 прогноз</th>
  </tr>
  <tr>
    <td>Дивиденд на акцию<br>Дивидендная доходность</td>
    <td>34,8 12,73%</td><td>37,6 12,55%</td><td>40,6 14,46%</td><td>41,6 12,50%</td>
  </tr>
</table>
<table>
  <tr>
    <th>Показатель</th><th>2024</th><th>2025</th><th>2026 прогноз</th><th>2027 прогноз</th>
  </tr>
  <tr>
    <td>Чистая прибыль<br>Чистая прибыль / Выручка</td>
    <td>1 580,3 0,37</td><td>1 705,9 0,35</td><td>1 836,23 0,33</td><td>1 877 0,30</td>
  </tr>
</table>
<table>
  <tr><th>Показатель</th><th>2025</th><th>2026*</th><th>2027*</th></tr>
  <tr><td>Чистая прибыль</td><td>1 705,9</td><td>9 999</td><td>9 999</td></tr>
</table>
</body></html>
"""

KOPECK_HTML = """
<html><body>
<p>Денежные суммы указаны в млрд рублей, цена, дивиденд на акцию и EPS — в копейках.</p>
<table>
  <tr><th>Показатель</th><th>2025</th><th>2026 прогноз</th><th>2027 прогноз</th></tr>
  <tr><td>Дивиденд на акцию Дивидендная доходность</td><td>0</td><td>0,113 0,98%</td><td>0,203 1,56%</td></tr>
</table>
<table>
  <tr><th>Показатель</th><th>2025</th><th>2026 прогноз</th><th>2027 прогноз</th></tr>
  <tr><td>Чистая прибыль Чистая прибыль / Выручка</td><td>-2,27 -0,06</td><td>2,12 0,05</td><td>3,8 0,08</td></tr>
</table>
</body></html>
"""

NEGATIVE_PROFIT_HTML = """
<html><body>
<p>Денежные суммы указаны в млрд рублей, цена, дивиденд на акцию и EPS — в рублях.</p>
<table>
  <tr><th>Показатель</th><th>2026 прогноз</th><th>2027 прогноз</th></tr>
  <tr><td>Чистая прибыль Чистая прибыль / Выручка</td><td>-7,92 -0,05</td><td>4 0,02</td></tr>
</table>
</body></html>
"""


def assert_raises(exc_type, message: str, callback) -> None:
    try:
        callback()
    except exc_type as exc:
        assert message in str(exc)
    else:
        raise AssertionError(f"expected {exc_type.__name__}")


def test_parse_finvista_calendar_profit_and_dividends() -> None:
    forecast = finvista_source.parse_finvista_prospect_html("SBER", "SBER", RUBLE_HTML)

    assert forecast.ticker == "SBER"
    assert forecast.net_profit_billion_rub == {"2026": 1836.23, "2027": 1877.0}
    assert forecast.dividends_per_share_rub == {"2026": 40.6, "2027": 41.6}


def test_parse_finvista_ignores_nonforecast_star_columns() -> None:
    forecast = finvista_source.parse_finvista_prospect_html("SBER", "SBER", RUBLE_HTML)

    assert forecast.net_profit_billion_rub["2026"] != 9999
    assert forecast.net_profit_billion_rub["2027"] != 9999


def test_parse_finvista_converts_kopeck_dividends_to_rubles() -> None:
    forecast = finvista_source.parse_finvista_prospect_html("ELMT", "ELMT", KOPECK_HTML)

    assert forecast.net_profit_billion_rub == {"2026": 2.12, "2027": 3.8}
    assert forecast.dividends_per_share_rub == {"2026": 0.00113, "2027": 0.00203}


def test_parse_finvista_supports_negative_profit_and_missing_dividends() -> None:
    forecast = finvista_source.parse_finvista_prospect_html(
        "ETLN",
        "ETLN",
        NEGATIVE_PROFIT_HTML,
    )

    assert forecast.net_profit_billion_rub == {"2026": -7.92, "2027": 4.0}
    assert forecast.dividends_per_share_rub == {}


def test_parse_finvista_fails_closed_without_billion_ruble_unit() -> None:
    assert_raises(
        finvista_source.FinVistaParseError,
        "единицы измерения финансовых показателей",
        lambda: finvista_source.parse_finvista_prospect_html(
            "SBER",
            "SBER",
            RUBLE_HTML.replace("Денежные суммы указаны в млрд рублей", "Суммы неизвестны"),
        ),
    )


def test_parse_finvista_requires_calendar_profit_forecast() -> None:
    assert_raises(
        finvista_source.FinVistaParseError,
        "чистая прибыль",
        lambda: finvista_source.parse_finvista_prospect_html(
            "SBER",
            "SBER",
            "<p>Денежные суммы указаны в млрд рублей</p><table><tr><th>2026 прогноз</th></tr></table>",
        ),
    )


def test_finvista_alias_config_validation() -> None:
    assert finvista_source.load_finvista_aliases('{"TCSG":"T","SBER":"SBER"}') == {
        "TCSG": "T",
        "SBER": "SBER",
    }

    assert_raises(ValueError, "JSON object", lambda: finvista_source.load_finvista_aliases("[]"))
    assert_raises(
        ValueError,
        "invalid fin-vista slug",
        lambda: finvista_source.load_finvista_aliases('{"SBER":"../bad"}'),
    )
