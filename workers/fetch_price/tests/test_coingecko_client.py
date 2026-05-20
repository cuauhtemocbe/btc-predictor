"""Tests for CoinGeckoClient."""

from datetime import datetime, timezone

import httpx
import pytest

from fetch_price.coingecko_client import CoinGeckoClient
from fetch_price.exceptions import (
    InvalidSymbolError,
    PriceAPIError,
    RateLimitError,
)


@pytest.fixture
def sample_coingecko_response():
    """Sample CoinGecko OHLC API response (1 candle).

    Format: [[timestamp_ms, open, high, low, close], ...]
    """
    return [[1714521600000, 63000.50, 63500.75, 62800.25, 63200.00]]


@pytest.fixture
def sample_coingecko_multiple_candles():
    """Sample CoinGecko response with multiple candles."""
    return [
        [1714521600000, 63000.50, 63500.75, 62800.25, 63200.00],
        [1714525200000, 63200.00, 63800.00, 63100.00, 63400.00],
        [1714528800000, 63400.00, 64000.00, 63300.00, 63500.00],
    ]


class TestParameterValidation:
    """Tests for parameter validation (ZOMBIES edge cases)."""

    def test_days_invalid_raises_value_error(self):
        """ZOMBIES: Invalid days value should raise ValueError."""
        client = CoinGeckoClient()

        with pytest.raises(ValueError, match="days must be one of"):
            client._validate_params(coin_id="bitcoin", vs_currency="usd", days=5)

    def test_days_zero_raises_value_error(self):
        """ZOMBIES: Zero - days=0 should raise ValueError."""
        client = CoinGeckoClient()

        with pytest.raises(ValueError, match="days must be one of"):
            client._validate_params(coin_id="bitcoin", vs_currency="usd", days=0)

    def test_days_negative_raises_value_error(self):
        """ZOMBIES: Negative - days=-1 should raise ValueError."""
        client = CoinGeckoClient()

        with pytest.raises(ValueError, match="days must be one of"):
            client._validate_params(coin_id="bitcoin", vs_currency="usd", days=-1)

    def test_days_1_is_valid(self):
        """ZOMBIES: One - days=1 should be valid."""
        client = CoinGeckoClient()

        # Should not raise
        client._validate_params(coin_id="bitcoin", vs_currency="usd", days=1)

    def test_days_7_is_valid(self):
        """ZOMBIES: Many - days=7 should be valid."""
        client = CoinGeckoClient()

        # Should not raise
        client._validate_params(coin_id="bitcoin", vs_currency="usd", days=7)

    def test_days_365_is_valid(self):
        """ZOMBIES: Boundary - days=365 (max) should be valid."""
        client = CoinGeckoClient()

        # Should not raise
        client._validate_params(coin_id="bitcoin", vs_currency="usd", days=365)

    def test_days_366_raises_value_error(self):
        """ZOMBIES: Boundary - days=366 should raise ValueError."""
        client = CoinGeckoClient()

        with pytest.raises(ValueError, match="days must be one of"):
            client._validate_params(coin_id="bitcoin", vs_currency="usd", days=366)

    def test_empty_coin_id_raises_value_error(self):
        """ZOMBIES: Empty - empty coin_id should raise ValueError."""
        client = CoinGeckoClient()

        with pytest.raises(ValueError, match="coin_id cannot be empty"):
            client._validate_params(coin_id="", vs_currency="usd", days=1)

    def test_whitespace_only_coin_id_raises_value_error(self):
        """ZOMBIES: Edge case - whitespace-only coin_id should raise ValueError."""
        client = CoinGeckoClient()

        with pytest.raises(ValueError, match="coin_id cannot be empty"):
            client._validate_params(coin_id="   ", vs_currency="usd", days=1)

    def test_empty_vs_currency_raises_value_error(self):
        """ZOMBIES: Empty - empty vs_currency should raise ValueError."""
        client = CoinGeckoClient()

        with pytest.raises(ValueError, match="vs_currency cannot be empty"):
            client._validate_params(coin_id="bitcoin", vs_currency="", days=1)

    def test_valid_params_do_not_raise(self):
        """Test that valid parameters pass validation."""
        client = CoinGeckoClient()

        # Should not raise for valid params
        client._validate_params(coin_id="bitcoin", vs_currency="usd", days=1)
        client._validate_params(coin_id="ethereum", vs_currency="eur", days=7)
        client._validate_params(coin_id="bitcoin", vs_currency="gbp", days=365)


class TestCoinGeckoClientInitialization:
    """Tests for CoinGeckoClient.__init__."""

    def test_can_create_client_with_defaults(self):
        """Test creating client with default parameters."""
        client = CoinGeckoClient()

        assert client.base_url == "https://api.coingecko.com/api/v3"
        assert client.timeout == 10.0
        assert isinstance(client._client, httpx.AsyncClient)

    def test_can_create_client_with_custom_base_url(self):
        """Test creating client with custom base URL."""
        custom_url = "https://custom.coingecko.api"
        client = CoinGeckoClient(base_url=custom_url)

        assert client.base_url == custom_url
        assert client.timeout == 10.0

    def test_can_create_client_with_custom_timeout(self):
        """Test creating client with custom timeout."""
        client = CoinGeckoClient(timeout=5.0)

        assert client.base_url == "https://api.coingecko.com/api/v3"
        assert client.timeout == 5.0

    def test_can_create_client_with_all_custom_params(self):
        """Test creating client with all custom parameters."""
        client = CoinGeckoClient(base_url="https://custom.api", timeout=15.0)

        assert client.base_url == "https://custom.api"
        assert client.timeout == 15.0

    def test_client_has_httpx_async_client(self):
        """Test that client initializes httpx.AsyncClient."""
        client = CoinGeckoClient()

        assert hasattr(client, "_client")
        assert isinstance(client._client, httpx.AsyncClient)

    def test_httpx_client_configured_with_timeout(self):
        """Test that httpx client is configured with the specified timeout."""
        client = CoinGeckoClient(timeout=7.5)

        # httpx.AsyncClient.timeout can be a Timeout object or float
        assert client._client.timeout.read == 7.5


class TestFetchOHLCV:
    """Tests for fetch_ohlcv method."""

    async def test_fetch_single_day(self, mocker, sample_coingecko_response):
        """Test fetching 1 day of data (~24 hourly candles)."""
        client = CoinGeckoClient()

        # Mock the httpx response
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_coingecko_response
        mock_response.raise_for_status = mocker.Mock()

        mock_get = mocker.patch.object(client._client, "get", return_value=mock_response)

        # Call fetch_ohlcv
        result = await client.fetch_ohlcv(coin_id="bitcoin", vs_currency="usd", days=1)

        # Verify API was called correctly
        mock_get.assert_called_once_with(
            "/coins/bitcoin/ohlc", params={"vs_currency": "usd", "days": 1}
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

        # Verify values (from sample_coingecko_response)
        assert open_price == 63000.50
        assert high == 63500.75
        assert low == 62800.25
        assert close == 63200.00

        # CoinGecko OHLC doesn't include volume
        assert volume == 0.0

    async def test_fetch_multiple_candles(self, mocker, sample_coingecko_multiple_candles):
        """Test fetching multiple candles."""
        client = CoinGeckoClient()

        # Mock the httpx response
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_coingecko_multiple_candles
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch.object(client._client, "get", return_value=mock_response)

        # Call fetch_ohlcv
        result = await client.fetch_ohlcv(coin_id="bitcoin", vs_currency="usd", days=1)

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

        # Verify all candles have volume=0.0
        for candle in result:
            assert candle[5] == 0.0, "Volume should be 0.0 for CoinGecko OHLC"

    async def test_timestamp_converted_to_utc_datetime(self, mocker, sample_coingecko_response):
        """Test that Unix milliseconds are converted to UTC datetime objects."""
        client = CoinGeckoClient()

        # Mock the httpx response
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_coingecko_response
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch.object(client._client, "get", return_value=mock_response)

        result = await client.fetch_ohlcv()

        timestamp = result[0][0]

        # Verify it's a datetime object
        assert isinstance(timestamp, datetime)

        # Verify timezone is UTC (tzinfo should be set)
        assert timestamp.tzinfo == timezone.utc

        # Verify the timestamp value is correct
        # 1714521600000 ms = 2024-05-01 00:00:00 UTC
        assert timestamp.year == 2024
        assert timestamp.month == 5
        assert timestamp.day == 1
        assert timestamp.hour == 0
        assert timestamp.minute == 0

    async def test_prices_parsed_as_floats(self, mocker, sample_coingecko_response):
        """Test that price values are parsed as floats."""
        client = CoinGeckoClient()

        # Mock the httpx response
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_coingecko_response
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch.object(client._client, "get", return_value=mock_response)

        result = await client.fetch_ohlcv()

        _, open_price, high, low, close, volume = result[0]

        # All should be floats
        assert isinstance(open_price, float)
        assert isinstance(high, float)
        assert isinstance(low, float)
        assert isinstance(close, float)
        assert isinstance(volume, float)

    async def test_volume_always_zero(self, mocker, sample_coingecko_response):
        """Test that volume is always 0.0 (CoinGecko OHLC doesn't include volume)."""
        client = CoinGeckoClient()

        # Mock the httpx response
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_coingecko_response
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch.object(client._client, "get", return_value=mock_response)

        result = await client.fetch_ohlcv()

        volume = result[0][5]

        assert volume == 0.0


class TestErrorHandling:
    """Tests for error handling (ZOMBIES: Exceptions)."""

    async def test_timeout_raises_timeout_error(self, mocker):
        """Test that httpx timeout raises TimeoutError."""
        client = CoinGeckoClient(timeout=5.0)

        # Mock timeout exception
        mocker.patch.object(
            client._client, "get", side_effect=httpx.TimeoutException("Request timeout")
        )

        with pytest.raises(TimeoutError, match="CoinGecko API timeout after 5.0s"):
            await client.fetch_ohlcv()

    async def test_rate_limit_429_raises_rate_limit_error(self, mocker):
        """Test that HTTP 429 raises RateLimitError."""
        client = CoinGeckoClient()

        # Mock 429 response
        mock_response = mocker.Mock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "60"}

        mock_get = mocker.patch.object(
            client._client,
            "get",
            side_effect=httpx.HTTPStatusError(
                "Rate limit exceeded", request=mocker.Mock(), response=mock_response
            ),
        )

        with pytest.raises(RateLimitError, match="Rate limit exceeded"):
            await client.fetch_ohlcv()

    async def test_invalid_coin_id_404_raises_invalid_symbol_error(self, mocker):
        """Test that HTTP 404 raises InvalidSymbolError."""
        client = CoinGeckoClient()

        # Mock 404 response
        mock_response = mocker.Mock()
        mock_response.status_code = 404

        mocker.patch.object(
            client._client,
            "get",
            side_effect=httpx.HTTPStatusError(
                "Not found", request=mocker.Mock(), response=mock_response
            ),
        )

        with pytest.raises(InvalidSymbolError, match="Invalid coin_id"):
            await client.fetch_ohlcv(coin_id="invalid-coin")

    async def test_server_error_500_raises_price_api_error(self, mocker):
        """Test that HTTP 500 raises PriceAPIError."""
        client = CoinGeckoClient()

        # Mock 500 response
        mock_response = mocker.Mock()
        mock_response.status_code = 500

        mocker.patch.object(
            client._client,
            "get",
            side_effect=httpx.HTTPStatusError(
                "Internal server error", request=mocker.Mock(), response=mock_response
            ),
        )

        with pytest.raises(PriceAPIError, match="CoinGecko API error \\(HTTP 500\\)"):
            await client.fetch_ohlcv()

    async def test_network_error_raises_price_api_error(self, mocker):
        """Test that network connection error raises PriceAPIError."""
        client = CoinGeckoClient()

        # Mock connection error
        mocker.patch.object(
            client._client, "get", side_effect=httpx.ConnectError("Could not connect")
        )

        with pytest.raises(PriceAPIError, match="Network error"):
            await client.fetch_ohlcv()

    async def test_malformed_candle_less_than_5_fields_raises_error(self, mocker):
        """Test that malformed candle data (< 5 fields) raises PriceAPIError."""
        client = CoinGeckoClient()

        # Mock response with malformed candle (only 3 fields instead of 5)
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            [1714521600000, 63000.50, 63500.75]  # Missing low and close
        ]
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch.object(client._client, "get", return_value=mock_response)

        with pytest.raises(PriceAPIError, match="Malformed candle data: expected 5 fields"):
            await client.fetch_ohlcv()

    async def test_malformed_candle_invalid_types_raises_error(self, mocker):
        """Test that malformed candle data (invalid types) raises PriceAPIError."""
        client = CoinGeckoClient()

        # Mock response with invalid data types
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            [1714521600000, "not_a_number", 63500.75, 62800.25, 63200.00]
        ]
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch.object(client._client, "get", return_value=mock_response)

        with pytest.raises(PriceAPIError, match="Failed to parse candle data"):
            await client.fetch_ohlcv()


class TestDefaultParameters:
    """Tests for default parameter values."""

    async def test_fetch_with_all_defaults(self, mocker, sample_coingecko_response):
        """Test that fetch_ohlcv works with all default parameters."""
        client = CoinGeckoClient()

        # Mock the httpx response
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_coingecko_response
        mock_response.raise_for_status = mocker.Mock()

        mock_get = mocker.patch.object(client._client, "get", return_value=mock_response)

        # Call with defaults (bitcoin, usd, 1 day)
        result = await client.fetch_ohlcv()

        # Verify defaults were used
        mock_get.assert_called_once_with(
            "/coins/bitcoin/ohlc", params={"vs_currency": "usd", "days": 1}
        )

        assert len(result) == 1

    async def test_fetch_with_custom_coin_id(self, mocker, sample_coingecko_response):
        """Test fetching with custom coin_id."""
        client = CoinGeckoClient()

        # Mock the httpx response
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_coingecko_response
        mock_response.raise_for_status = mocker.Mock()

        mock_get = mocker.patch.object(client._client, "get", return_value=mock_response)

        # Call with custom coin_id
        await client.fetch_ohlcv(coin_id="ethereum")

        # Verify custom coin_id was used in URL
        mock_get.assert_called_once_with(
            "/coins/ethereum/ohlc", params={"vs_currency": "usd", "days": 1}
        )


class TestFetchHistoricalPrices:
    """Tests for fetch_historical_prices method (market_chart endpoint)."""

    @pytest.fixture
    def sample_market_chart_response(self):
        """Sample CoinGecko market_chart API response.

        Format: {"prices": [[timestamp_ms, price], ...], ...}
        """
        return {
            "prices": [
                [1714521600000, 63000.50],
                [1714525200000, 63200.00],
                [1714528800000, 63400.00],
            ],
            "market_caps": [[1714521600000, 1234567890]],
            "total_volumes": [[1714521600000, 9876543210]],
        }

    async def test_fetch_90_days_default(self, mocker, sample_market_chart_response):
        """Test fetching 90 days of historical data (default)."""
        client = CoinGeckoClient()

        # Mock the httpx response
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_market_chart_response
        mock_response.raise_for_status = mocker.Mock()

        mock_get = mocker.patch.object(client._client, "get", return_value=mock_response)

        # Call fetch_historical_prices with default (90 days)
        result = await client.fetch_historical_prices()

        # Verify API was called correctly
        mock_get.assert_called_once_with(
            "/coins/bitcoin/market_chart",
            params={"vs_currency": "usd", "days": 90, "interval": "hourly"},
        )

        # Verify result structure
        assert len(result) == 3
        timestamp, price = result[0]

        # Verify data types
        assert isinstance(timestamp, datetime)
        assert isinstance(price, float)

        # Verify values
        assert price == 63000.50

    async def test_fetch_custom_days(self, mocker, sample_market_chart_response):
        """Test fetching custom number of days."""
        client = CoinGeckoClient()

        # Mock the httpx response
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_market_chart_response
        mock_response.raise_for_status = mocker.Mock()

        mock_get = mocker.patch.object(client._client, "get", return_value=mock_response)

        # Call with custom days (7 days)
        await client.fetch_historical_prices(days=7)

        # Verify API was called with correct days parameter
        mock_get.assert_called_once_with(
            "/coins/bitcoin/market_chart",
            params={"vs_currency": "usd", "days": 7, "interval": "hourly"},
        )

    async def test_prices_sorted_ascending(self, mocker):
        """Test that prices are sorted by timestamp ascending (oldest first)."""
        client = CoinGeckoClient()

        # Mock response with unsorted prices
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "prices": [
                [1714528800000, 63400.00],  # Newest
                [1714521600000, 63000.50],  # Oldest
                [1714525200000, 63200.00],  # Middle
            ]
        }
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch.object(client._client, "get", return_value=mock_response)

        result = await client.fetch_historical_prices()

        # Verify sorted ascending (oldest first)
        timestamps = [ts for ts, _ in result]
        assert timestamps == sorted(timestamps), "Prices should be sorted ascending"

        # Verify oldest is first
        assert result[0][1] == 63000.50
        # Verify newest is last
        assert result[-1][1] == 63400.00

    async def test_empty_response_returns_empty_list(self, mocker):
        """Test that empty prices array returns empty list."""
        client = CoinGeckoClient()

        # Mock empty response
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"prices": []}
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch.object(client._client, "get", return_value=mock_response)

        result = await client.fetch_historical_prices()

        assert result == []

    async def test_rate_limit_with_exponential_backoff(self, mocker):
        """Test that rate limit (429) triggers exponential backoff."""
        client = CoinGeckoClient()

        # Mock 429 response (all retries fail)
        mock_response = mocker.Mock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "10"}

        mocker.patch.object(
            client._client,
            "get",
            side_effect=httpx.HTTPStatusError(
                "Rate limit exceeded", request=mocker.Mock(), response=mock_response
            ),
        )

        # Mock asyncio.sleep to verify backoff
        mock_sleep = mocker.patch("fetch_price.coingecko_client.asyncio.sleep")

        with pytest.raises(RateLimitError):
            await client.fetch_historical_prices(max_retries=3)

        # Verify exponential backoff: 10s, 10s, 10s (uses Retry-After header)
        assert mock_sleep.call_count == 3

    async def test_invalid_coin_id_raises_error(self, mocker):
        """Test that invalid coin_id raises InvalidSymbolError."""
        client = CoinGeckoClient()

        # Mock 404 response
        mock_response = mocker.Mock()
        mock_response.status_code = 404

        mocker.patch.object(
            client._client,
            "get",
            side_effect=httpx.HTTPStatusError(
                "Not found", request=mocker.Mock(), response=mock_response
            ),
        )

        with pytest.raises(InvalidSymbolError):
            await client.fetch_historical_prices(coin_id="invalid-coin")

    async def test_timeout_raises_timeout_error(self, mocker):
        """Test that timeout raises TimeoutError."""
        client = CoinGeckoClient(timeout=5.0)

        mocker.patch.object(
            client._client, "get", side_effect=httpx.TimeoutException("Request timeout")
        )

        with pytest.raises(TimeoutError):
            await client.fetch_historical_prices()

    async def test_malformed_price_entry_skipped(self, mocker):
        """Test that malformed price entries are skipped gracefully."""
        client = CoinGeckoClient()

        # Mock response with one malformed entry
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "prices": [
                [1714521600000, 63000.50],  # Valid
                [1714525200000],  # Malformed (missing price)
                [1714528800000, 63400.00],  # Valid
            ]
        }
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch.object(client._client, "get", return_value=mock_response)

        result = await client.fetch_historical_prices()

        # Should return only 2 valid entries
        assert len(result) == 2
        assert result[0][1] == 63000.50
        assert result[1][1] == 63400.00

    async def test_zero_days_raises_value_error(self):
        """Test that days=0 raises ValueError."""
        client = CoinGeckoClient()

        with pytest.raises(ValueError, match="days must be positive"):
            await client.fetch_historical_prices(days=0)

    async def test_negative_days_raises_value_error(self):
        """Test that negative days raises ValueError."""
        client = CoinGeckoClient()

        with pytest.raises(ValueError, match="days must be positive"):
            await client.fetch_historical_prices(days=-1)

    async def test_empty_coin_id_raises_value_error(self):
        """Test that empty coin_id raises ValueError."""
        client = CoinGeckoClient()

        with pytest.raises(ValueError, match="coin_id cannot be empty"):
            await client.fetch_historical_prices(coin_id="")

    async def test_timestamp_converted_to_utc_datetime(self, mocker, sample_market_chart_response):
        """Test that timestamps are converted to UTC datetime objects."""
        client = CoinGeckoClient()

        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_market_chart_response
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch.object(client._client, "get", return_value=mock_response)

        result = await client.fetch_historical_prices()

        timestamp = result[0][0]

        # Verify it's a datetime object with UTC timezone
        assert isinstance(timestamp, datetime)
        assert timestamp.tzinfo == timezone.utc

        # Verify the timestamp value
        # 1714521600000 ms = 2024-05-01 00:00:00 UTC
        assert timestamp.year == 2024
        assert timestamp.month == 5
        assert timestamp.day == 1
