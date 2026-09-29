#!/usr/bin/env python3
"""
Load years of daily price history from data.binance.vision.

Replaces the CoinGecko backfill (30-day limit, no volume). Downloads the monthly
daily-kline zips for each symbol, verifies their SHA256 checksums, and inserts
the rows into ``prices``. Idempotent: rows that already exist are skipped.

Usage:
    # Local
    docker compose exec api python scripts/load_binance_history.py

    # One symbol only, e.g. gold proxy
    docker compose exec api python scripts/load_binance_history.py --symbols PAXGUSDT

    # Check that the host is reachable from Railway (no HTTP 451/403), no DB writes
    railway run -s api python scripts/load_binance_history.py --check

    # Production load
    railway run -s api python scripts/load_binance_history.py
"""

import argparse
import logging
import sys

from shared.binance_vision import (
    SYMBOL_START_MONTH,
    BinanceVisionError,
    check_reachability,
    load_history,
    validate_history,
)
from shared.db.database import SessionLocal

logger = logging.getLogger("load_binance_history")


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load daily price history from data.binance.vision"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=sorted(SYMBOL_START_MONTH),
        choices=sorted(SYMBOL_START_MONTH),
        help="Symbols to load (default: all)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only verify data.binance.vision is reachable; write nothing",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Return 0 on success, 1 on any load or validation error."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )
    args = parse_arguments(argv)

    try:
        if args.check:
            url = check_reachability()
            logger.info("Reachable: %s", url)
            return 0

        with SessionLocal() as session:
            for symbol in args.symbols:
                inserted = load_history(session, symbol)
                validate_history(session, symbol)
                logger.info("%s: %d new rows, series is continuous", symbol, inserted)
        return 0
    except BinanceVisionError as error:
        logger.error("%s", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
