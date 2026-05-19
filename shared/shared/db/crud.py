"""
Database CRUD operations for BTC Predictor.

Functions for querying and manipulating database records using SQLAlchemy ORM.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from shared.db.models import Model, Prediction


def get_evaluated_predictions(
    session: Session,
    from_date: date | None = None,
    to_date: date | None = None,
    timeframe: str | None = None,
) -> list[Prediction]:
    """
    Query all evaluated predictions (actual_price IS NOT NULL) with model info.

    Args:
        session: SQLAlchemy database session
        from_date: Optional start date filter (inclusive)
        to_date: Optional end date filter (inclusive)
        timeframe: Optional timeframe filter ('1h', '1d', '1w')

    Returns:
        List of Prediction objects with model relationship loaded,
        ordered by predicted_for DESC (most recent first)

    Example:
        >>> predictions = get_evaluated_predictions(session, from_date=date(2026, 5, 1))
        >>> for p in predictions:
        ...     print(f"{p.predicted_for}: {p.error_pct}% error")
    """
    query = (
        select(Prediction)
        .join(Model, Prediction.model_id == Model.id)
        .where(Prediction.actual_price.isnot(None))
    )

    # Apply date range filters
    if from_date:
        query = query.where(Prediction.predicted_for >= from_date)
    if to_date:
        query = query.where(Prediction.predicted_for <= to_date)
    if timeframe:
        query = query.where(Prediction.timeframe == timeframe)

    # Order by most recent first
    query = query.order_by(Prediction.predicted_for.desc())

    result = session.execute(query)
    return list(result.scalars().all())


async def get_evaluated_predictions_async(
    session: AsyncSession,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[Prediction]:
    """
    Async version of get_evaluated_predictions.

    Query all evaluated predictions (actual_price IS NOT NULL) with model info.

    Args:
        session: SQLAlchemy async database session
        from_date: Optional start date filter (inclusive)
        to_date: Optional end date filter (inclusive)

    Returns:
        List of Prediction objects with model relationship loaded,
        ordered by predicted_for DESC (most recent first)
    """
    query = (
        select(Prediction)
        .join(Model, Prediction.model_id == Model.id)
        .where(Prediction.actual_price.isnot(None))
    )

    # Apply date range filters
    if from_date:
        query = query.where(Prediction.predicted_for >= from_date)
    if to_date:
        query = query.where(Prediction.predicted_for <= to_date)

    # Order by most recent first
    query = query.order_by(Prediction.predicted_for.desc())

    result = await session.execute(query)
    return list(result.scalars().all())
