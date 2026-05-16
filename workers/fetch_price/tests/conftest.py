"""Pytest configuration and fixtures for fetch_price tests."""

import pytest


@pytest.fixture
def binance_api_url():
    """Base URL for Binance API."""
    return "https://api.binance.com"


@pytest.fixture
def sample_binance_response():
    """Sample Binance /api/v3/klines response for BTCUSDT 1h."""
    return [
        [
            1714521600000,      # Kline open time (Unix ms) - 2024-05-01 00:00:00 UTC
            "63000.50",         # Open
            "63500.75",         # High
            "62800.25",         # Low
            "63200.00",         # Close
            "1234.56789012",    # Volume
            1714525199999,      # Kline close time
            "77777777.77",      # Quote asset volume
            5000,               # Number of trades
            "617.28394506",     # Taker buy base asset volume
            "38888888.88",      # Taker buy quote asset volume
            "0"                 # Unused field
        ]
    ]


@pytest.fixture
def sample_binance_multiple_candles():
    """Sample Binance response with 3 candles."""
    return [
        [
            1714528800000,      # 2024-05-01 02:00:00 UTC (newest)
            "63400.00",
            "63600.00",
            "63300.00",
            "63500.00",
            "800.12345678",
            1714532399999,
            "50000000.00",
            3000,
            "400.06172839",
            "25000000.00",
            "0"
        ],
        [
            1714525200000,      # 2024-05-01 01:00:00 UTC
            "63200.00",
            "63450.00",
            "63100.00",
            "63400.00",
            "950.98765432",
            1714528799999,
            "60000000.00",
            4000,
            "475.49382716",
            "30000000.00",
            "0"
        ],
        [
            1714521600000,      # 2024-05-01 00:00:00 UTC (oldest)
            "63000.50",
            "63500.75",
            "62800.25",
            "63200.00",
            "1234.56789012",
            1714525199999,
            "77777777.77",
            5000,
            "617.28394506",
            "38888888.88",
            "0"
        ]
    ]
