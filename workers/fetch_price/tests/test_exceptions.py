"""Tests for custom Binance API exceptions."""

import pytest

from fetch_price.exceptions import (
    BinanceAPIError,
    InvalidSymbolError,
    RateLimitError,
)


class TestBinanceAPIError:
    """Tests for base BinanceAPIError exception."""

    def test_can_raise_base_exception(self):
        """Test that BinanceAPIError can be raised."""
        with pytest.raises(BinanceAPIError) as exc_info:
            raise BinanceAPIError("Something went wrong")

        assert str(exc_info.value) == "Something went wrong"

    def test_inherits_from_exception(self):
        """Test that BinanceAPIError inherits from Exception."""
        assert issubclass(BinanceAPIError, Exception)


class TestRateLimitError:
    """Tests for RateLimitError exception."""

    def test_can_raise_with_message_only(self):
        """Test RateLimitError with just a message."""
        with pytest.raises(RateLimitError) as exc_info:
            raise RateLimitError("Rate limit exceeded")

        assert str(exc_info.value) == "Rate limit exceeded"
        assert exc_info.value.retry_after is None

    def test_can_raise_with_retry_after(self):
        """Test RateLimitError with retry_after value."""
        with pytest.raises(RateLimitError) as exc_info:
            raise RateLimitError("Rate limit exceeded", retry_after=60)

        assert str(exc_info.value) == "Rate limit exceeded"
        assert exc_info.value.retry_after == 60

    def test_inherits_from_binance_api_error(self):
        """Test that RateLimitError inherits from BinanceAPIError."""
        assert issubclass(RateLimitError, BinanceAPIError)

    def test_retry_after_defaults_to_none(self):
        """Test that retry_after defaults to None if not provided."""
        error = RateLimitError("Too many requests")
        assert error.retry_after is None


class TestInvalidSymbolError:
    """Tests for InvalidSymbolError exception."""

    def test_can_raise_invalid_symbol_error(self):
        """Test that InvalidSymbolError can be raised."""
        with pytest.raises(InvalidSymbolError) as exc_info:
            raise InvalidSymbolError("Invalid symbol: FOOBAR")

        assert str(exc_info.value) == "Invalid symbol: FOOBAR"

    def test_inherits_from_binance_api_error(self):
        """Test that InvalidSymbolError inherits from BinanceAPIError."""
        assert issubclass(InvalidSymbolError, BinanceAPIError)


class TestExceptionHierarchy:
    """Tests for exception inheritance hierarchy."""

    def test_all_custom_exceptions_inherit_from_base(self):
        """Test that all custom exceptions inherit from BinanceAPIError."""
        custom_exceptions = [RateLimitError, InvalidSymbolError]

        for exc_class in custom_exceptions:
            assert issubclass(exc_class, BinanceAPIError)

    def test_can_catch_all_with_base_exception(self):
        """Test that catching BinanceAPIError catches all custom exceptions."""
        # Should catch RateLimitError
        with pytest.raises(BinanceAPIError):
            raise RateLimitError("Rate limit")

        # Should catch InvalidSymbolError
        with pytest.raises(BinanceAPIError):
            raise InvalidSymbolError("Invalid")
