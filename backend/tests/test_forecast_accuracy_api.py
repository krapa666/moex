from math import inf, nan

from app.forecast_api import ActualNetProfitWrite, require_local_access, upsert_actual_net_profit
from app.forecast_accuracy import ActualNetProfit
from app.models import Base
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from starlette.requests import Request


def _request(scope: str | None) -> Request:
    headers = []
    if scope is not None:
        headers.append((b"x-moex-access-scope", scope.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "PUT",
            "path": "/api/analytics/actual-net-profits/SBER/2025",
            "headers": headers,
            "client": ("127.0.0.1", 12345),
            "server": ("backend", 8000),
            "scheme": "http",
            "query_string": b"",
        }
    )


def test_actual_result_write_requires_explicit_local_scope() -> None:
    for scope in (None, "internet"):
        try:
            require_local_access(_request(scope))
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("non-local actual result write was accepted")

    require_local_access(_request("local"))


def test_actual_result_upsert_normalizes_ticker_and_updates_restated_value() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        first = upsert_actual_net_profit(
            request=_request("local"),
            payload=ActualNetProfitWrite(
                net_profit_billion_rub=100.0,
                source_name="Issuer IFRS",
            ),
            ticker="sber",
            fiscal_year=2025,
            db=db,
        )
        second = upsert_actual_net_profit(
            request=_request("local"),
            payload=ActualNetProfitWrite(
                net_profit_billion_rub=105.0,
                source_name="Issuer IFRS restatement",
            ),
            ticker="SBER",
            fiscal_year=2025,
            db=db,
        )

        rows = list(db.scalars(select(ActualNetProfit)).all())

    assert first.id == second.id
    assert len(rows) == 1
    assert rows[0].ticker == "SBER"
    assert rows[0].net_profit_billion_rub == 105.0
    assert rows[0].source_name == "Issuer IFRS restatement"


def test_actual_result_rejects_non_finite_values() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        for value in (nan, inf, -inf):
            try:
                upsert_actual_net_profit(
                    request=_request("local"),
                    payload=ActualNetProfitWrite(
                        net_profit_billion_rub=value,
                        source_name="Issuer",
                    ),
                    ticker="SBER",
                    fiscal_year=2025,
                    db=db,
                )
            except HTTPException as exc:
                assert exc.status_code == 422
            else:
                raise AssertionError("non-finite actual result was accepted")
