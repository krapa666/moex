from datetime import datetime, timedelta, timezone

from app.application import app
from app.forecast_api import list_forecast_revisions
from app.models import Base, ForecastRevision
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def make_revision(
    *,
    table_id: int,
    ticker: str,
    created_at: datetime,
    analyst_name: str = "Аналитик",
) -> ForecastRevision:
    return ForecastRevision(
        table_id=table_id,
        ticker=ticker,
        analyst_name=analyst_name,
        forecast_start_year=2026,
        event_type="updated",
        created_at=created_at,
    )


def test_application_registers_forecast_revision_route() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/analytics/forecast-revisions" in paths


def test_forecast_revision_api_filters_and_returns_newest_first() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)

    with Session(engine) as db:
        db.add_all(
            [
                make_revision(table_id=1, ticker="SBER", created_at=now - timedelta(days=2)),
                make_revision(table_id=1, ticker="SBER", created_at=now - timedelta(hours=2)),
                make_revision(table_id=2, ticker="SBER", created_at=now - timedelta(hours=1)),
                make_revision(table_id=1, ticker="LKOH", created_at=now),
            ]
        )
        db.commit()

        revisions = list_forecast_revisions(
            ticker="sber",
            table_id=1,
            since=now - timedelta(days=1),
            limit=10,
            db=db,
        )

        assert len(revisions) == 1
        assert revisions[0].ticker == "SBER"
        assert revisions[0].table_id == 1
        assert revisions[0].created_at.replace(tzinfo=timezone.utc) == (now - timedelta(hours=2)).replace(
            microsecond=revisions[0].created_at.microsecond
        )


def test_forecast_revision_api_applies_limit_after_descending_order() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)

    with Session(engine) as db:
        db.add_all(
            [
                make_revision(table_id=1, ticker="SBER", created_at=now - timedelta(hours=3)),
                make_revision(table_id=1, ticker="SBER", created_at=now - timedelta(hours=2)),
                make_revision(table_id=1, ticker="SBER", created_at=now - timedelta(hours=1)),
            ]
        )
        db.commit()

        revisions = list_forecast_revisions(
            ticker="SBER",
            table_id=None,
            since=None,
            limit=2,
            db=db,
        )

        assert len(revisions) == 2
        assert revisions[0].created_at > revisions[1].created_at
