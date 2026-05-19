#!/usr/bin/env python3
"""
Train all ML models with same training data and auto-activate best.

This script:
1. Fetches historical BTC price data
2. Splits into train/validation sets (70/20/10)
3. Trains all 4 models (Linear, LSTM, XGBoost, ARIMA)
4. Calculates validation error (MAPE) for each
5. Saves all models to database
6. Automatically activates the model with lowest validation error

Usage:
    python scripts/train_all_models.py
    docker compose exec api python scripts/train_all_models.py
"""

import logging
import sys
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


def main() -> int:
    """
    Main entry point for multi-model training script.

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    logger.info("=" * 70)
    logger.info("BTC Predictor - Multi-Model Training")
    logger.info("=" * 70)

    session = SessionLocal()

    try:
        # Train all models
        models = train_all_models(
            session=session,
            window_days=30,  # 30-day sliding window
            min_days=90,  # Need 90 days for ARIMA and validation split
        )

        logger.info("=" * 70)
        logger.info(f"✓ SUCCESS: Trained and saved {len(models)} models")
        logger.info("=" * 70)

        return 0

    except ValueError as e:
        logger.error(f"✗ VALIDATION ERROR: {e}")
        logger.error("Make sure you have at least 90 days of historical BTC prices.")
        logger.error("Run: docker compose exec api python -m fetch_price.main")
        return 1

    except Exception as e:
        logger.error(f"✗ UNEXPECTED ERROR: {e}", exc_info=True)
        return 1

    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
