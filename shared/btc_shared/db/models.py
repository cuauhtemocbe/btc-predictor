"""
SQLAlchemy models for BTC Predictor.

Models:
- BtcPrice: Historical Bitcoin OHLCV price data
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import NUMERIC


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


class BtcPrice(Base):
    """
    Historical Bitcoin OHLCV (Open, High, Low, Close, Volume) price data.

    Data is populated hourly by the fetch-price cron job from Binance API.
    Used for model training, evaluation, and historical analysis.
    """
    __tablename__ = "btc_prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        unique=True,
        nullable=False,
        index=True,
        comment="Price timestamp in UTC"
    )
    open: Mapped[Decimal] = mapped_column(
        NUMERIC(18, 8),
        nullable=False,
        comment="Opening price in USDT"
    )
    high: Mapped[Decimal] = mapped_column(
        NUMERIC(18, 8),
        nullable=False,
        comment="Highest price in USDT"
    )
    low: Mapped[Decimal] = mapped_column(
        NUMERIC(18, 8),
        nullable=False,
        comment="Lowest price in USDT"
    )
    close: Mapped[Decimal] = mapped_column(
        NUMERIC(18, 8),
        nullable=False,
        comment="Closing price in USDT"
    )
    volume: Mapped[Decimal] = mapped_column(
        NUMERIC(18, 8),
        nullable=False,
        comment="Trading volume in BTC"
    )
    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="binance",
        comment="Data source (e.g., 'binance')"
    )

    def __repr__(self) -> str:
        return (
            f"<BtcPrice(timestamp={self.timestamp}, "
            f"close={self.close}, source={self.source})>"
        )
