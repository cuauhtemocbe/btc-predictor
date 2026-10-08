"""Interface of every model; the trainer, predictor and backtest use only this."""

from abc import ABC, abstractmethod

import numpy as np
import numpy.typing as npt


class BaseModel(ABC):
    """Abstract model: train, predict, serialize, deserialize and a trained flag."""

    @abstractmethod
    def train(self, X: npt.NDArray[np.float64], y: npt.NDArray[np.float64]) -> None:
        """Fit on a feature matrix and a target vector.

        Args:
            X: Features, shape (n_samples, n_features).
            y: Targets, shape (n_samples,).

        Raises:
            ValueError: If the shapes are invalid or X or y hold NaN or infinite values.
        """
        pass

    @abstractmethod
    def predict(self, X: npt.NDArray[np.float64]) -> float:
        """Predict the target for one sample.

        Args:
            X: One sample, shape (n_features,) or (1, n_features).

        Raises:
            ValueError: If the model is untrained or X has an invalid shape.
        """
        pass

    @abstractmethod
    def serialize(self) -> bytes:
        """Return the bytes stored in ``models.artifact`` (BYTEA).

        The bytes hold the trained parameters, the configuration and the trained flag.

        Raises:
            RuntimeError: If serialization fails.
        """
        pass

    @classmethod
    @abstractmethod
    def deserialize(cls, data: bytes) -> "BaseModel":
        """Rebuild a model from the bytes ``serialize`` returned.

        Raises:
            ValueError: If the data is corrupted or invalid.
            pickle.UnpicklingError: If unpickling fails.
        """
        pass

    @property
    @abstractmethod
    def is_trained(self) -> bool:
        """True once trained; ``predict`` raises before that."""
        pass
