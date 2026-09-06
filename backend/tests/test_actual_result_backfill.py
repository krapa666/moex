from datetime import datetime, timezone

from app.actual_result_backfill import (
    evaluate_actual_result_backfill,
    parse_actual_result_csv,
)
from app.application import app
from app.database import Base
from app.forecast_accuracy import ActualNetProfit
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def test_actual_result_backfill_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/analytics/actual-net-profits/backfill/preview" in paths
    assert "/api/analytics/actual-net-profits/backfill" in paths


def test_parser_accepts_utf8_semicolon_csv_and_decimal_comma() -> None:
    content = (
        "ticker;fiscal_year;net_profit_billion_rub;source_name;source_url;reported_at;source_comment\n"
        'SBER;2025;1580,25;Issuer IFRS;https://example.test/sber;2026-02-27;owner profit\n'
    ).encode("utf-8-sig")

    candidates, issues = parse_actual_result_csv(
        content,
        now=datetime(2026, 9, 6, tzinfo=timezone.utc),
    )

    assert issues == []
    assert len(candidates) == 1
    row = candidates[0]
    assert row.ticker == "SBER"
    assert row.fiscal_year == 2025
    assert row.net_profit_billion_rub == 1580.25
    assert row.source_url == "https://example.test/sber"
    assert row.reported_at == datetime(2026, 2, 27, tzinfo=timezone.utc)


def test_parser_rejects_incomplete_year_missing_provenance_and_duplicates() -> None:
    content = (
        "ticker,fiscal_year,net_profit_billion_rub,source_name,source_url,reported_at\n"
        "SBER,2026,1500,Issuer,https://example.test/sber,2026-03-01\n"
        "GAZP,2025,1000,Issuer,,2026-02-01\n"
        "LKOH,2025,900,Issuer,https://example.test/lkoh,2026-02-01\n"
        "LKOH,2025,901,Issuer,https://example.test/lkoh2,2026-02-02\n"
    ).encode()

    candidates, issues = parse_actual_result_csv(
        content,
        now=datetime(2026, 9, 6, tzinfo=timezone.utc),
    )

    assert [(row.ticker, row.fiscal_year) for row in candidates] == [("LKOH", 2025)]
    messages = [issue.message for issue in issues]
    assert any("completed years only" in message for message in messages)
    assert any("source_url is required" in message for message in messages)
    assert any("duplicate ticker + fiscal_year" in message for message in messages)


def test_preview_never_overwrites_existing_canonical_fact() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    content = (
        "ticker,fiscal_year,net_profit_billion_rub,source_name,source_url,reported_at\n"
        "SBER,2025,1600,New source,https://example.test/new,2026-02-27\n"
        "GAZP,2025,1000,Issuer,https://example.test/gazp,2026-03-01\n"
    ).encode()
    candidates, issues = parse_actual_result_csv(
        content,
        now=datetime(2026, 9, 6, tzinfo=timezone.utc),
    )

    with Session(engine) as db:
        db.add(
            ActualNetProfit(
                ticker="SBER",
                fiscal_year=2025,
                source_key="manual",
                net_profit_billion_rub=1580.0,
                source_name="Existing source",
                source_url="https://example.test/existing",
                reported_at=datetime(2026, 2, 26, tzinfo=timezone.utc),
            )
        )
        db.commit()

        result = evaluate_actual_result_backfill(db, candidates, issues, apply=False)
        rows = list(db.scalars(select(ActualNetProfit)).all())

    assert result["applied"] is False
    assert result["create_rows"] == 1
    assert result["protected_rows"] == 1
    assert result["created_rows"] == 0
    assert len(rows) == 1
    actions = {(item["ticker"], item["action"]) for item in result["items"]}
    assert ("SBER", "protected") in actions
    assert ("GAZP", "create") in actions


def test_apply_creates_only_missing_rows_and_marks_them_manual() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    content = (
        "ticker,fiscal_year,net_profit_billion_rub,source_name,source_url,reported_at\n"
        "GAZP,2025,1000,Issuer IFRS,https://example.test/gazp,2026-03-01\n"
    ).encode()
    candidates, issues = parse_actual_result_csv(
        content,
        now=datetime(2026, 9, 6, tzinfo=timezone.utc),
    )

    with Session(engine) as db:
        result = evaluate_actual_result_backfill(db, candidates, issues, apply=True)
        row = db.scalars(select(ActualNetProfit)).one()

    assert result["applied"] is True
    assert result["created_rows"] == 1
    assert row.ticker == "GAZP"
    assert row.fiscal_year == 2025
    assert row.source_key == "manual"
    assert row.net_profit_billion_rub == 1000.0


def test_apply_is_all_or_nothing_when_csv_has_invalid_rows() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    content = (
        "ticker,fiscal_year,net_profit_billion_rub,source_name,source_url,reported_at\n"
        "GAZP,2025,1000,Issuer,https://example.test/gazp,2026-03-01\n"
        "SBER,2025,1580,Issuer,,2026-02-27\n"
    ).encode()
    candidates, issues = parse_actual_result_csv(
        content,
        now=datetime(2026, 9, 6, tzinfo=timezone.utc),
    )

    with Session(engine) as db:
        result = evaluate_actual_result_backfill(db, candidates, issues, apply=True)
        rows = list(db.scalars(select(ActualNetProfit)).all())

    assert result["applied"] is False
    assert result["invalid_rows"] == 1
    assert result["created_rows"] == 0
    assert rows == []
