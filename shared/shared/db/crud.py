"""
Database CRUD operations for BTC Predictor.

Functions for querying and manipulating database records using SQLAlchemy ORM.
"""

from datetime import date

from sqlalchemy import select, update
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
    timeframe: str | None = None,
) -> list[Prediction]:
    """
    Async version of get_evaluated_predictions.

    Query all evaluated predictions (actual_price IS NOT NULL) with model info.

    Args:
        session: SQLAlchemy async database session
        from_date: Optional start date filter (inclusive)
        to_date: Optional end date filter (inclusive)
        timeframe: Optional timeframe filter ('1h', '1d', '1w')

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
    if timeframe:
        query = query.where(Prediction.timeframe == timeframe)

    # Order by most recent first
    query = query.order_by(Prediction.predicted_for.desc())

    result = await session.execute(query)
    return list(result.scalars().all())


def get_active_model(session: Session, timeframe: str = "1d") -> Model | None:
    """
    Get an active model for a given timeframe.

    At most one active version per (name, timeframe) is allowed (see
    ix_models_one_active_version_per_name_timeframe), but multiple
    different-named models can be active within the same timeframe at once
    (multi-model prediction mode, US-025). This returns the first match --
    callers that need every active model for a timeframe should query
    directly instead.

    Args:
        session: SQLAlchemy database session
        timeframe: Prediction horizon to look up ('1h', '1d', '1w').
            Defaults to '1d' for backward compatibility with callers
            that only ever dealt with daily models.

    Returns:
        An active Model object for that timeframe, or None if none is active

    Example:
        >>> active = get_active_model(session, timeframe="1d")
        >>> if active:
        ...     print(f"Active model: {active.name} v{active.version}")
    """
    query = (
        select(Model)
        .where(Model.is_active.is_(True), Model.timeframe == timeframe)
        .limit(1)
    )
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


def deactivate_all_models(session: Session, timeframe: str | None = None) -> int:
    """
    Set is_active=False for models, optionally scoped to one timeframe.

    Args:
        session: SQLAlchemy database session
        timeframe: If given, only deactivate models for this timeframe
            ('1h', '1d', '1w'). If None, deactivate every active model
            across all timeframes.

    Returns:
        Number of models deactivated

    Example:
        >>> count = deactivate_all_models(session)
        >>> session.commit()
        >>> print(f"Deactivated {count} models")
    """
    query = select(Model).where(Model.is_active.is_(True))
    if timeframe is not None:
        query = query.where(Model.timeframe == timeframe)
    result = session.execute(query)
    active_models = list(result.scalars().all())

    for model in active_models:
        model.is_active = False

    return len(active_models)


def activate_model(session: Session, model_id: int) -> Model:
    """
    Atomically activate a specific model by ID, replacing prior versions
    of that same (name, timeframe).

    Deactivates every other model that shares the target model's name AND
    timeframe -- e.g. activating a new "linear_v1"/"1d" model deactivates
    the previous active "linear_v1"/"1d" version, but never touches an
    active "xgboost_v1"/"1d" or "linear_v1"/"1w" model -- and activates the
    target, committing both changes as a single transaction. This scoping
    is what lets multi-model prediction mode (US-025) keep multiple
    different-named models active at once within the same timeframe.

    The partial unique index ix_models_one_active_version_per_name_timeframe
    is the final guard: if a concurrent activation for the same
    (name, timeframe) commits first, this raises IntegrityError and the
    whole transaction is rolled back, leaving the previous active model
    untouched.

    Args:
        session: SQLAlchemy database session
        model_id: ID of the model to activate

    Returns:
        The activated Model object

    Raises:
        ValueError: If model_id doesn't exist
        sqlalchemy.exc.IntegrityError: If a concurrent activation for the
            same (name, timeframe) wins the race (rolled back first)

    Example:
        >>> model = activate_model(session, model_id=42)
        >>> print(f"Activated: {model.name} v{model.version}")
    """
    model = session.get(Model, model_id)

    if model is None:
        raise ValueError(f"Model with id={model_id} does not exist")

    try:
        # Deactivate other active versions of the same (name, timeframe) via
        # a single UPDATE (not the ORM-object loop deactivate_all_models()
        # uses) so this doesn't require those rows to already be loaded.
        session.execute(
            update(Model)
            .where(Model.name == model.name)
            .where(Model.timeframe == model.timeframe)
            .where(Model.id != model_id)
            .where(Model.is_active.is_(True))
            .values(is_active=False)
        )
        model.is_active = True
        session.commit()
    except Exception:
        session.rollback()
        raise

    session.refresh(model)
    return model
