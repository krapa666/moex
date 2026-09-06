import asyncio

import pytest
from app import forecast_source_runs, forecast_source_sync
from app.forecast_source_runs import ForecastSourceRun
from app.forecast_source_sync import sync_forecast_source_once
from app.models import AnalystTable, Base, StockRow
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def _prepare_engine(tmp_path, tickers: list[str]):
    engine = create_engine(f"sqlite:///{tmp_path / 'source-runs.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        table = AnalystTable(
            analyst_name="Источник",
            year_offset=0,
            forecast_start_year=2099,
            sort_order=1,
        )
        db.add(table)
        db.commit()
        db.refresh(table)
        db.add_all(StockRow(table_id=table.id, ticker=ticker) for ticker in tickers)
        db.commit()
    return engine


def _patch_sessions(monkeypatch, engine) -> None:
    factory = lambda: Session(engine)  # noqa: E731
    monkeypatch.setattr(forecast_source_sync, "SessionLocal", factory)
    monkeypatch.setattr(forecast_source_runs, "SessionLocal", factory)


class Forecast:
    net_profit_billion_rub = {"2099": 100.0}
    dividends_per_share_rub = {"2099": 10.0}


class SuccessClient:
    async def fetch_catalog_mapping(self, tickers):
        return {ticker: ticker.lower() for ticker in tickers}, {}

    async def fetch_forecast(self, ticker, source_ref):
        return Forecast()


class PartialClient:
    async def fetch_catalog_mapping(self, tickers):
        return {"SBER": "sber"}, {"LKOH": "нет данных"}

    async def fetch_forecast(self, ticker, source_ref):
        return Forecast()


class FailedClient:
    async def fetch_catalog_mapping(self, tickers):
        raise RuntimeError("source unavailable")

    async def fetch_forecast(self, ticker, source_ref):
        return Forecast()


def _sync(client):
    return asyncio.run(
        sync_forecast_source_once(
            analyst_name="Источник",
            source_comment="Тестовый источник",
            changed_by="test-sync",
            client=client,
            source_key="test-source",
        )
    )


def test_successful_source_sync_is_persisted(tmp_path, monkeypatch) -> None:
    engine = _prepare_engine(tmp_path, ["SBER"])
    _patch_sessions(monkeypatch, engine)

    result = _sync(SuccessClient())

    assert result.tickers_updated == 1
    with Session(engine) as db:
        run = db.scalars(select(ForecastSourceRun)).one()
        assert run.source_key == "test-source"
        assert run.analyst_name == "Источник"
        assert run.status == "success"
        assert run.finished_at is not None
        assert run.tickers_total == 1
        assert run.tickers_mapped == 1
        assert run.tickers_updated == 1
        assert run.tickers_skipped == 0
        assert run.error_details is None
        assert run.error_message is None


def test_partial_source_sync_keeps_ticker_errors(tmp_path, monkeypatch) -> None:
    engine = _prepare_engine(tmp_path, ["SBER", "LKOH"])
    _patch_sessions(monkeypatch, engine)

    result = _sync(PartialClient())

    assert result.tickers_updated == 1
    assert result.errors == {"LKOH": "нет данных"}
    with Session(engine) as db:
        run = db.scalars(select(ForecastSourceRun)).one()
        assert run.status == "partial"
        assert run.tickers_total == 2
        assert run.tickers_mapped == 1
        assert run.tickers_skipped == 1
        assert run.error_details == {"LKOH": "нет данных"}


def test_source_exception_is_persisted_and_reraised(tmp_path, monkeypatch) -> None:
    engine = _prepare_engine(tmp_path, ["SBER"])
    _patch_sessions(monkeypatch, engine)

    with pytest.raises(RuntimeError, match="source unavailable"):
        _sync(FailedClient())

    with Session(engine) as db:
        run = db.scalars(select(ForecastSourceRun)).one()
        assert run.status == "failed"
        assert run.finished_at is not None
        assert run.error_message == "source unavailable"
