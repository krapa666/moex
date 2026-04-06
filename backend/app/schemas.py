from datetime import datetime

from pydantic import BaseModel, Field


class StockRowBase(BaseModel):
    table_id: int
    ticker: str = Field(default="", max_length=32)
    shares_billion: float | None = Field(default=None, ge=0)
    pe_avg_5y: float | None = Field(default=None, ge=0)
    forecast_profit_year1_billion_rub: float | None = Field(default=None)
    forecast_profit_year2_billion_rub: float | None = Field(default=None)
    forecast_profit_year3_billion_rub: float | None = Field(default=None)
    forecast_profit_year4_billion_rub: float | None = Field(default=None)
    net_profit_year_map: dict[str, float | None] | None = Field(default=None)
    net_profit_source_comment: str | None = Field(default=None, max_length=512)


class StockRowCreate(StockRowBase):
    pass


class StockRowUpdate(StockRowBase):
    pass


class StockRowRead(StockRowBase):
    id: int
    current_price: float | None
    market_cap_billion_rub: float | None
    forecast_price_year1: float | None
    forecast_price_year2: float | None
    forecast_price_year3: float | None
    forecast_price_year4: float | None
    upside_percent_year1: float | None
    upside_percent_year2: float | None
    upside_percent_year3: float | None
    upside_percent_year4: float | None
    status_message: str | None
    price_updated_at: datetime | None
    created_at: datetime
    updated_at: datetime | None

    class Config:
        from_attributes = True


class AnalystTableCreate(BaseModel):
    analyst_name: str = Field(min_length=1, max_length=100)
    source_table_id: int | None = Field(default=None, ge=1)


class AnalystTableUpdate(BaseModel):
    analyst_name: str | None = Field(default=None, min_length=1, max_length=100)
    year_offset: int | None = Field(default=None, ge=-20, le=20)


class AnalystTableRead(BaseModel):
    id: int
    table_number: int
    analyst_name: str
    year_offset: int
    created_at: datetime

    class Config:
        from_attributes = True


class TickerComparisonYear(BaseModel):
    year: int
    forecast_profit_billion_rub: float | None
    forecast_price: float | None
    upside_percent: float | None


class TickerComparisonItem(BaseModel):
    table_id: int
    table_number: int
    analyst_name: str
    year_offset: int
    ticker: str
    years: list[TickerComparisonYear]
