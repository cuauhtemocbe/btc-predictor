"""Headline blocks of the dashboard: live and replay scored apart (#176)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from api.numeric import required_float
from shared.db.models import Prediction, PredictionSource
from shared.model_baselines import BASELINE_TIMEFRAME, baseline_for_predictions


@dataclass(frozen=True)
class SourceSummary:
    """Evaluated predictions of one source, with the baselines over the same days."""

    key: str
    title: str
    note: str
    count: int
    accuracy_pct: float | None
    avg_error_pct: float | None
    total_pnl: float
    baseline: dict[str, Any] | None


_LIVE = ("live", "Live", "Made by the running system, one prediction per day.")
_REPLAY = (
    "replay",
    "Replay (simulated)",
    "Simulated afterwards with the same code, for the days before go-live. "
    "Not live results.",
)
_COMBINED = (
    "combined",
    "Live + replay",
    "Both sources added together. Read each source above on its own first.",
)


def summarize(
    db: Session,
    symbol: str,
    timeframe: str,
    spec: tuple[str, str, str],
    predictions: Sequence[Prediction],
) -> SourceSummary:
    """Accuracy, average error, simple PnL and baselines of ``predictions``."""
    key, title, note = spec
    count = len(predictions)
    correct = sum(1 for p in predictions if p.direction_correct)
    return SourceSummary(
        key=key,
        title=title,
        note=note,
        count=count,
        accuracy_pct=correct / count * 100 if count else None,
        avg_error_pct=(
            sum(required_float(p.error_pct, "error_pct") for p in predictions) / count
            if count
            else None
        ),
        total_pnl=sum(
            required_float(p.pnl_simulated, "pnl_simulated") for p in predictions
        ),
        baseline=(
            baseline_for_predictions(db, symbol, predictions)
            if timeframe == BASELINE_TIMEFRAME
            else None
        ),
    )


def source_summaries(
    db: Session,
    symbol: str,
    timeframe: str,
    source: PredictionSource,
    predictions: Sequence[Prediction],
) -> list[SourceSummary]:
    """
    One block per source shown: live, replay, and live + replay only under ``all``.

    ``predictions`` are the evaluated rows already filtered by ``source`` in SQL;
    they are only grouped here. A source with no rows still gets its block (n = 0),
    so a missing live history is visible instead of silently absent.
    """
    live = [p for p in predictions if not p.model.is_replay]
    replay = [p for p in predictions if p.model.is_replay]
    blocks: list[SourceSummary] = []
    if source is not PredictionSource.REPLAY:
        blocks.append(summarize(db, symbol, timeframe, _LIVE, live))
    if source is not PredictionSource.LIVE:
        blocks.append(summarize(db, symbol, timeframe, _REPLAY, replay))
    if source is PredictionSource.ALL:
        blocks.append(summarize(db, symbol, timeframe, _COMBINED, predictions))
    return blocks
