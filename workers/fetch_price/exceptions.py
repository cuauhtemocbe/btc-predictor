"""Custom exceptions for price API clients (Binance, CoinGecko, etc.)."""

from typing import Optional


class PriceAPIError(Exception):
    """Base exception for price API errors.

    All custom price API exceptions inherit from this class.
    Use this to catch any price API-related error from any provider
    (Binance, CoinGecko, etc.).
    """

    pass


class RateLimitError(PriceAPIError):
    """Raised when API returns 429 Too Many Requests.

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


class InvalidSymbolError(PriceAPIError):
    """Raised when API returns error for an invalid trading symbol or coin ID.

    This typically happens when the symbol/coin doesn't exist.
    Examples:
    - Binance: "FOOBAR" instead of "BTCUSDT"
    - CoinGecko: "invalid-coin" instead of "bitcoin"
    """

    pass


# Legacy aliases for backward compatibility with existing code
BinanceAPIError = PriceAPIError
CoinGeckoAPIError = PriceAPIError
