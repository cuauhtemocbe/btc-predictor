"""Binance API client for fetching OHLCV data."""

from datetime import datetime, timezone
from typing import List, Tuple

import httpx

from fetch_price.exceptions import (
    BinanceAPIError,
    InvalidSymbolError,
    RateLimitError,
)


class BinanceClient:
    """Async client for Binance Public API (OHLCV data).

    This client fetches historical and recent Bitcoin price data (OHLCV - Open, High,
    Low, Close, Volume) from Binance's public API without requiring authentication.

    Example:
        >>> client = BinanceClient()
        >>> data = await client.fetch_ohlcv(symbol="BTCUSDT", interval="1h", limit=24)
        >>> # Returns 24 hourly candles
    """

    def __init__(self, base_url: str = "https://api.binance.com", timeout: float = 10.0):
        """Initialize Binance API client.

        Args:
            base_url: Base URL for Binance API (default: https://api.binance.com)
                     Use https://testnet.binance.vision for testing
            timeout: Request timeout in seconds (default: 10.0)
        """
        self.base_url = base_url
        self.timeout = timeout
        self._client = httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(timeout))

    def _validate_params(self, symbol: str, interval: str, limit: int) -> None:
        """Validate parameters for fetch_ohlcv.

        Args:
            symbol: Trading pair
            interval: Candle interval
            limit: Number of candles to fetch

        Raises:
            ValueError: If parameters are invalid
        """
        # Validate symbol
        if not symbol or not symbol.strip():
            raise ValueError("symbol cannot be empty")

        # Validate interval
        if not interval or not interval.strip():
            raise ValueError("interval cannot be empty")

        # Validate limit (Binance allows 1-1000)
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")

    def _parse_candle(self, raw_candle: List) -> Tuple[datetime, float, float, float, float, float]:
        """Parse a raw Binance candle into structured OHLCV tuple.

        Binance returns candles as arrays with 12 elements. We extract:
        - [0]: Kline open time (Unix ms) → datetime UTC
        - [1]: Open price (string) → float
        - [2]: High price (string) → float
        - [3]: Low price (string) → float
        - [4]: Close price (string) → float
        - [5]: Volume (string) → float

        Args:
            raw_candle: Raw candle data from Binance API

        Returns:
            Tuple of (timestamp, open, high, low, close, volume)

        Raises:
            BinanceAPIError: If candle data is malformed (missing required fields)
        """
        # Validate candle has minimum required fields
        if len(raw_candle) < 6:
            raise BinanceAPIError(
                f"Malformed candle data: expected at least 6 fields, got {len(raw_candle)}"
            )

        try:
            # Extract and convert timestamp (Unix ms → datetime UTC)
            timestamp_ms = raw_candle[0]
            timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)

            # Extract and parse OHLCV (strings → floats)
            open_price = float(raw_candle[1])
            high = float(raw_candle[2])
            low = float(raw_candle[3])
            close = float(raw_candle[4])
            volume = float(raw_candle[5])

            return (timestamp, open_price, high, low, close, volume)

        except (ValueError, TypeError) as e:
            raise BinanceAPIError(f"Failed to parse candle data: {str(e)}") from e

    async def fetch_ohlcv(
        self, symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 1
    ) -> List[Tuple[datetime, float, float, float, float, float]]:
        """Fetch OHLCV data from Binance.

        Args:
            symbol: Trading pair (default: BTCUSDT)
            interval: Candle interval (1m, 5m, 1h, 1d, etc.) (default: 1h)
            limit: Number of candles to fetch, 1-1000 (default: 1)

        Returns:
            List of tuples: (timestamp, open, high, low, close, volume)
            Ordered by timestamp descending (newest first)

        Raises:
            ValueError: Invalid parameters (limit out of range, empty symbol)
            TimeoutError: API did not respond in time
            RateLimitError: API rate limit exceeded (429)
            InvalidSymbolError: Invalid trading symbol (400)
            BinanceAPIError: Other API errors (4xx, 5xx)
        """
        # Validate parameters
        self._validate_params(symbol, interval, limit)

        # Build request parameters
        params = {"symbol": symbol, "interval": interval, "limit": limit}

        try:
            # Make API request
            response = await self._client.get("/api/v3/klines", params=params)
            response.raise_for_status()

            # Parse response
            raw_candles = response.json()

            # Parse each candle and order by timestamp descending (newest first)
            candles = [self._parse_candle(raw_candle) for raw_candle in raw_candles]
            candles.sort(key=lambda x: x[0], reverse=True)

            return candles

        except httpx.TimeoutException as e:
            raise TimeoutError(f"Binance API timeout after {self.timeout}s") from e

        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code

            # Handle rate limit (429)
            if status_code == 429:
                retry_after = e.response.headers.get("Retry-After")
                retry_after_int = int(retry_after) if retry_after else None
                raise RateLimitError(
                    "Rate limit exceeded. Please wait before retrying.", retry_after=retry_after_int
                ) from e

            # Handle invalid symbol (400)
            elif status_code == 400:
                raise InvalidSymbolError(
                    f"Invalid symbol: {symbol}. Please check the symbol name."
                ) from e

            # Handle other HTTP errors (500, 503, etc.)
            else:
                raise BinanceAPIError(f"Binance API error (HTTP {status_code}): {str(e)}") from e

        except httpx.ConnectError as e:
            raise BinanceAPIError(
                f"Network error: Could not connect to Binance API. {str(e)}"
            ) from e

        except httpx.HTTPError as e:
            # Catch-all for other httpx errors
            raise BinanceAPIError(f"HTTP error while fetching data from Binance: {str(e)}") from e
