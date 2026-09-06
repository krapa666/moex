from app import dohod_source


CATALOG_HTML = """
<html><body>
<a href="/ik/analytics/dividend/sber">Сбербанк-ао</a>
<a href="https://www.dohod.ru/ik/analytics/dividend/sberp">Сбербанк-п</a>
<a href="/ik/analytics/dividend/moex?from=list">Московская биржа</a>
</body></html>
"""


DIVIDEND_HTML = """
<html><body>
<table>
  <tr><th>Год</th><th>Дивиденд (руб.)</th><th>Изм. к пред. году</th></tr>
  <tr><td>2026</td><td>37.64</td><td>-</td></tr>
</table>
<table>
  <tr>
    <th>Дата объявления дивиденда</th>
    <th>Дата закрытия реестра</th>
    <th>Год для учета дивиденда</th>
    <th>Дивиденд</th>
  </tr>
  <tr><td>21.04.2026</td><td>20.07.2026</td><td>2026</td><td>37.64</td></tr>
  <tr><td>n/a</td><td>20.07.2027 (прогноз)</td><td>n/a</td><td>44,53</td></tr>
  <tr><td>22.04.2025</td><td>18.07.2025</td><td>2025</td><td>34.84</td></tr>
</table>
</body></html>
"""


MULTI_PAYMENT_HTML = """
<table>
  <tr>
    <th>Дата объявления дивиденда</th>
    <th>Дата закрытия реестра</th>
    <th>Год для учета дивиденда</th>
    <th>Дивиденд</th>
  </tr>
  <tr><td>13.03.2026</td><td>27.04.2026</td><td>2026</td><td>110</td></tr>
  <tr><td>n/a</td><td>21.09.2026 (прогноз)</td><td>n/a</td><td>110</td></tr>
  <tr><td>n/a</td><td>27.04.2027 (прогноз)</td><td>n/a</td><td>110</td></tr>
</table>
"""


def assert_raises(exc_type, message: str, callback) -> None:
    try:
        callback()
    except exc_type as exc:
        assert message in str(exc)
    else:
        raise AssertionError(f"expected {exc_type.__name__}")


def test_catalog_maps_tickers_to_dohod_slugs() -> None:
    found, errors = dohod_source.parse_dohod_catalog_slugs(
        CATALOG_HTML,
        ["SBER", "SBERP", "MOEX", "UNKNOWN"],
    )

    assert found == {"MOEX": "moex", "SBER": "sber", "SBERP": "sberp"}
    assert errors == {"UNKNOWN": "тикер не найден в каталоге дивидендов ДОХОДЪ"}


def test_catalog_supports_explicit_slug_aliases() -> None:
    found, errors = dohod_source.parse_dohod_catalog_slugs(
        CATALOG_HTML,
        ["MOEXOLD"],
        aliases={"MOEXOLD": "moex"},
    )

    assert found == {"MOEXOLD": "moex"}
    assert errors == {}


def test_parse_dohod_builds_full_calendar_year_dividend_map() -> None:
    forecast = dohod_source.parse_dohod_dividend_html(
        "SBER",
        "sber",
        DIVIDEND_HTML,
        current_year=2026,
    )

    assert forecast.ticker == "SBER"
    assert forecast.net_profit_billion_rub == {}
    assert forecast.dividends_per_share_rub == {"2026": 37.64, "2027": 44.53}


def test_parse_dohod_sums_multiple_payments_in_same_calendar_year() -> None:
    forecast = dohod_source.parse_dohod_dividend_html(
        "YDEX",
        "ydex",
        MULTI_PAYMENT_HTML,
        current_year=2026,
    )

    assert forecast.dividends_per_share_rub == {"2026": 220.0, "2027": 110.0}


def test_parse_dohod_requires_payment_table() -> None:
    assert_raises(
        dohod_source.DohodParseError,
        "таблица выплат",
        lambda: dohod_source.parse_dohod_dividend_html(
            "SBER",
            "sber",
            "<html><body>no table</body></html>",
        ),
    )


def test_dohod_alias_config_validation() -> None:
    assert dohod_source.load_dohod_aliases('{"SBER":"sber","SNGSP":"sngsp"}') == {
        "SBER": "sber",
        "SNGSP": "sngsp",
    }

    assert_raises(ValueError, "JSON object", lambda: dohod_source.load_dohod_aliases("[]"))
    assert_raises(
        ValueError,
        "invalid DOHOD slug",
        lambda: dohod_source.load_dohod_aliases('{"SBER":"../bad"}'),
    )
