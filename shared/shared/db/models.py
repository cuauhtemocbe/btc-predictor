"""
SQLAlchemy models for BTC Predictor.

Models:
- Price: Historical OHLCV price data, one series per asset symbol
- Model: Trained ML models with versioning
- Prediction: Daily price predictions with evaluation metrics
- BacktestResult: Walk-forward backtesting simulation results
"""

import re
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import NUMERIC

# Asset every row belongs to unless told otherwise (the original BTC pipeline).
DEFAULT_SYMBOL = "BTCUSDT"

# Trailing "_v<N>" the trainers append to a model name ("linear_v2"). It stays
# "[0-9]", not "\d", on purpose: Python's "\d" also matches non-ASCII digits and
# PostgreSQL's depends on the locale, so the two sides could disagree, and the
# index of migration d5a1c7e93b20 is built with "[0-9]".
VERSION_SUFFIX_PATTERN = r"_v[0-9]+$"  # NOSONAR python:S6353 (reason above)


# The same rule as model_family(), as a SQL expression on the ``name`` column.
MODEL_FAMILY_SQL = f"regexp_replace(name, '{VERSION_SUFFIX_PATTERN}', '')"


# Key of ``Model.params`` that ``scripts/simulate_history.py`` sets on every model
# it trains to replay the days before go-live (#176). Live trainers never set it.
REPLAY_PARAM = "simulated"


class PredictionSource(StrEnum):
    """Which predictions a query or page covers: live ones, replayed ones or both."""

    LIVE = "live"
    REPLAY = "replay"
    ALL = "all"


def is_replay_params(params: dict[str, Any] | None) -> bool:
    """Whether a model's ``params`` mark it as trained by the history replay."""
    return params is not None and params.get(REPLAY_PARAM) is True


def model_family(name: str) -> str:
    """
    Model name without its trailing version suffix: "linear_v2" -> "linear".

    The family is the "same model" scope of the one-active-version rule: the
    trainers put the version in the name, so every version of a model has a
    different name but the same family.
    """
    return re.sub(VERSION_SUFFIX_PATTERN, "", name)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


class Price(Base):
    """
    Historical OHLCV (Open, High, Low, Close, Volume) price data per asset.

    Each row belongs to one asset, identified by ``symbol`` (e.g. 'BTCUSDT',
    'PAXGUSDT'); a timestamp is unique per symbol, so several assets share the
    table. Used for model training, evaluation, and historical analysis.
    """

    __tablename__ = "prices"
    __table_args__ = (
        UniqueConstraint("symbol", "timestamp", name="unique_price_per_symbol"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=DEFAULT_SYMBOL,
        comment="Asset symbol (e.g., 'BTCUSDT', 'PAXGUSDT')",
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
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
        NUMERIC(18, 8), nullable=False, comment="Trading volume in the base asset"
    )
    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="binance",
        comment="Data source (e.g., 'binance')",
    )

    def __repr__(self) -> str:
        return (
            f"<Price(symbol={self.symbol}, timestamp={self.timestamp}, "
            f"close={self.close}, source={self.source})>"
        )


class Model(Base):
    """
    Trained ML models with versioning and training metadata.

    Stores serialized model artifacts (pickled scikit-learn models), training
    parameters, and metadata. Supports model versioning and rollback.
    Each model is trained for one asset (``symbol``); predictions get their
    asset through ``model_id``. At most one active version per
    (symbol, family, timeframe) is allowed at a time, enforced by the partial
    unique index ix_models_one_active_version_per_name_timeframe -- not just
    application logic. The family is the name without its ``_v<N>`` suffix
    (see ``model_family``), so "linear_v1" and "linear_v2" are versions of
    one model. Different families (e.g. "linear_v1" and "xgboost_v1") can be
    active at the same time within the same timeframe; that's what powers
    multi-model prediction mode (US-025). The same model name can be trained
    once per asset.
    """

    __tablename__ = "models"
    __table_args__ = (
        UniqueConstraint("symbol", "name", "version", name="unique_model_version"),
        CheckConstraint("train_to >= train_from", name="valid_training_period"),
        CheckConstraint("timeframe IN ('1d')", name="valid_model_timeframe_values"),
        Index(
            "ix_models_one_active_version_per_name_timeframe",
            "symbol",
            text(MODEL_FAMILY_SQL),
            "timeframe",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=DEFAULT_SYMBOL,
        comment="Asset this model predicts (e.g., 'BTCUSDT', 'PAXGUSDT')",
    )
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
    params: Mapped[dict[str, Any]] = mapped_column(
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
    timeframe: Mapped[str] = mapped_column(
        String(2),
        nullable=False,
        default="1d",
        comment=(
            "Prediction horizon this model was trained for: '1d' (daily), "
            "the only value allowed. At most one active version per "
            "(symbol, family, timeframe) is allowed at a time (enforced by "
            "ix_models_one_active_version_per_name_timeframe); different "
            "families can be active concurrently (multi-model mode)."
        ),
    )

    @property
    def is_replay(self) -> bool:
        """True when the model was trained by the history replay (simulated)."""
        return is_replay_params(self.params)

    def __repr__(self) -> str:
        return (
            f"<Model(symbol={self.symbol}, name={self.name}, "
            f"version={self.version}, "
            f"timeframe={self.timeframe}, is_active={self.is_active}, "
            f"trained_at={self.trained_at})>"
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

    Only the daily timeframe (1d) is allowed; the column is kept so the unique
    constraint and the queries do not change.
    """

    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint(
            "predicted_for",
            "timeframe",
            "model_id",
            name="unique_prediction_per_model_timeframe",
        ),
        CheckConstraint("timeframe IN ('1d')", name="valid_timeframe_values"),
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
        comment="Date being predicted (the day after the last closed bar)",
    )
    timeframe: Mapped[str] = mapped_column(
        String(2),
        nullable=False,
        default="1d",
        comment="Prediction timeframe: '1d' (daily, the only value allowed)",
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
    __table_args__ = (
        CheckConstraint(
            "evaluation_slice IN ('validation', 'test')",
            name="valid_evaluation_slice_values",
        ),
    )

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
    model_params: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Model training parameters as JSONB "
        "(e.g., {'model_name': 'linear_v1', 'window_days': 30})",
    )
    evaluation_slice: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="'validation' (may inform choices) or 'test' (headline, "
        "out-of-sample); NULL for rows stored before the split existed",
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
