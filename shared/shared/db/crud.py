"""Queries and updates on predictions and models."""

from datetime import date

from sqlalchemy import ColumnElement, false, func, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from shared.db.models import (
    REPLAY_PARAM,
    VERSION_SUFFIX_PATTERN,
    Model,
    Prediction,
    PredictionSource,
    model_family,
)


def source_filter(source: PredictionSource) -> ColumnElement[bool]:
    """SQL condition selecting the models of one source; needs ``models`` in the query.

    A replay model has ``params["simulated"]`` true (``is_replay_params`` is the Python
    twin); one without the key, or with it false, is live.
    """
    if source is PredictionSource.ALL:
        return true()
    is_replay = func.coalesce(Model.params[REPLAY_PARAM].as_boolean(), false())
    return is_replay if source is PredictionSource.REPLAY else ~is_replay


def get_evaluated_predictions(
    session: Session,
    from_date: date | None = None,
    to_date: date | None = None,
    timeframe: str | None = None,
    symbol: str | None = None,
    source: PredictionSource = PredictionSource.ALL,
) -> list[Prediction]:
    """Evaluated predictions (``actual_price`` set), newest ``predicted_for`` first.

    Args:
        session: Database session.
        from_date: Inclusive lower bound on ``predicted_for``.
        to_date: Inclusive upper bound on ``predicted_for``.
        timeframe: Optional timeframe filter (``1d``).
        symbol: Optional filter on the predicting model's symbol.
        source: ``live``, ``replay`` or ``all``, by the predicting model.
    """
    query = (
        select(Prediction)
        .join(Model, Prediction.model_id == Model.id)
        .where(Prediction.actual_price.isnot(None))
    )

    if from_date:
        query = query.where(Prediction.predicted_for >= from_date)
    if to_date:
        query = query.where(Prediction.predicted_for <= to_date)
    if timeframe:
        query = query.where(Prediction.timeframe == timeframe)
    if symbol:
        query = query.where(Model.symbol == symbol)
    query = query.where(source_filter(source))

    query = query.order_by(Prediction.predicted_for.desc())

    result = session.execute(query)
    return list(result.scalars().all())


async def get_evaluated_predictions_async(
    session: AsyncSession,
    from_date: date | None = None,
    to_date: date | None = None,
    timeframe: str | None = None,
) -> list[Prediction]:
    """Async ``get_evaluated_predictions`` without the symbol and source filters."""
    query = (
        select(Prediction)
        .join(Model, Prediction.model_id == Model.id)
        .where(Prediction.actual_price.isnot(None))
    )

    if from_date:
        query = query.where(Prediction.predicted_for >= from_date)
    if to_date:
        query = query.where(Prediction.predicted_for <= to_date)
    if timeframe:
        query = query.where(Prediction.timeframe == timeframe)

    query = query.order_by(Prediction.predicted_for.desc())

    result = await session.execute(query)
    return list(result.scalars().all())


def get_active_model(session: Session, timeframe: str = "1d") -> Model | None:
    """An active model of ``timeframe``, or None.

    The partial unique index ``ix_models_one_active_version_per_name_timeframe`` allows
    one active version per (symbol, family, timeframe), so several families can be
    active at once; this returns the first match. Callers that need every active model
    query directly.
    """
    query = (
        select(Model)
        .where(Model.is_active.is_(True), Model.timeframe == timeframe)
        .limit(1)
    )
    result = session.execute(query)
    return result.scalar_one_or_none()


def get_all_models(session: Session) -> list[Model]:
    """All models, most recently trained first."""
    query = select(Model).order_by(Model.trained_at.desc())
    result = session.execute(query)
    return list(result.scalars().all())


def deactivate_all_models(session: Session, timeframe: str | None = None) -> int:
    """Set ``is_active`` to False on every active model, or only those of ``timeframe``.

    Does not commit.

    Returns:
        Number of models deactivated.
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
    """Activate a model and deactivate the other versions of its family, atomically.

    The family is the name without its ``_v<N>`` suffix (``model_family``): activating
    ``linear_v2`` deactivates the active ``linear_v1`` of the same symbol and timeframe,
    and leaves other families, symbols and timeframes alone. The partial unique index
    ``ix_models_one_active_version_per_name_timeframe`` is the final guard: if a
    concurrent activation of the same family commits first, this raises and rolls back,
    leaving the previous active model untouched.

    Raises:
        ValueError: If ``model_id`` does not exist.
        sqlalchemy.exc.IntegrityError: If a concurrent activation wins the race.
    """
    model = session.get(Model, model_id)

    if model is None:
        raise ValueError(f"Model with id={model_id} does not exist")

    try:
        session.execute(
            update(Model)
            .where(Model.symbol == model.symbol)
            .where(
                func.regexp_replace(Model.name, VERSION_SUFFIX_PATTERN, "")
                == model_family(model.name)
            )
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
