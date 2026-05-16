"""Custom exceptions for Binance API client."""

from typing import Optional


class BinanceAPIError(Exception):
    """Base exception for Binance API errors.

    All custom Binance exceptions inherit from this class.
    Use this to catch any Binance-related error.
    """

    pass


class RateLimitError(BinanceAPIError):
    """Raised when Binance API returns 429 Too Many Requests.

    Attributes:
        retry_after: Optional number of seconds to wait before retrying
                    (from Retry-After header if present)
    """

    def __init__(self, message: str, retry_after: Optional[int] = None):
        """Initialize RateLimitError.

        Args:
            message: Error message
            retry_after: Optional seconds to wait before retry
        """
        super().__init__(message)
        self.retry_after = retry_after


class InvalidSymbolError(BinanceAPIError):
    """Raised when Binance API returns 400 for an invalid trading symbol.

    This typically happens when the symbol doesn't exist on Binance
    (e.g., "FOOBAR" instead of "BTCUSDT").
    """

    pass
