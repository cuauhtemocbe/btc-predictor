"""Type aliases shared by the script tests."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from shared.db.models import BacktestResult

# (day, close, volume), one per day: the seeded random walk of conftest.py.
DailyRows = list[tuple[date, Decimal, Decimal]]

# (timestamp, open, high, low, close, volume): the cached intraday-style rows.
PriceRows = list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, Decimal]]


def params_of(row: BacktestResult) -> dict[str, Any]:
    """The stored model parameters of a result row, which every run fills in."""
    assert row.model_params is not None
    return row.model_params
