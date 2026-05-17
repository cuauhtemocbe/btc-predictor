"""CoinGecko API client for fetching OHLCV data."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Tuple

import httpx

from fetch_price.exceptions import (
    PriceAPIError,
    InvalidSymbolError,
    RateLimitError,
)

logger = logging.getLogger(__name__)


class CoinGeckoClient:
    """Async client for CoinGecko Public API (OHLCV data).

    This client fetches historical Bitcoin price data (OHLC - Open, High,
    Low, Close) from CoinGecko's public API without requiring authentication.

    Note: CoinGecko's OHLC endpoint does not include volume data, so volume
    will always be 0.0 in the returned data.

    Example:
        >>> client = CoinGeckoClient()
        >>> data = await client.fetch_ohlcv(coin_id="bitcoin", days=1)
        >>> # Returns ~24 hourly candles for the last day
    """

    def __init__(
        self,
        base_url: str = "https://api.coingecko.com/api/v3",
        timeout: float = 10.0
    ):
        """Initialize CoinGecko API client.

        Args:
            base_url: Base URL for CoinGecko API
                     (default: https://api.coingecko.com/api/v3)
            timeout: Request timeout in seconds (default: 10.0)
        """
        self.base_url = base_url
        self.timeout = timeout
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout)
        )

    def _validate_params(self, coin_id: str, vs_currency: str, days: int) -> None:
        """Validate parameters for fetch_ohlcv.

        Args:
            coin_id: Coin identifier
            vs_currency: Target currency
            days: Number of days of data

        Raises:
            ValueError: If parameters are invalid
        """
        # Validate coin_id
        if not coin_id or not coin_id.strip():
            raise ValueError("coin_id cannot be empty")

        # Validate vs_currency
        if not vs_currency or not vs_currency.strip():
            raise ValueError("vs_currency cannot be empty")

        # Validate days (CoinGecko supports: 1, 7, 14, 30, 90, 180, 365, max)
        valid_days = {1, 7, 14, 30, 90, 180, 365}
        if days not in valid_days:
            raise ValueError(
                f"days must be one of {sorted(valid_days)}, got {days}"
            )

    def _parse_candle(
        self,
        raw_candle: List
    ) -> Tuple[datetime, float, float, float, float, float]:
        """Parse a raw CoinGecko candle into structured OHLCV tuple.

        CoinGecko returns candles as arrays with 5 elements:
        - [0]: Unix timestamp in milliseconds
        - [1]: Open price
        - [2]: High price
        - [3]: Low price
        - [4]: Close price

        Note: Volume is not included, so we set it to 0.0

        Args:
            raw_candle: Raw candle data from CoinGecko API

        Returns:
            Tuple of (timestamp, open, high, low, close, volume)
            Note: volume will always be 0.0

        Raises:
            PriceAPIError: If candle data is malformed
        """
        # Validate candle has required fields
        if len(raw_candle) < 5:
            raise PriceAPIError(
                f"Malformed candle data: expected 5 fields, got {len(raw_candle)}"
            )

        try:
            # Extract and convert timestamp (Unix ms → datetime UTC)
            timestamp_ms = raw_candle[0]
            timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)

            # Extract OHLC (already floats from CoinGecko)
            open_price = float(raw_candle[1])
            high = float(raw_candle[2])
            low = float(raw_candle[3])
            close = float(raw_candle[4])

            # Volume not provided by CoinGecko OHLC endpoint
            volume = 0.0

            return (timestamp, open_price, high, low, close, volume)

        except (ValueError, TypeError) as e:
            raise PriceAPIError(
                f"Failed to parse candle data: {str(e)}"
            ) from e

    async def fetch_ohlcv(
        self,
        coin_id: str = "bitcoin",
        vs_currency: str = "usd",
        days: int = 1,
        max_retries: int = 3
    ) -> List[Tuple[datetime, float, float, float, float, float]]:
        """Fetch OHLCV data from CoinGecko with exponential backoff retry.

        Args:
            coin_id: Coin identifier (default: bitcoin)
            vs_currency: Target currency (default: usd)
            days: Number of days of data (must be: 1, 7, 14, 30, 90, 180, 365)
                 (default: 1 = ~24 hourly candles)
            max_retries: Maximum number of retry attempts on rate limit (default: 3)

        Returns:
            List of tuples: (timestamp, open, high, low, close, volume)
            Ordered by timestamp descending (newest first)
            Note: volume will always be 0.0 (not provided by CoinGecko OHLC)

        Raises:
            ValueError: Invalid parameters
            TimeoutError: API did not respond in time
            RateLimitError: API rate limit exceeded after all retries
            InvalidSymbolError: Invalid coin_id (404)
            PriceAPIError: Other API errors (4xx, 5xx)
        """
        # Validate parameters
        self._validate_params(coin_id, vs_currency, days)

        # Build request parameters
        params = {
            "vs_currency": vs_currency,
            "days": days
        }

        # Retry loop with exponential backoff
        for attempt in range(max_retries + 1):
            try:
                # Make API request
                # Endpoint: /coins/{id}/ohlc
                response = await self._client.get(
                    f"/coins/{coin_id}/ohlc",
                    params=params
                )
                response.raise_for_status()

                # Parse response
                raw_candles = response.json()

                # Parse each candle and order by timestamp descending (newest first)
                candles = [self._parse_candle(raw_candle) for raw_candle in raw_candles]
                candles.sort(key=lambda x: x[0], reverse=True)

                return candles

            except httpx.TimeoutException as e:
                raise TimeoutError(f"CoinGecko API timeout after {self.timeout}s") from e

            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code

                # Handle rate limit (429) with exponential backoff
                if status_code == 429:
                    retry_after = e.response.headers.get("Retry-After")

                    # If this was the last attempt, raise the error
                    if attempt >= max_retries:
                        retry_after_int = int(retry_after) if retry_after else None
                        raise RateLimitError(
                            f"Rate limit exceeded after {max_retries} retries. "
                            "Please wait before retrying.",
                            retry_after=retry_after_int
                        ) from e

                    # Calculate backoff delay
                    if retry_after:
                        # Use server's Retry-After header if available
                        delay = int(retry_after)
                    else:
                        # Exponential backoff: 5s, 10s, 20s, 40s, ...
                        delay = 5 * (2 ** attempt)

                    logger.warning(
                        f"Rate limit hit (attempt {attempt + 1}/{max_retries + 1}). "
                        f"Waiting {delay}s before retry..."
                    )
                    await asyncio.sleep(delay)
                    continue  # Retry the request

                # Handle invalid coin_id (404)
                elif status_code == 404:
                    raise InvalidSymbolError(
                        f"Invalid coin_id: {coin_id}. Please check the coin identifier."
                    ) from e

                # Handle other HTTP errors (500, 503, etc.)
                else:
                    raise PriceAPIError(
                        f"CoinGecko API error (HTTP {status_code}): {str(e)}"
                    ) from e

            except httpx.ConnectError as e:
                raise PriceAPIError(
                    f"Network error: Could not connect to CoinGecko API. {str(e)}"
                ) from e

            except httpx.HTTPError as e:
                # Catch-all for other httpx errors
                raise PriceAPIError(
                    f"HTTP error while fetching data from CoinGecko: {str(e)}"
                ) from e

        # Should never reach here, but just in case
        raise PriceAPIError("Unexpected error: retry loop completed without returning")
