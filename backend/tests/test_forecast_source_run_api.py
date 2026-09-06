from datetime import datetime, timedelta, timezone

from app.application import app
from app.forecast_api import list_forecast_source_runs
from app.forecast_source_runs import ForecastSourceRun
from app.models import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def make_run(
    *,
    source_key: str,
    analyst_name: str,
    status: str,
    started_at: datetime,
) -> ForecastSourceRun:
    return ForecastSourceRun(
        source_key=source_key,
        analyst_name=analyst_name,
        started_at=started_at,
        finished_at=started_at + timedelta(seconds=1),
        status=status,
        tables=1,
        tickers_total=10,
        tickers_mapped=9,
        tickers_updated=2,
        tickers_unchanged=7,
        tickers_skipped=1,
        table_created=False,
    )


def test_application_registers_source_runs_route() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/analytics/source-runs" in paths


def test_source_runs_api_filters_and_returns_newest_first() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)

    with Session(engine) as db:
        db.add_all(
            [
                make_run(
                    source_key="arsagera",
                    analyst_name="Арсагера",
                    status="success",
                    started_at=now - timedelta(hours=3),
                ),
                make_run(
                    source_key="arsagera",
                    analyst_name="Арсагера",
                    status="partial",
                    started_at=now - timedelta(hours=1),
                ),
                make_run(
                    source_key="dohod",
                    analyst_name="ДОХОДЪ",
                    status="partial",
                    started_at=now,
                ),
            ]
        )
        db.commit()

        runs = list_forecast_source_runs(
            source_key="arsagera",
            analyst_name=None,
            status=None,
            since=now - timedelta(hours=4),
            limit=10,
            db=db,
        )

        assert len(runs) == 2
        assert runs[0].status == "partial"
        assert runs[1].status == "success"
        assert runs[0].started_at > runs[1].started_at
