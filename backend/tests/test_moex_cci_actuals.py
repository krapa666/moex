from datetime import datetime, timezone

import pytest

from app.moex_cci_actuals import (
    _annual_fiscal_year,
    _owner_profit_value,
    _scale_to_billion,
    _select_annual_reports,
)


def _detail_payload(*rows: list[object]) -> dict:
    return {
        "cci_report_values": {
            "columns": ["parameter_trek_id", "parameter_name_short_ru", "value"],
            "data": list(rows),
        }
    }


def test_owner_profit_parser_prefers_profit_attributable_to_owners() -> None:
    payload = _detail_payload(
        [1147, "Чистая прибыль после налогооблажения", 8253],
        [1148, "Чистая прибыль собственников", 8062],
        [1227, "Неконтролирующие доли участия в чистой прибыли", 191],
    )

    value, name = _owner_profit_value(payload)

    assert value == 8062
    assert name == "Чистая прибыль собственников"


def test_owner_profit_parser_fails_closed_without_owner_field() -> None:
    payload = _detail_payload([1147, "Чистая прибыль после налогообложения", 8253])

    with pytest.raises(ValueError, match="expected one owner-attributable"):
        _owner_profit_value(payload)


def test_owner_profit_parser_fails_closed_on_ambiguous_owner_fields() -> None:
    payload = _detail_payload(
        [1, "Чистая прибыль собственников", 100],
        [2, "Чистая прибыль акционеров", 100],
    )

    with pytest.raises(ValueError, match="got 2"):
        _owner_profit_value(payload)


def test_annual_period_and_scale_conversion() -> None:
    assert _annual_fiscal_year("2025Y4Q") == 2025
    assert _annual_fiscal_year("2025Y3Q") is None
    assert _scale_to_billion("Миллиарды единиц") == 1.0
    assert _scale_to_billion("Миллионы единиц") == 0.001
    assert _scale_to_billion("Тысячи единиц") == 0.000001


def test_select_annual_reports_uses_latest_publication_for_restatement() -> None:
    rows = [
        {
            "basis_type_report_id": 10,
            "period_code": "2024Y4Q",
            "scale_name_short_ru": "Миллионы единиц",
            "currency_name_short_ru": "руб.",
            "report_publicate_date": "2025-03-01 10:00:00",
        },
        {
            "basis_type_report_id": 11,
            "period_code": "2024Y4Q",
            "scale_name_short_ru": "Миллионы единиц",
            "currency_name_short_ru": "руб.",
            "report_publicate_date": "2025-05-01 10:00:00",
        },
        {
            "basis_type_report_id": 12,
            "period_code": "2024Y3Q",
            "scale_name_short_ru": "Миллионы единиц",
            "currency_name_short_ru": "руб.",
            "report_publicate_date": "2024-11-01 10:00:00",
        },
    ]

    selected = _select_annual_reports(rows, min_fiscal_year=2024, current_year=2025)

    assert list(selected) == [2024]
    assert selected[2024]["basis_type_report_id"] == 11


def test_select_annual_reports_rejects_non_rub_currency() -> None:
    rows = [
        {
            "basis_type_report_id": 10,
            "period_code": "2024Y4Q",
            "scale_name_short_ru": "Миллионы единиц",
            "currency_name_short_ru": "USD",
            "report_publicate_date": datetime(2025, 3, 1, tzinfo=timezone.utc).isoformat(),
        }
    ]

    with pytest.raises(ValueError, match="not RUB"):
        _select_annual_reports(rows, min_fiscal_year=2024, current_year=2025)
