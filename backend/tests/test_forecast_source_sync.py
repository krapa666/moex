from app.forecast_source_sync import _get_or_create_target_tables, merge_future_values
from app.models import AnalystTable, Base, StockRow
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def test_create_missing_source_table_copies_primary_universe() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        primary = AnalystTable(
            analyst_name="Основной",
            year_offset=0,
            forecast_start_year=2026,
            sort_order=1,
        )
        db.add(primary)
        db.commit()
        db.refresh(primary)
        db.add(
            StockRow(
                table_id=primary.id,
                ticker="SBER",
                current_price=300.0,
                shares_billion=21.5,
                pe_avg_5y=5.2,
                net_profit_year_map={"2026": 1500.0},
            )
        )
        db.commit()

        tables, created = _get_or_create_target_tables(
            db,
            "Новый источник",
            create_table_if_missing=True,
        )
        db.commit()

        assert created is True
        assert len(tables) == 1
        copied = db.scalars(select(StockRow).where(StockRow.table_id == tables[0].id)).one()
        assert copied.ticker == "SBER"
        assert copied.current_price == 300.0
        assert copied.shares_billion == 21.5
        assert copied.pe_avg_5y == 5.2
        assert copied.net_profit_year_map == {}


def test_merge_future_values_is_source_agnostic() -> None:
    merged, changed = merge_future_values({"2099": 1.0}, {"2099": 2.0, "2100": 3.0})

    assert changed is True
    assert merged == {"2099": 2.0, "2100": 3.0}
