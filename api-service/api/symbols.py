"""Asset and prediction-source selection shared by every page and JSON endpoint."""

from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import Query, Request

from shared.assets import ASSETS, SUPPORTED_SYMBOLS
from shared.db.models import DEFAULT_SYMBOL, PredictionSource

# Unknown symbols fail validation (HTTP 422) instead of silently showing no data.
SymbolQuery = Annotated[
    str,
    Query(
        pattern=f"^({'|'.join(SUPPORTED_SYMBOLS)})$",
        description=f"Asset symbol: {', '.join(SUPPORTED_SYMBOLS)}",
    ),
]


# Invalid values fail validation (HTTP 422) instead of silently showing everything.
SourceQuery = Annotated[
    PredictionSource,
    Query(
        description=(
            "Predictions to include: 'live' (made by the running system), "
            "'replay' (simulated by the history replay) or 'all' (default)"
        ),
    ),
]


_SOURCE_LABELS = {
    PredictionSource.ALL: "All",
    PredictionSource.LIVE: "Live",
    PredictionSource.REPLAY: "Replay",
}


def source_context(request: Request, source: PredictionSource) -> dict[str, Any]:
    """
    Template context for the source selector (live / replay / all).

    Same idea as ``asset_context``: each option links to the same page with only
    ``source`` replaced, so symbol, dates and timeframe survive a switch.
    """
    kept = [(k, v) for k, v in request.query_params.multi_items() if k != "source"]
    return {
        "source": source.value,
        "source_options": [
            {
                "value": option.value,
                "label": label,
                "href": f"?{urlencode([*kept, ('source', option.value)])}",
                "selected": option is source,
            }
            for option, label in _SOURCE_LABELS.items()
        ],
    }


def asset_context(request: Request, symbol: str) -> dict[str, Any]:
    """
    Template context for the asset selector and the selected asset's caveat.

    Each option links to the same page with only ``symbol`` replaced, so the other
    filters (dates, timeframe) survive a switch. Links are relative so they do not
    depend on the scheme or host the app is served behind.

    Args:
        request: Current request, whose query string the links keep
        symbol: Selected symbol, already validated by ``SymbolQuery``

    Returns:
        ``{"asset": Asset, "asset_options": [{"asset", "href", "selected"}]}``
    """
    kept = [(k, v) for k, v in request.query_params.multi_items() if k != "symbol"]
    options = []
    for asset in ASSETS.values():
        options.append(
            {
                "asset": asset,
                "href": f"?{urlencode([*kept, ('symbol', asset.symbol)])}",
                "selected": asset.symbol == symbol,
            }
        )
    return {"asset": ASSETS[symbol], "asset_options": options}


__all__ = [
    "DEFAULT_SYMBOL",
    "SourceQuery",
    "SymbolQuery",
    "asset_context",
    "source_context",
]
