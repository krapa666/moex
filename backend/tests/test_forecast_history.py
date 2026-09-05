from app.main import apply_net_profit_projection, current_calendar_year
from app.models import AnalystTable, Base, ForecastRevision, StockRow
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


CURRENT_YEAR = current_calendar_year()


def make_table(db: Session, name: str = "Аналитик 1", sort_order: int = 1) -> AnalystTable:
    table = AnalystTable(
        analyst_name=name,
        forecast_start_year=CURRENT_YEAR,
        year_offset=0,
        sort_order=sort_order,
    )
    db.add(table)
    db.commit()
    db.refresh(table)
    return table


def test_forecast_row_insert_creates_initial_revision() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        table = make_table(db)
        row = StockRow(
            table_id=table.id,
            ticker="SBER",
            current_price=300.0,
            shares_billion=20.0,
            pe_avg_5y=5.0,
            net_profit_year_map={str(CURRENT_YEAR): 1_200.0},
            dividend_year_map={str(CURRENT_YEAR): 20.0},
            net_profit_source_comment="Первичный прогноз",
        )
        apply_net_profit_projection(row, table.forecast_start_year)
        db.add(row)
        db.commit()
        db.refresh(row)

        revisions = db.scalars(select(ForecastRevision)).all()
        assert len(revisions) == 1
        revision = revisions[0]
        assert revision.event_type == "created"
        assert revision.stock_row_id == row.id
        assert revision.table_id == table.id
        assert revision.ticker == "SBER"
        assert revision.analyst_name == "Аналитик 1"
        assert revision.forecast_start_year == CURRENT_YEAR
        assert revision.net_profit_year_map == {str(CURRENT_YEAR): 1_200.0}
        assert revision.dividend_year_map == {str(CURRENT_YEAR): 20.0}
        assert revision.forecast_price_year1 == 300.0


def test_material_forecast_change_creates_revision_with_recalculated_values() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        table = make_table(db)
        row = StockRow(
            table_id=table.id,
            ticker="SBER",
            current_price=300.0,
            shares_billion=20.0,
            pe_avg_5y=5.0,
            net_profit_year_map={str(CURRENT_YEAR): 1_200.0},
            dividend_year_map={str(CURRENT_YEAR): 20.0},
        )
        apply_net_profit_projection(row, table.forecast_start_year)
        db.add(row)
        db.commit()

        row.net_profit_year_map = {str(CURRENT_YEAR): 1_400.0}
        apply_net_profit_projection(row, table.forecast_start_year)
        db.commit()

        revisions = db.scalars(select(ForecastRevision).order_by(ForecastRevision.id.asc())).all()
        assert len(revisions) == 2
        assert revisions[1].event_type == "updated"
        assert revisions[1].net_profit_year_map == {str(CURRENT_YEAR): 1_400.0}
        assert revisions[1].forecast_price_year1 == 350.0
        assert round(revisions[1].upside_percent_year1 or 0.0, 2) == round(
            ((350.0 - 300.0 + 20.0) / 300.0) * 100,
            2,
        )


def test_market_price_only_update_does_not_create_forecast_revision() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        table = make_table(db)
        row = StockRow(
            table_id=table.id,
            ticker="SBER",
            current_price=300.0,
            shares_billion=20.0,
            pe_avg_5y=5.0,
            net_profit_year_map={str(CURRENT_YEAR): 1_200.0},
        )
        apply_net_profit_projection(row, table.forecast_start_year)
        db.add(row)
        db.commit()

        row.current_price = 310.0
        apply_net_profit_projection(row, table.forecast_start_year)
        db.commit()

        revisions = db.scalars(select(ForecastRevision)).all()
        assert len(revisions) == 1
        assert revisions[0].event_type == "created"


def test_blank_synced_row_does_not_create_history_noise() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        table = make_table(db, name="Аналитик 2", sort_order=2)
        row = StockRow(
            table_id=table.id,
            ticker="SBER",
            shares_billion=20.0,
            pe_avg_5y=5.0,
            net_profit_year_map={},
            dividend_year_map={},
        )
        db.add(row)
        db.commit()

        assert db.scalars(select(ForecastRevision)).all() == []
