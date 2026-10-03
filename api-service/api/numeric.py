"""Number conversions shared by the dashboard and the predictions API."""

from decimal import Decimal


def required_float(value: Decimal | None, column: str) -> float:
    """Convert a column that every evaluated prediction carries.

    The history queries only return rows with ``actual_price`` set, and the
    evaluator writes the errors and the PnL in the same update, so a NULL here
    means corrupted data: fail with the column name instead of with
    ``float(None)``.
    """
    if value is None:
        raise ValueError(f"{column} is NULL on an evaluated prediction")
    return float(value)
