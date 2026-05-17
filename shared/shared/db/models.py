"""
SQLAlchemy models for BTC Predictor.

Models:
- BtcPrice: Historical Bitcoin OHLCV price data
- Model: Trained ML models with versioning
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
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
        comment="Price timestamp in UTC",
    )
    open: Mapped[Decimal] = mapped_column(
        NUMERIC(18, 8), nullable=False, comment="Opening price in USDT"
    )
    high: Mapped[Decimal] = mapped_column(
        NUMERIC(18, 8), nullable=False, comment="Highest price in USDT"
    )
    low: Mapped[Decimal] = mapped_column(
        NUMERIC(18, 8), nullable=False, comment="Lowest price in USDT"
    )
    close: Mapped[Decimal] = mapped_column(
        NUMERIC(18, 8), nullable=False, comment="Closing price in USDT"
    )
    volume: Mapped[Decimal] = mapped_column(
        NUMERIC(18, 8), nullable=False, comment="Trading volume in BTC"
    )
    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="binance",
        comment="Data source (e.g., 'binance')",
    )

    def __repr__(self) -> str:
        return (
            f"<BtcPrice(timestamp={self.timestamp}, "
            f"close={self.close}, source={self.source})>"
        )


class Model(Base):
    """
    Trained ML models with versioning and training metadata.

    Stores serialized model artifacts (pickled scikit-learn models), training
    parameters, and metadata. Supports model versioning and rollback.
    Only one model per name can be active at a time (enforced by application logic).
    """

    __tablename__ = "models"
    __table_args__ = (
        UniqueConstraint("name", "version", name="unique_model_version"),
        CheckConstraint("train_to >= train_from", name="valid_training_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Model name (e.g., 'linear_v1', 'lstm_v1')",
    )
    version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Model version (e.g., '1.0.0', '2024-05-17-001')",
    )
    params: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="Training hyperparameters as JSON (e.g., {'window_days': 30})",
    )
    artifact: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False, comment="Serialized model (pickle format)"
    )
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="When training completed"
    )
    train_from: Mapped[date] = mapped_column(
        Date, nullable=False, comment="Training data start date"
    )
    train_to: Mapped[date] = mapped_column(
        Date, nullable=False, comment="Training data end date"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether this model is currently active for predictions",
    )

    def __repr__(self) -> str:
        return (
            f"<Model(name={self.name}, version={self.version}, "
            f"is_active={self.is_active}, trained_at={self.trained_at})>"
        )
