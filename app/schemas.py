from pydantic import BaseModel


class QuoteResponse(BaseModel):
    ticker: str
    board: str
    price: float
    currency: str
