"""Tests for fetch_price main job."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from shared.db.models import BtcPrice
from sqlalchemy.exc import OperationalError

from fetch_price.exceptions import InvalidSymbolError, RateLimitError
from fetch_price.main import (
    fetch_prices,
    filter_existing_timestamps,
    main,
    save_prices,
)


class TestFetchPrices:
    """Tests for fetch_prices() function."""

    @pytest.mark.asyncio
    async def test_fetch_prices_success(self):
        """Test fetching prices successfully from CoinGecko."""
        # Mock CoinGeckoClient (note: volume is 0.0 from CoinGecko)
        mock_candles = [
            (
                datetime(2024, 5, 1, 2, 0, 0, tzinfo=timezone.utc),
                63400.00,
                63600.00,
                63300.00,
                63500.00,
                0.0  # CoinGecko OHLC doesn't include volume
            ),
            (
                datetime(2024, 5, 1, 1, 0, 0, tzinfo=timezone.utc),
                63200.00,
                63450.00,
                63100.00,
                63400.00,
                0.0  # CoinGecko OHLC doesn't include volume
            )
        ]

        with patch("fetch_price.main.CoinGeckoClient") as mock_client_cls:
            mock_instance = mock_client_cls.return_value
            mock_instance.fetch_ohlcv = AsyncMock(return_value=mock_candles)

            prices = await fetch_prices(days=1)

            # Verify CoinGeckoClient was called correctly
            mock_instance.fetch_ohlcv.assert_called_once_with(
                coin_id="bitcoin",
                vs_currency="usd",
                days=1
            )

            # Verify returned data
            assert len(prices) == 2
            assert prices[0]["timestamp"] == datetime(2024, 5, 1, 2, 0, 0, tzinfo=timezone.utc)
            assert prices[0]["open"] == Decimal("63400.00")
            assert prices[0]["high"] == Decimal("63600.00")
            assert prices[0]["low"] == Decimal("63300.00")
            assert prices[0]["close"] == Decimal("63500.00")
            assert prices[0]["volume"] == Decimal("0.0")
            assert prices[0]["source"] == "coingecko"

    @pytest.mark.asyncio
    async def test_fetch_prices_empty_response(self):
        """Test handling empty response from CoinGecko."""
        with patch("fetch_price.main.CoinGeckoClient") as mock_client_cls:
            mock_instance = mock_client_cls.return_value
            mock_instance.fetch_ohlcv = AsyncMock(return_value=[])

            prices = await fetch_prices(days=1)

            assert prices == []

    @pytest.mark.asyncio
    async def test_fetch_prices_timeout(self):
        """Test handling CoinGecko API timeout."""
        with patch("fetch_price.main.CoinGeckoClient") as mock_client_cls:
            mock_instance = mock_client_cls.return_value
            mock_instance.fetch_ohlcv = AsyncMock(side_effect=TimeoutError("CoinGecko API timeout"))

            with pytest.raises(TimeoutError):
                await fetch_prices()

    @pytest.mark.asyncio
    async def test_fetch_prices_rate_limit(self):
        """Test handling CoinGecko rate limit error."""
        with patch("fetch_price.main.CoinGeckoClient") as mock_client_cls:
            mock_instance = mock_client_cls.return_value
            mock_instance.fetch_ohlcv = AsyncMock(
                side_effect=RateLimitError("Rate limit exceeded", retry_after=60)
            )

            with pytest.raises(RateLimitError):
                await fetch_prices()


class TestFilterExistingTimestamps:
    """Tests for filter_existing_timestamps() function."""

    def test_filter_no_existing(self, test_db_session, sample_price_data):
        """Test filtering when no existing records (all new)."""
        new_prices = filter_existing_timestamps(sample_price_data, test_db_session)

        assert len(new_prices) == 3
        assert new_prices == sample_price_data

    def test_filter_with_existing(self, test_db_session, sample_price_data):
        """Test filtering when some records already exist."""
        # First, add 2 existing prices to DB
        existing = [
            BtcPrice(
                timestamp=datetime(2024, 5, 1, 1, 0, 0, tzinfo=timezone.utc),
                open=Decimal("63200.00"),
                high=Decimal("63450.00"),
                low=Decimal("63100.00"),
                close=Decimal("63400.00"),
                volume=Decimal("950.98765432"),
                source="coingecko"
            ),
            BtcPrice(
                timestamp=datetime(2024, 5, 1, 0, 0, 0, tzinfo=timezone.utc),
                open=Decimal("63000.50"),
                high=Decimal("63500.75"),
                low=Decimal("62800.25"),
                close=Decimal("63200.00"),
                volume=Decimal("0.0"),
                source="coingecko"
            )
        ]
        test_db_session.add_all(existing)
        test_db_session.commit()

        # sample_price_data has 3 prices, 2 of which overlap
        new_prices = filter_existing_timestamps(sample_price_data, test_db_session)

        # Only 1 new price (2024-05-01 02:00:00)
        assert len(new_prices) == 1
        assert new_prices[0]["timestamp"] == datetime(2024, 5, 1, 2, 0, 0, tzinfo=timezone.utc)

    def test_filter_all_existing(self, test_db_session):
        """Test filtering when all records already exist."""
        # Add existing record
        existing = BtcPrice(
            timestamp=datetime(2024, 5, 1, 1, 0, 0, tzinfo=timezone.utc),
            open=Decimal("63200.00"),
            high=Decimal("63450.00"),
            low=Decimal("63100.00"),
            close=Decimal("63400.00"),
            volume=Decimal("950.98765432"),
            source="coingecko"
        )
        test_db_session.add(existing)
        test_db_session.commit()

        # Use same data as existing record
        prices = [
            {
                "timestamp": datetime(2024, 5, 1, 1, 0, 0, tzinfo=timezone.utc),
                "open": Decimal("63200.00"),
                "high": Decimal("63450.00"),
                "low": Decimal("63100.00"),
                "close": Decimal("63400.00"),
                "volume": Decimal("0.0"),
                "source": "coingecko"
            }
        ]

        new_prices = filter_existing_timestamps(prices, test_db_session)

        assert len(new_prices) == 0

    def test_filter_empty_input(self, test_db_session):
        """Test filtering with empty input list."""
        new_prices = filter_existing_timestamps([], test_db_session)

        assert new_prices == []


class TestSavePrices:
    """Tests for save_prices() function."""

    def test_save_prices_success(self, test_db_session, sample_price_data):
        """Test saving prices successfully."""
        inserted = save_prices(sample_price_data, test_db_session)

        assert inserted == 3

        # Verify records in database
        count = test_db_session.query(BtcPrice).count()
        assert count == 3

    def test_save_prices_empty(self, test_db_session):
        """Test saving empty list."""
        inserted = save_prices([], test_db_session)

        assert inserted == 0

    def test_save_prices_rollback_on_error(self, test_db_session):
        """Test that session rolls back on error."""
        # Invalid data (missing required field)
        invalid_prices = [
            {
                "timestamp": datetime(2024, 5, 1, 0, 0, 0, tzinfo=timezone.utc),
                # Missing open, high, low, close, volume
            }
        ]

        with pytest.raises(Exception):
            save_prices(invalid_prices, test_db_session)

        # Rollback the failed transaction before querying
        test_db_session.rollback()

        # Verify no records were inserted
        count = test_db_session.query(BtcPrice).count()
        assert count == 0


class TestMain:
    """Tests for main() orchestration - Gherkin scenarios."""

    @pytest.mark.asyncio
    async def test_gherkin_first_run_inserts_new_prices(self):
        """
        Gherkin Scenario: First run inserts new prices

        Given the btc_prices table is empty
        And the CoinGecko API returns 24 candles (last 24 hours)
        When I run the job
        Then 24 records are inserted into btc_prices
        And all records have source="coingecko"
        And no IntegrityError occurs
        """
        # Generate 24 mock candles (volume=0.0 from CoinGecko)
        mock_candles = [
            (
                datetime(2024, 5, 1, i, 0, 0, tzinfo=timezone.utc),
                63000.0 + i * 10,
                63100.0 + i * 10,
                62900.0 + i * 10,
                63050.0 + i * 10,
                0.0  # CoinGecko OHLC doesn't include volume
            )
            for i in range(24)
        ]

        with patch("fetch_price.main.CoinGeckoClient") as mock_client_cls, \
             patch("fetch_price.main.SessionLocal") as mock_session_cls:

            # Mock CoinGecko client
            mock_instance = mock_client_cls.return_value
            mock_instance.fetch_ohlcv = AsyncMock(return_value=mock_candles)

            # Mock empty database session
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_session.query.return_value.filter.return_value.all.return_value = []
            mock_session_cls.return_value = mock_session

            # Run job
            exit_code = await main()

            # Verify success
            assert exit_code == 0

            # Verify add_all was called with 24 records
            mock_session.add_all.assert_called_once()
            added_prices = mock_session.add_all.call_args[0][0]
            assert len(added_prices) == 24
            assert all(p.source == "coingecko" for p in added_prices)

            # Verify commit was called
            mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_gherkin_second_run_skips_existing(self):
        """
        Gherkin Scenario: Second run skips existing prices

        Given the btc_prices table already has records for timestamps T1, T2, T3
        And the CoinGecko API returns candles for T1, T2, T3, T4 (T4 is new)
        When I run the job
        Then only 1 new record (T4) is inserted
        And existing records (T1, T2, T3) are unchanged
        """
        mock_candles = [
            # New
            (
                datetime(2024, 5, 1, 3, 0, 0, tzinfo=timezone.utc),
                63300.0,
                63400.0,
                63200.0,
                63350.0,
                0.0,  # CoinGecko OHLC doesn't include volume
            ),
            # Existing
            (
                datetime(2024, 5, 1, 2, 0, 0, tzinfo=timezone.utc),
                63200.0,
                63300.0,
                63100.0,
                63250.0,
                0.0,
            ),
            # Existing
            (
                datetime(2024, 5, 1, 1, 0, 0, tzinfo=timezone.utc),
                63100.0,
                63200.0,
                63000.0,
                63150.0,
                0.0,
            ),
            # Existing
            (
                datetime(2024, 5, 1, 0, 0, 0, tzinfo=timezone.utc),
                63000.0,
                63100.0,
                62900.0,
                63050.0,
                0.0,
            ),
        ]

        # Mock existing timestamps T1, T2, T3
        existing_timestamps = [
            (datetime(2024, 5, 1, 2, 0, 0, tzinfo=timezone.utc),),
            (datetime(2024, 5, 1, 1, 0, 0, tzinfo=timezone.utc),),
            (datetime(2024, 5, 1, 0, 0, 0, tzinfo=timezone.utc),),
        ]

        with patch("fetch_price.main.CoinGeckoClient") as mock_client_cls, \
             patch("fetch_price.main.SessionLocal") as mock_session_cls:

            mock_instance = mock_client_cls.return_value
            mock_instance.fetch_ohlcv = AsyncMock(return_value=mock_candles)

            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_session.query.return_value.filter.return_value.all.return_value = (
                existing_timestamps
            )
            mock_session_cls.return_value = mock_session

            exit_code = await main()

            assert exit_code == 0

            # Verify only 1 new record was inserted
            mock_session.add_all.assert_called_once()
            added_prices = mock_session.add_all.call_args[0][0]
            assert len(added_prices) == 1
            assert added_prices[0].timestamp == datetime(2024, 5, 1, 3, 0, 0, tzinfo=timezone.utc)

    @pytest.mark.asyncio
    async def test_gherkin_coingecko_timeout(self):
        """
        Gherkin Scenario: CoinGecko API timeout during fetch

        Given the CoinGecko API times out
        When I run the job
        Then a TimeoutError is logged
        And the job exits with code 1 (error)
        And no partial data is saved to the database
        """
        with patch("fetch_price.main.CoinGeckoClient") as mock_client_cls, \
             patch("fetch_price.main.SessionLocal") as mock_session_cls:

            mock_instance = mock_client_cls.return_value
            mock_instance.fetch_ohlcv = AsyncMock(side_effect=TimeoutError("CoinGecko API timeout"))

            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            exit_code = await main()

            # Verify error exit code
            assert exit_code == 1

            # Verify no database operations were attempted
            mock_session.__enter__.assert_not_called()

    @pytest.mark.asyncio
    async def test_gherkin_database_connection_failure(self):
        """
        Gherkin Scenario: Database connection failure

        Given the DATABASE_URL is invalid
        When I run the job
        Then an OperationalError is logged
        And the job exits with code 1 (error)
        """
        mock_candles = [
            (
                datetime(2024, 5, 1, 0, 0, 0, tzinfo=timezone.utc),
                63000.0,
                63100.0,
                62900.0,
                63050.0,
                0.0,  # CoinGecko OHLC doesn't include volume
            )
        ]

        with patch("fetch_price.main.CoinGeckoClient") as mock_client_cls, \
             patch("fetch_price.main.SessionLocal") as mock_session_cls:

            mock_instance = mock_client_cls.return_value
            mock_instance.fetch_ohlcv = AsyncMock(return_value=mock_candles)

            # Mock database connection failure
            mock_session_cls.side_effect = OperationalError("statement", "params", "orig")

            exit_code = await main()

            # Verify error exit code
            assert exit_code == 1

    @pytest.mark.asyncio
    async def test_zero_candles_returned(self):
        """
        ZOMBIES: Zero case

        When CoinGecko returns 0 candles
        Then log "No data fetched" and exit 0
        """
        with patch("fetch_price.main.CoinGeckoClient") as mock_client_cls, \
             patch("fetch_price.main.SessionLocal") as mock_session_cls:

            mock_instance = mock_client_cls.return_value
            mock_instance.fetch_ohlcv = AsyncMock(return_value=[])

            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_session.query.return_value.filter.return_value.all.return_value = []
            mock_session_cls.return_value = mock_session

            exit_code = await main()

            # Success even with 0 candles
            assert exit_code == 0

            # No database operations
            mock_session.add_all.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_symbol_error(self):
        """Test handling invalid coin_id error from CoinGecko."""
        with patch("fetch_price.main.CoinGeckoClient") as mock_client_cls:
            mock_instance = mock_client_cls.return_value
            mock_instance.fetch_ohlcv = AsyncMock(
                side_effect=InvalidSymbolError("Invalid coin_id: bitcoin")
            )

            exit_code = await main()

            # Verify error exit code
            assert exit_code == 1
