from datetime import datetime

from pydantic import BaseModel, Field


class StockRowBase(BaseModel):
    ticker: str = Field(default="", max_length=32)
    shares_billion: float | None = Field(default=None, ge=0)
    pe_avg_5y: float | None = Field(default=None, ge=0)
    forecast_profit_year1_billion_rub: float | None = Field(default=None)
    forecast_profit_year2_billion_rub: float | None = Field(default=None)
    forecast_profit_year3_billion_rub: float | None = Field(default=None)
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
    upside_percent_year1: float | None
    upside_percent_year2: float | None
    upside_percent_year3: float | None
    status_message: str | None
    price_updated_at: datetime | None
    created_at: datetime
    updated_at: datetime | None

    class Config:
        from_attributes = True
