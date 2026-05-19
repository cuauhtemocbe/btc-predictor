#!/usr/bin/env python3
"""
List all trained ML models with their metrics.

Displays a table showing:
- ID
- Name
- Version
- Active status
- Validation error
- Training date

Usage:
    python scripts/list_models.py
    docker compose exec api python scripts/list_models.py
"""

import logging
import sys
from pathlib import Path

# Add parent directory to path to allow imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.db.crud import get_all_models
from shared.db.database import SessionLocal

# Configure logging
logging.basicConfig(
    level=logging.WARNING,  # Only show warnings/errors for cleaner output
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def format_validation_error(params: dict) -> str:
    """Format validation error from params dict."""
    if "validation_error_pct" in params:
        return f"{params['validation_error_pct']:.2f}%"
    return "N/A"


def main() -> int:
    """
    Main entry point for list models script.

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    session = SessionLocal()

    try:
        # Fetch all models
        models = get_all_models(session)

        if not models:
            print("=" * 90)
            print("No models found in database.")
            print("=" * 90)
            print("Run 'python scripts/train_all_models.py' to train models.")
            return 0

        # Display table header
        print("=" * 110)
        header = (
            f"{'ID':<5} {'Name':<20} {'Version':<10} {'Active':<8} "
            f"{'Val Error':<12} {'Trained At':<25}"
        )
        print(header)
        print("=" * 110)

        # Display each model
        for model in models:
            active_marker = "✓ Yes" if model.is_active else "No"
            val_error = format_validation_error(model.params)
            trained_at = model.trained_at.strftime("%Y-%m-%d %H:%M:%S")

            print(
                f"{model.id:<5} "
                f"{model.name:<20} "
                f"{model.version:<10} "
                f"{active_marker:<8} "
                f"{val_error:<12} "
                f"{trained_at:<25}"
            )

        print("=" * 110)
        print(f"Total: {len(models)} model(s)")
        print("=" * 110)

        # Show active model summary
        active_models = [m for m in models if m.is_active]
        if active_models:
            active = active_models[0]
            print("\nCurrently active model:")
            print(f"  • {active.name} (ID: {active.id})")
            print(f"  • Validation Error: {format_validation_error(active.params)}")
            print(f"  • Trained: {active.trained_at.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            print("\n⚠ WARNING: No active model!")
            msg = (
                "Run 'python scripts/activate_model.py --model-id=X' "
                "to activate a model."
            )
            print(msg)

        print()

        return 0

    except Exception as e:
        logger.error(f"✗ UNEXPECTED ERROR: {e}", exc_info=True)
        return 1

    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
