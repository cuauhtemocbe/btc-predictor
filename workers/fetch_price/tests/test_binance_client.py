"""Tests for BinanceClient."""

import pytest
import httpx
from datetime import datetime
from fetch_price.binance_client import BinanceClient
from fetch_price.exceptions import (
    BinanceAPIError,
    InvalidSymbolError,
    RateLimitError,
)


class TestParameterValidation:
    """Tests for parameter validation (ZOMBIES edge cases)."""

    def test_limit_zero_raises_value_error(self):
        """ZOMBIES: Zero - limit=0 should raise ValueError."""
        client = BinanceClient()

        with pytest.raises(ValueError, match="limit must be between 1 and 1000"):
            client._validate_params(symbol="BTCUSDT", interval="1h", limit=0)

    def test_limit_negative_raises_value_error(self):
        """ZOMBIES: Negative - limit=-1 should raise ValueError."""
        client = BinanceClient()

        with pytest.raises(ValueError, match="limit must be between 1 and 1000"):
            client._validate_params(symbol="BTCUSDT", interval="1h", limit=-1)

    def test_limit_one_is_valid(self):
        """ZOMBIES: One - limit=1 should be valid."""
        client = BinanceClient()

        # Should not raise
        client._validate_params(symbol="BTCUSDT", interval="1h", limit=1)

    def test_limit_1000_is_valid(self):
        """ZOMBIES: Many - limit=1000 (Binance max) should be valid."""
        client = BinanceClient()

        # Should not raise
        client._validate_params(symbol="BTCUSDT", interval="1h", limit=1000)

    def test_limit_1001_raises_value_error(self):
        """ZOMBIES: Boundary - limit=1001 should raise ValueError."""
        client = BinanceClient()

        with pytest.raises(ValueError, match="limit must be between 1 and 1000"):
            client._validate_params(symbol="BTCUSDT", interval="1h", limit=1001)

    def test_empty_symbol_raises_value_error(self):
        """ZOMBIES: Empty - empty symbol should raise ValueError."""
        client = BinanceClient()

        with pytest.raises(ValueError, match="symbol cannot be empty"):
            client._validate_params(symbol="", interval="1h", limit=1)

    def test_whitespace_only_symbol_raises_value_error(self):
        """ZOMBIES: Edge case - whitespace-only symbol should raise ValueError."""
        client = BinanceClient()

        with pytest.raises(ValueError, match="symbol cannot be empty"):
            client._validate_params(symbol="   ", interval="1h", limit=1)

    def test_empty_interval_raises_value_error(self):
        """ZOMBIES: Empty - empty interval should raise ValueError."""
        client = BinanceClient()

        with pytest.raises(ValueError, match="interval cannot be empty"):
            client._validate_params(symbol="BTCUSDT", interval="", limit=1)

    def test_valid_params_do_not_raise(self):
        """Test that valid parameters pass validation."""
        client = BinanceClient()

        # Should not raise for valid params
        client._validate_params(symbol="BTCUSDT", interval="1h", limit=100)
        client._validate_params(symbol="ETHUSDT", interval="1d", limit=1)
        client._validate_params(symbol="BNBUSDT", interval="5m", limit=1000)


class TestBinanceClientInitialization:
    """Tests for BinanceClient.__init__."""

    def test_can_create_client_with_defaults(self):
        """Test creating client with default parameters."""
        client = BinanceClient()

        assert client.base_url == "https://api.binance.com"
        assert client.timeout == 10.0
        assert isinstance(client._client, httpx.AsyncClient)

    def test_can_create_client_with_custom_base_url(self):
        """Test creating client with custom base URL."""
        custom_url = "https://testnet.binance.vision"
        client = BinanceClient(base_url=custom_url)

        assert client.base_url == custom_url
        assert client.timeout == 10.0

    def test_can_create_client_with_custom_timeout(self):
        """Test creating client with custom timeout."""
        client = BinanceClient(timeout=5.0)

        assert client.base_url == "https://api.binance.com"
        assert client.timeout == 5.0

    def test_can_create_client_with_all_custom_params(self):
        """Test creating client with all custom parameters."""
        client = BinanceClient(
            base_url="https://custom.api",
            timeout=15.0
        )

        assert client.base_url == "https://custom.api"
        assert client.timeout == 15.0

    def test_client_has_httpx_async_client(self):
        """Test that client initializes httpx.AsyncClient."""
        client = BinanceClient()

        assert hasattr(client, "_client")
        assert isinstance(client._client, httpx.AsyncClient)

    def test_httpx_client_configured_with_timeout(self):
        """Test that httpx client is configured with the specified timeout."""
        client = BinanceClient(timeout=7.5)

        # httpx.AsyncClient.timeout can be a Timeout object or float
        assert client._client.timeout.read == 7.5


class TestFetchOHLCV:
    """Tests for fetch_ohlcv method."""

    async def test_fetch_single_candle(self, mocker, sample_binance_response):
        """Test fetching a single candle (latest)."""
        client = BinanceClient()

        # Mock the httpx response
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_binance_response
        mock_response.raise_for_status = mocker.Mock()

        mock_get = mocker.patch.object(client._client, 'get', return_value=mock_response)

        # Call fetch_ohlcv
        result = await client.fetch_ohlcv(symbol="BTCUSDT", interval="1h", limit=1)

        # Verify API was called correctly
        mock_get.assert_called_once_with(
            "/api/v3/klines",
            params={"symbol": "BTCUSDT", "interval": "1h", "limit": 1}
        )

        # Verify result structure
        assert len(result) == 1
        timestamp, open_price, high, low, close, volume = result[0]

        # Verify data types
        assert isinstance(timestamp, datetime)
        assert isinstance(open_price, float)
        assert isinstance(high, float)
        assert isinstance(low, float)
        assert isinstance(close, float)
        assert isinstance(volume, float)

        # Verify values (from sample_binance_response)
        assert open_price == 63000.50
        assert high == 63500.75
        assert low == 62800.25
        assert close == 63200.00
        assert volume == 1234.56789012

    async def test_fetch_multiple_candles(self, mocker, sample_binance_multiple_candles):
        """Test fetching multiple candles (168 for 1 week)."""
        client = BinanceClient()

        # Mock the httpx response
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_binance_multiple_candles
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch.object(client._client, 'get', return_value=mock_response)

        # Call fetch_ohlcv
        result = await client.fetch_ohlcv(symbol="BTCUSDT", interval="1h", limit=3)

        # Verify result structure
        assert len(result) == 3

        # Verify candles are ordered by timestamp descending (newest first)
        timestamps = [candle[0] for candle in result]
        assert timestamps == sorted(timestamps, reverse=True), "Candles not ordered descending"

        # Verify first candle (newest) has correct values
        newest = result[0]
        assert newest[4] == 63500.00  # close price of newest candle

        # Verify last candle (oldest) has correct values
        oldest = result[-1]
        assert oldest[4] == 63200.00  # close price of oldest candle

    async def test_timestamp_converted_to_utc_datetime(self, mocker, sample_binance_response):
        """Test that Unix milliseconds are converted to UTC datetime objects."""
        client = BinanceClient()

        # Mock the httpx response
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_binance_response
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch.object(client._client, 'get', return_value=mock_response)

        result = await client.fetch_ohlcv()

        timestamp = result[0][0]

        # Verify it's a datetime object
        assert isinstance(timestamp, datetime)

        # Verify timezone is UTC (tzinfo should be set)
        from datetime import timezone
        assert timestamp.tzinfo == timezone.utc

        # Verify the timestamp value is correct
        # 1714521600000 ms = 2024-05-01 00:00:00 UTC
        assert timestamp.year == 2024
        assert timestamp.month == 5
        assert timestamp.day == 1
        assert timestamp.hour == 0
        assert timestamp.minute == 0

    async def test_prices_parsed_as_floats(self, mocker, sample_binance_response):
        """Test that price strings are parsed as floats."""
        client = BinanceClient()

        # Mock the httpx response
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_binance_response
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch.object(client._client, 'get', return_value=mock_response)

        result = await client.fetch_ohlcv()

        _, open_price, high, low, close, volume = result[0]

        # All should be floats, not strings
        assert type(open_price) == float
        assert type(high) == float
        assert type(low) == float
        assert type(close) == float
        assert type(volume) == float

        # Verify values are positive
        assert open_price > 0
        assert high > 0
        assert low > 0
        assert close > 0
        assert volume > 0


class TestErrorHandling:
    """Tests for error handling in fetch_ohlcv."""

    async def test_timeout_raises_timeout_error(self, mocker):
        """Test that API timeout raises TimeoutError."""
        client = BinanceClient(timeout=10.0)

        # Mock httpx to raise timeout
        mocker.patch.object(
            client._client,
            'get',
            side_effect=httpx.TimeoutException("Request timed out")
        )

        with pytest.raises(TimeoutError, match="Binance API timeout"):
            await client.fetch_ohlcv()

    async def test_rate_limit_429_raises_rate_limit_error(self, mocker):
        """Test that 429 response raises RateLimitError."""
        client = BinanceClient()

        # Mock 429 response
        mock_response = mocker.Mock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "60"}
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Rate limit exceeded",
            request=mocker.Mock(),
            response=mock_response
        )

        mocker.patch.object(client._client, 'get', return_value=mock_response)

        with pytest.raises(RateLimitError) as exc_info:
            await client.fetch_ohlcv()

        # Verify error message and retry_after
        assert "Rate limit exceeded" in str(exc_info.value)
        assert exc_info.value.retry_after == 60

    async def test_rate_limit_without_retry_after_header(self, mocker):
        """Test that 429 without Retry-After header still raises RateLimitError."""
        client = BinanceClient()

        # Mock 429 response without Retry-After header
        mock_response = mocker.Mock()
        mock_response.status_code = 429
        mock_response.headers = {}
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Rate limit",
            request=mocker.Mock(),
            response=mock_response
        )

        mocker.patch.object(client._client, 'get', return_value=mock_response)

        with pytest.raises(RateLimitError) as exc_info:
            await client.fetch_ohlcv()

        assert exc_info.value.retry_after is None

    async def test_invalid_symbol_400_raises_invalid_symbol_error(self, mocker):
        """Test that 400 response for invalid symbol raises InvalidSymbolError."""
        client = BinanceClient()

        # Mock 400 response
        mock_response = mocker.Mock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"msg": "Invalid symbol."}
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad request",
            request=mocker.Mock(),
            response=mock_response
        )

        mocker.patch.object(client._client, 'get', return_value=mock_response)

        with pytest.raises(InvalidSymbolError, match="Invalid symbol"):
            await client.fetch_ohlcv(symbol="INVALID")

    async def test_server_error_500_raises_binance_api_error(self, mocker):
        """Test that 500 response raises BinanceAPIError."""
        client = BinanceClient()

        # Mock 500 response
        mock_response = mocker.Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Internal server error",
            request=mocker.Mock(),
            response=mock_response
        )

        mocker.patch.object(client._client, 'get', return_value=mock_response)

        with pytest.raises(BinanceAPIError, match="Binance API error"):
            await client.fetch_ohlcv()

    async def test_network_error_raises_binance_api_error(self, mocker):
        """Test that network errors raise BinanceAPIError."""
        client = BinanceClient()

        # Mock network error (connection refused, DNS failure, etc.)
        mocker.patch.object(
            client._client,
            'get',
            side_effect=httpx.ConnectError("Failed to connect")
        )

        with pytest.raises(BinanceAPIError, match="Network error"):
            await client.fetch_ohlcv()

    async def test_http_error_raises_binance_api_error(self, mocker):
        """Test that other HTTP errors (4xx, 5xx) raise BinanceAPIError."""
        client = BinanceClient()

        # Mock 503 Service Unavailable
        mock_response = mocker.Mock()
        mock_response.status_code = 503
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Service unavailable",
            request=mocker.Mock(),
            response=mock_response
        )

        mocker.patch.object(client._client, 'get', return_value=mock_response)

        with pytest.raises(BinanceAPIError):
            await client.fetch_ohlcv()

    async def test_malformed_candle_raises_binance_api_error(self, mocker):
        """Test that malformed API response (missing fields) raises BinanceAPIError.

        This test was added after mutation testing analysis identified that
        malformed Binance responses could cause uncaught IndexErrors.
        Now properly handled with validation.
        """
        client = BinanceClient()

        # Mock response with incomplete candle (only 3 elements instead of 12)
        # Binance normally returns: [open_time, open, high, low, close, volume, ...]
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            [1714521600000, "63000.50", "63500.75"]  # Missing close, volume, etc.
        ]
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch.object(client._client, 'get', return_value=mock_response)

        # Should raise BinanceAPIError with clear error message
        with pytest.raises(BinanceAPIError, match="Malformed candle data"):
            await client.fetch_ohlcv()

    async def test_invalid_price_format_raises_binance_api_error(self, mocker):
        """Test that invalid price data (non-numeric) raises BinanceAPIError.

        This test was added after mutation testing analysis to ensure
        ValueError/TypeError are caught and wrapped properly.
        """
        client = BinanceClient()

        # Mock response with non-numeric price data
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            [1714521600000, "invalid", "63500.75", "62800.25", "63200.00", "1234.56"]
        ]
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch.object(client._client, 'get', return_value=mock_response)

        # Should raise BinanceAPIError (not ValueError)
        with pytest.raises(BinanceAPIError, match="Failed to parse candle data"):
            await client.fetch_ohlcv()
