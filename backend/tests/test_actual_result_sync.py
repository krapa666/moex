from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from app import actual_result_sync
from app.forecast_accuracy import ActualNetProfit
from app.models import AnalystTable, Base, StockRow
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Record:
    ticker: str
    fiscal_year: int
    net_profit_billion_rub: float
    source_name: str = "MOEX CCI · МСФО"
    source_url: str | None = "https://iss.moex.com/example"
    source_comment: str | None = "Краткое МСФО"
    reported_at: datetime | None = datetime(2026, 3, 1, tzinfo=timezone.utc)


class Client:
    def __init__(self, records: list[Record]) -> None:
        self.records = records

    async def fetch_actuals(self, tickers, *, min_fiscal_year):
        assert set(tickers) == {"LKOH", "SBER"}
        assert min_fiscal_year <= 2025
        return self.records, {}


def _prepare_db(monkeypatch) -> object:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        table = AnalystTable(
            analyst_name="Основной",
            year_offset=0,
            forecast_start_year=2026,
            sort_order=1,
        )
        db.add(table)
        db.flush()
        db.add_all(
            [
                StockRow(table_id=table.id, ticker="SBER"),
                StockRow(table_id=table.id, ticker="LKOH"),
            ]
        )
        db.commit()

    monkeypatch.setattr(actual_result_sync, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(
        actual_result_sync,
        "get_primary_table",
        lambda db: db.scalars(select(AnalystTable).order_by(AnalystTable.id.asc())).first(),
    )
    return engine


@pytest.mark.asyncio
async def test_sync_creates_auto_fact_but_protects_manual_fact(monkeypatch) -> None:
    engine = _prepare_db(monkeypatch)
    with Session(engine) as db:
        db.add(
            ActualNetProfit(
                ticker="SBER",
                fiscal_year=2025,
                source_key="manual",
                net_profit_billion_rub=1600.0,
                source_name="Проверенный вручную отчёт",
            )
        )
        db.commit()

    result = await actual_result_sync.sync_actual_profit_source_once(
        source_key="moex-cci",
        client=Client([Record("SBER", 2025, 1700.0), Record("LKOH", 2025, 800.0)]),
        years_back=5,
    )

    assert result.records_created == 1
    assert result.records_protected == 1
    with Session(engine) as db:
        sber = db.scalars(
            select(ActualNetProfit).where(
                ActualNetProfit.ticker == "SBER",
                ActualNetProfit.fiscal_year == 2025,
            )
        ).one()
        lkoh = db.scalars(
            select(ActualNetProfit).where(
                ActualNetProfit.ticker == "LKOH",
                ActualNetProfit.fiscal_year == 2025,
            )
        ).one()
        assert sber.net_profit_billion_rub == 1600.0
        assert sber.source_key == "manual"
        assert lkoh.net_profit_billion_rub == 800.0
        assert lkoh.source_key == "moex-cci"


@pytest.mark.asyncio
async def test_sync_updates_record_owned_by_same_source(monkeypatch) -> None:
    engine = _prepare_db(monkeypatch)
    with Session(engine) as db:
        db.add(
            ActualNetProfit(
                ticker="LKOH",
                fiscal_year=2025,
                source_key="moex-cci",
                net_profit_billion_rub=800.0,
                source_name="MOEX CCI · МСФО",
            )
        )
        db.commit()

    result = await actual_result_sync.sync_actual_profit_source_once(
        source_key="moex-cci",
        client=Client([Record("LKOH", 2025, 825.5)]),
        years_back=5,
    )

    assert result.records_updated == 1
    assert result.records_protected == 0
    with Session(engine) as db:
        row = db.scalars(select(ActualNetProfit).where(ActualNetProfit.ticker == "LKOH")).one()
        assert row.net_profit_billion_rub == 825.5
        assert row.source_key == "moex-cci"
