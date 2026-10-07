#!/usr/bin/env python3
"""
Train all ML models with same training data; activation is opt-in.

This script:
1. Fetches historical BTC price data
2. Splits into train/validation sets (70/20/10)
3. Trains the linear model, the only one (#184)
4. Calculates validation error (MAPE) for each
5. Saves all models to database
6. Activates the model with lowest validation error only with --activate;
   otherwise prints the activate_model.py command for it

Usage:
    python scripts/train_all_models.py
    python scripts/train_all_models.py --activate
    docker compose exec api python scripts/train_all_models.py
"""

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

# Add parent directory to path to allow imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.db.database import SessionLocal
from workers.daily.trainer import train_all_models

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    """
    Main entry point for multi-model training script.

    Args:
        argv: Command-line arguments (``sys.argv[1:]`` if None)

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    parser = argparse.ArgumentParser(description="Train every ML model")
    parser.add_argument(
        "--activate",
        action="store_true",
        help="activate the model with the lowest validation error "
        "(off by default: the daily predictor uses the active model)",
    )
    args = parser.parse_args(argv)

    logger.info("=" * 70)
    logger.info("BTC Predictor - Multi-Model Training")
    logger.info("=" * 70)

    session = SessionLocal()

    try:
        # Train all models
        models = train_all_models(session=session, activate=args.activate)

        logger.info("=" * 70)
        logger.info(f"✓ SUCCESS: Trained and saved {len(models)} models")
        if not args.activate:
            best = min(models, key=lambda m: m.params["validation_error_pct"])
            logger.info("No model was activated. To activate the best one, run:")
            logger.info(
                f"  python scripts/activate_model.py --model-id={best.id}"
                f"   # {best.name}"
            )
        logger.info("=" * 70)

        return 0

    except ValueError as e:
        logger.error(f"✗ VALIDATION ERROR: {e}")
        logger.error(
            "Make sure enough daily BTCUSDT prices are stored (see the error above)."
        )
        logger.error("Run: docker compose exec api python -m fetch_price.main")
        return 1

    except Exception as e:
        logger.error(f"✗ UNEXPECTED ERROR: {e}", exc_info=True)
        return 1

    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
