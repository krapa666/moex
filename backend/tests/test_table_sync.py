import pytest
from app.main import (
    build_database_snapshot,
    delete_row,
    ensure_primary_table_for_row_mutation,
    import_database_snapshot,
    is_shared_fields_editable_for_table,
    sync_row_to_other_tables,
)
from app.models import AnalystTable, Base, StockRow
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def test_sync_row_to_other_tables_copies_shared_fields_without_net_profit() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        table1 = AnalystTable(analyst_name="Аналитик 1", year_offset=0)
        table2 = AnalystTable(analyst_name="Аналитик 2", year_offset=0)
        table3 = AnalystTable(analyst_name="Аналитик 3", year_offset=1)
        db.add_all([table1, table2, table3])
        db.commit()
        db.refresh(table1)
        db.refresh(table2)
        db.refresh(table3)

        source = StockRow(
            table_id=table2.id,
            ticker="SBER",
            current_price=303.0,
            shares_billion=21.5,
            pe_avg_5y=5.2,
            market_cap_billion_rub=6514.5,
            net_profit_year_map={"2026": 1_400.0},
            forecast_profit_year1_billion_rub=1_400.0,
            forecast_price_year1=338.6,
            upside_percent_year1=11.7,
        )
        db.add(source)
        db.commit()
        db.refresh(source)

        sync_row_to_other_tables(db, source)
        db.commit()

        copied_rows = db.scalars(
            select(StockRow).where(StockRow.ticker == "SBER").order_by(StockRow.table_id.asc())
        ).all()
        assert len(copied_rows) == 3

        for row in copied_rows:
            assert row.current_price == 303.0
            assert row.shares_billion == 21.5
            assert row.pe_avg_5y == 5.2
            assert row.market_cap_billion_rub == 6514.5
            if row.table_id != table2.id:
                assert row.net_profit_year_map == {}
                assert row.forecast_profit_year1_billion_rub is None
                assert row.forecast_price_year1 is None
                assert row.upside_percent_year1 is None


def test_shared_fields_are_editable_in_non_primary_only_for_new_ticker() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        table1 = AnalystTable(analyst_name="Аналитик 1", year_offset=0, sort_order=1)
        table2 = AnalystTable(analyst_name="Аналитик 2", year_offset=0, sort_order=2)
        db.add_all([table1, table2])
        db.commit()
        db.refresh(table1)
        db.refresh(table2)

        db.add(StockRow(table_id=table1.id, ticker="SBER", shares_billion=21.5, pe_avg_5y=5.2))
        db.commit()

        assert is_shared_fields_editable_for_table(db, table2.id, "SBER") is False
        assert is_shared_fields_editable_for_table(db, table2.id, "LKOH") is True


def test_row_mutation_permissions_allow_only_primary_table() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        table1 = AnalystTable(analyst_name="Аналитик 1", year_offset=0, sort_order=1)
        table2 = AnalystTable(analyst_name="Аналитик 2", year_offset=0, sort_order=2)
        db.add_all([table1, table2])
        db.commit()
        db.refresh(table1)
        db.refresh(table2)

        ensure_primary_table_for_row_mutation(db, table1.id)
        with pytest.raises(HTTPException) as exc:
            ensure_primary_table_for_row_mutation(db, table2.id)
        assert exc.value.status_code == 403


def test_delete_primary_row_removes_rows_with_same_ticker_from_all_tables() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        table1 = AnalystTable(analyst_name="Аналитик 1", year_offset=0, sort_order=1)
        table2 = AnalystTable(analyst_name="Аналитик 2", year_offset=0, sort_order=2)
        db.add_all([table1, table2])
        db.commit()
        db.refresh(table1)
        db.refresh(table2)

        row_primary = StockRow(table_id=table1.id, ticker="SBER")
        row_secondary = StockRow(table_id=table2.id, ticker="SBER")
        db.add_all([row_primary, row_secondary])
        db.commit()
        db.refresh(row_primary)

        delete_row(row_primary.id, db)

        remained = db.scalars(select(StockRow).where(StockRow.ticker == "SBER")).all()
        assert remained == []


def test_export_and_import_database_snapshot() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        table1 = AnalystTable(analyst_name="Аналитик 1", year_offset=0, sort_order=1)
        table2 = AnalystTable(analyst_name="Аналитик 2", year_offset=1, sort_order=2)
        db.add_all([table1, table2])
        db.commit()
        db.refresh(table1)
        db.refresh(table2)

        db.add_all(
            [
                StockRow(table_id=table1.id, ticker="SBER", shares_billion=21.5),
                StockRow(table_id=table2.id, ticker="GAZP", shares_billion=23.7),
            ]
        )
        db.commit()

        payload = build_database_snapshot(db)
        assert len(payload["tables"]) == 2
        assert len(payload["rows"]) == 2

        db.add(StockRow(table_id=table1.id, ticker="LKOH"))
        db.commit()

        imported = import_database_snapshot(db, payload)
        assert imported["tables_count"] == 2
        assert imported["rows_count"] == 2

        tickers = [row.ticker for row in db.scalars(select(StockRow).order_by(StockRow.ticker.asc())).all()]
        assert tickers == ["GAZP", "SBER"]
