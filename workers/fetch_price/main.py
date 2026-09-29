"""
Fetch Price Job - Main Entry Point

Ingests the closed daily bar (UTC) of every supported symbol from Binance:
the ``daily/`` file of data.binance.vision first, the REST klines endpoint if the
file is not published yet. Only closed days are stored; days missed by earlier
runs are backfilled.
"""

import logging
import sys

from shared.binance_vision import SYMBOL_START_MONTH, BinanceVisionError, ingest_new_days
from shared.db.database import SessionLocal

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


def main() -> int:
    """
    Main entry point for fetch_price job.

    Every symbol is attempted even if an earlier one fails, so one broken
    source does not block the others.

    Returns:
        Exit code: 0 for success, 1 if any symbol failed
    """
    logger.info("Fetch price job starting")
    failed = []
    with SessionLocal() as session:
        for symbol in sorted(SYMBOL_START_MONTH):
            try:
                inserted = ingest_new_days(session, symbol)
                logger.info("%s: %d new bars", symbol, inserted)
            except BinanceVisionError as error:
                session.rollback()
                logger.error("%s ingestion failed: %s", symbol, error)
                failed.append(symbol)
            except Exception:
                session.rollback()
                logger.exception("%s ingestion crashed", symbol)
                failed.append(symbol)
    if failed:
        logger.error("Job failed for: %s", ", ".join(failed))
        return 1
    logger.info("Job completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
