from sqlalchemy import Column, DateTime, Float, Integer, String, func

from app.database import Base


class QuoteRequest(Base):
    __tablename__ = "quote_requests"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(32), index=True, nullable=False)
    board = Column(String(16), nullable=False)
    price = Column(Float, nullable=False)
    currency = Column(String(8), nullable=False, default="RUB")
    requested_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
