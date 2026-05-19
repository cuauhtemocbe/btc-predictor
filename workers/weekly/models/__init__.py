"""ML models for weekly predictions (shared with daily)."""

# Reuse models from daily worker
from workers.daily.models import BaseModel, LinearRegressionModel

__all__ = ["BaseModel", "LinearRegressionModel"]
