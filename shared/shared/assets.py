"""
Assets the dashboard can show (#107).

Each asset is a stored price series, identified by its Binance symbol. Gold has no
spot series on Binance, so it is shown through PAXGUSDT, a gold-backed token that
trades 24/7: a proxy for gold, not XAU spot.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Asset:
    """An asset the dashboard can switch to.

    Attributes:
        symbol: Binance symbol stored in ``prices.symbol`` and ``models.symbol``.
        label: Short name shown in the selector and headings.
        note: Caveat the UI must state next to this asset's data, or None.
    """

    symbol: str
    label: str
    note: str | None = None


ASSETS: dict[str, Asset] = {
    "BTCUSDT": Asset("BTCUSDT", "Bitcoin"),
    "PAXGUSDT": Asset(
        "PAXGUSDT",
        "Gold",
        note=(
            "Gold is shown as PAXGUSDT, a gold-backed token that trades 24/7 on "
            "Binance. It is a proxy for gold, not XAU spot."
        ),
    ),
}

SUPPORTED_SYMBOLS = tuple(ASSETS)
