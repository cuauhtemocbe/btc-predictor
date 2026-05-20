"""
SQLAlchemy models for BTC Predictor.

Models:
- BtcPrice: Historical Bitcoin OHLCV price data
- Model: Trained ML models with versioning
- Prediction: Daily price predictions with evaluation metrics
- BacktestResult: Walk-forward backtesting simulation results
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
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
        JSON,
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


class Prediction(Base):
    """
    Daily Bitcoin price predictions with evaluation metrics.

    Two-phase lifecycle:
    1. Insert: Predictor job creates record with predicted_price,
       evaluation fields NULL
    2. Update: Evaluator job fills actual_price, errors,
       direction_correct, pnl_simulated

    Tracks model accuracy, error rates, and simulated trading profitability.

    Supports multiple timeframes: 1d (daily), 1w (weekly).
    """

    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint(
            "predicted_for",
            "timeframe",
            "model_id",
            name="unique_prediction_per_model_timeframe",
        ),
        CheckConstraint(
            "timeframe IN ('1h', '1d', '1w')", name="valid_timeframe_values"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(
        ForeignKey("models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Foreign key to models table",
    )
    predicted_for: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        comment="Date being predicted (usually tomorrow for 1d, 7 days ahead for 1w)",
    )
    timeframe: Mapped[str] = mapped_column(
        String(2),
        nullable=False,
        default="1d",
        comment="Prediction timeframe: '1h' (hourly), '1d' (daily), '1w' (weekly)",
    )
    predicted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Timestamp when prediction was made",
    )
    price_at_prediction: Mapped[Decimal] = mapped_column(
        NUMERIC(10, 2),
        nullable=False,
        comment="BTC price when prediction was made (in USDT)",
    )
    predicted_price: Mapped[Decimal] = mapped_column(
        NUMERIC(10, 2), nullable=False, comment="Predicted BTC price (in USDT)"
    )
    actual_price: Mapped[Decimal | None] = mapped_column(
        NUMERIC(10, 2),
        nullable=True,
        comment="Actual BTC price (filled by evaluator, NULL until evaluated)",
    )
    evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when evaluation was performed",
    )
    error_abs: Mapped[Decimal | None] = mapped_column(
        NUMERIC(10, 2),
        nullable=True,
        comment="Absolute error: |actual_price - predicted_price|",
    )
    error_pct: Mapped[Decimal | None] = mapped_column(
        NUMERIC(5, 2),
        nullable=True,
        comment="Percentage error: "
        "(actual_price - predicted_price) / actual_price * 100",
    )
    direction_correct: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        comment="True if predicted direction (up/down) was correct",
    )
    pnl_simulated: Mapped[Decimal | None] = mapped_column(
        NUMERIC(11, 2),
        nullable=True,
        comment="Simulated profit/loss from trading strategy (in USDT)",
    )
    pnl_long_short: Mapped[Decimal | None] = mapped_column(
        NUMERIC(11, 2),
        nullable=True,
        comment="PnL from long/short symmetric strategy: long if UP, short if DOWN",
    )
    pnl_threshold: Mapped[Decimal | None] = mapped_column(
        NUMERIC(11, 2),
        nullable=True,
        comment="PnL with threshold filter: only trade if predicted change > 1%",
    )
    pnl_realistic: Mapped[Decimal | None] = mapped_column(
        NUMERIC(11, 2),
        nullable=True,
        comment="PnL with trading fees (0.1%) and stop-loss (2% max loss)",
    )

    # Relationship to Model
    model: Mapped["Model"] = relationship("Model")

    def __repr__(self) -> str:
        return (
            f"<Prediction(id={self.id}, model_id={self.model_id}, "
            f"predicted_for={self.predicted_for}, "
            f"predicted_price={self.predicted_price}, "
            f"actual_price={self.actual_price})>"
        )


class BacktestResult(Base):
    """
    Walk-forward backtesting simulation results.

    Stores historical backtest predictions where each day:
    1. Model is trained on rolling window of past data
    2. Next day's price is predicted
    3. Actual price is fetched
    4. All 4 PnL strategies are calculated

    Each backtest run has a unique backtest_run_id (UUID) to distinguish
    different simulation runs.
    """

    __tablename__ = "backtest_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    backtest_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="Unique ID for this backtest run (UUID)",
    )
    predicted_for: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        comment="Date being predicted in the backtest",
    )
    predicted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Timestamp when prediction was made (simulated)",
    )
    price_at_prediction: Mapped[Decimal] = mapped_column(
        NUMERIC(15, 2),
        nullable=False,
        comment="BTC price at prediction time (in USDT)",
    )
    predicted_price: Mapped[Decimal] = mapped_column(
        NUMERIC(15, 2),
        nullable=False,
        comment="Predicted BTC price (in USDT)",
    )
    actual_price: Mapped[Decimal] = mapped_column(
        NUMERIC(15, 2),
        nullable=False,
        comment="Actual BTC price for that day (in USDT)",
    )
    pnl_simple: Mapped[Decimal | None] = mapped_column(
        NUMERIC(15, 2),
        nullable=True,
        comment="PnL from simple strategy: buy if predicted up, sell if down",
    )
    pnl_long_short: Mapped[Decimal | None] = mapped_column(
        NUMERIC(15, 2),
        nullable=True,
        comment="PnL from long/short strategy: long if UP, short if DOWN",
    )
    pnl_threshold: Mapped[Decimal | None] = mapped_column(
        NUMERIC(15, 2),
        nullable=True,
        comment="PnL with threshold filter: only trade if predicted change > 1%",
    )
    pnl_realistic: Mapped[Decimal | None] = mapped_column(
        NUMERIC(15, 2),
        nullable=True,
        comment="PnL with trading fees (0.1%) and stop-loss (2% max loss)",
    )
    model_params: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Model training parameters as JSONB "
        "(e.g., {'model_name': 'linear_v1', 'window_days': 30})",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="NOW()",
        comment="When this result was created",
    )

    def __repr__(self) -> str:
        return (
            f"<BacktestResult(id={self.id}, "
            f"backtest_run_id={self.backtest_run_id}, "
            f"predicted_for={self.predicted_for}, "
            f"predicted_price={self.predicted_price}, "
            f"actual_price={self.actual_price})>"
        )
