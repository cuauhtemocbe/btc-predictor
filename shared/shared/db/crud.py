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


def get_active_model(session: Session) -> Model | None:
    """
    Get the currently active model.

    Args:
        session: SQLAlchemy database session

    Returns:
        Active Model object or None if no active model exists

    Example:
        >>> active = get_active_model(session)
        >>> if active:
        ...     print(f"Active model: {active.name} v{active.version}")
    """
    query = select(Model).where(Model.is_active.is_(True))
    result = session.execute(query)
    return result.scalar_one_or_none()


def get_all_models(session: Session) -> list[Model]:
    """
    Get all models ordered by trained_at DESC (most recent first).

    Args:
        session: SQLAlchemy database session

    Returns:
        List of all Model objects ordered by training date

    Example:
        >>> models = get_all_models(session)
        >>> for m in models:
        ...     print(f"{m.name} v{m.version} - Active: {m.is_active}")
    """
    query = select(Model).order_by(Model.trained_at.desc())
    result = session.execute(query)
    return list(result.scalars().all())


def deactivate_all_models(session: Session) -> int:
    """
    Set is_active=False for all models.

    Args:
        session: SQLAlchemy database session

    Returns:
        Number of models deactivated

    Example:
        >>> count = deactivate_all_models(session)
        >>> session.commit()
        >>> print(f"Deactivated {count} models")
    """
    query = select(Model).where(Model.is_active.is_(True))
    result = session.execute(query)
    active_models = list(result.scalars().all())

    for model in active_models:
        model.is_active = False

    return len(active_models)


def activate_model(session: Session, model_id: int) -> Model:
    """
    Activate a specific model by ID, deactivating all others.

    Ensures only ONE model is active at any time.

    Args:
        session: SQLAlchemy database session
        model_id: ID of the model to activate

    Returns:
        The activated Model object

    Raises:
        ValueError: If model_id doesn't exist

    Example:
        >>> model = activate_model(session, model_id=42)
        >>> session.commit()
        >>> print(f"Activated: {model.name} v{model.version}")
    """
    # First, get the model to activate (raises if doesn't exist)
    query = select(Model).where(Model.id == model_id)
    result = session.execute(query)
    model = result.scalar_one_or_none()

    if model is None:
        raise ValueError(f"Model with id={model_id} does not exist")

    # Deactivate all models
    deactivate_all_models(session)

    # Activate the target model
    model.is_active = True

    return model
