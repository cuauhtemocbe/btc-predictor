#!/usr/bin/env python3
"""
Activate a specific model by ID.

This script allows you to manually activate a trained model,
deactivating all other models. Only ONE model can be active at a time.

Usage:
    python scripts/activate_model.py --model-id=42
    docker compose exec api python scripts/activate_model.py --model-id=42

Example:
    # List all models first
    python scripts/list_models.py

    # Activate model with ID 5
    python scripts/activate_model.py --model-id=5
"""

import argparse
import logging
import sys
from pathlib import Path

# Add parent directory to path to allow imports
sys.path.insert(0, str(Path(__file__).parent.parent))


from shared.db.crud import activate_model
from shared.db.database import SessionLocal

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    """
    Main entry point for model activation script.

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    # Parse arguments
    parser = argparse.ArgumentParser(description="Activate a specific ML model by ID")
    parser.add_argument(
        "--model-id",
        type=int,
        required=True,
        help="ID of the model to activate (get from list_models.py)",
    )
    args = parser.parse_args()

    model_id = args.model_id

    logger.info("=" * 70)
    logger.info(f"BTC Predictor - Activate Model #{model_id}")
    logger.info("=" * 70)

    session = SessionLocal()

    try:
        # Activate the model (commits internally, scoped to its timeframe)
        activated_model = activate_model(session, model_id)

        logger.info("=" * 70)
        logger.info("✓ SUCCESS")
        logger.info(f"  Model ID:  {activated_model.id}")
        logger.info(f"  Name:      {activated_model.name}")
        logger.info(f"  Version:   {activated_model.version}")
        logger.info(f"  Trained:   {activated_model.trained_at}")

        # Show validation error if available
        if "validation_error_pct" in activated_model.params:
            val_error = activated_model.params["validation_error_pct"]
            logger.info(f"  Val Error: {val_error}%")

        logger.info("=" * 70)
        logger.info("All other models have been deactivated.")
        logger.info("This model will now be used for predictions.")
        logger.info("=" * 70)

        return 0

    except ValueError as e:
        logger.error(f"✗ ERROR: {e}")
        logger.error(f"Model with ID={model_id} does not exist.")
        logger.error("Run 'python scripts/list_models.py' to see available models.")
        return 1

    except Exception as e:
        logger.error(f"✗ UNEXPECTED ERROR: {e}", exc_info=True)
        return 1

    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
