---
title: Binance API Client for OHLCV Data
status: completed
created: 2026-05-16
updated: 2026-05-16
issue: #4
user_story: US-003
---

# Binance API Client for OHLCV Data

## Objective

Build an async Binance API client that fetches hourly Bitcoin OHLCV (Open, High, Low, Close, Volume) data from Binance's public API without authentication. This client will serve as the foundation for all historical price data ingestion in the BTC Predictor application.

## Context

The BTC Predictor application needs historical Bitcoin price data to:
- Train machine learning models on past price patterns
- Evaluate prediction accuracy against actual prices
- Build a complete time series for feature engineering

Binance provides a free public API (`/api/v3/klines`) that returns OHLCV data without requiring API keys or authentication. The client must be robust, handle API errors gracefully, and return data in a structured format that can be easily stored in the database.

**User:** Data pipeline developer  
**Need:** Reliable Bitcoin price data ingestion  
**Pain point:** Manual data collection is time-consuming and error-prone

## Requirements

### Functional Requirements

- [ ] Fetch OHLCV data for a given symbol (default: BTCUSDT)
- [ ] Support configurable intervals (default: 1h)
- [ ] Support configurable limit (1 to 1000 candles)
- [ ] Return structured data: list of tuples `(timestamp, open, high, low, close, volume)`
- [ ] Timestamps must be UTC datetime objects (not Unix milliseconds)
- [ ] Price values must be parsed as floats
- [ ] Volume must be parsed as float
- [ ] Candles ordered by timestamp descending (newest first)

### Non-Functional Requirements

- [ ] **Performance**: API response time < 5 seconds under normal conditions
- [ ] **Reliability**: Configurable timeout (default: 10 seconds)
- [ ] **Error Handling**: Custom exceptions for timeout, rate limit, invalid symbol
- [ ] **Async**: Use httpx async client for non-blocking I/O
- [ ] **Security**: No credentials logged or exposed
- [ ] **Maintainability**: Clear error messages with context
- [ ] **Testability**: All API calls mockable via httpx

## Architecture

### Components

```
workers/
└── fetch_price/
    ├── __init__.py
    ├── binance_client.py     # Main client implementation
    ├── exceptions.py          # Custom exceptions
    └── tests/
        ├── __init__.py
        ├── conftest.py        # Test fixtures
        ├── test_binance_client.py
        └── test_exceptions.py
```

### Data Model

**Input:**
```python
symbol: str = "BTCUSDT"
interval: str = "1h"
limit: int = 1
```

**Output:**
```python
List[Tuple[datetime, float, float, float, float, float]]
# [(timestamp, open, high, low, close, volume), ...]
```

**Binance API Response (JSON):**
```json
[
  [
    1499040000000,      // Kline open time (Unix ms)
    "0.01634790",       // Open price
    "0.80000000",       // High price
    "0.01575800",       // Low price
    "0.01577100",       // Close price
    "148976.11427815",  // Volume
    1499644799999,      // Kline close time
    "2434.19055334",    // Quote asset volume
    308,                // Number of trades
    "1756.87402397",    // Taker buy base asset volume
    "28.46694368",      // Taker buy quote asset volume
    "0"                 // Unused field, ignore
  ]
]
```

### External Dependencies

- **httpx** (already in project): Async HTTP client for API requests
- **Binance Public API**: `https://api.binance.com/api/v3/klines`
  - No authentication required
  - Rate limit: ~1200 requests/minute (we'll stay well below)
  - Max limit per request: 1000 candles

### Class Design

```python
class BinanceClient:
    """Async client for Binance Public API (OHLCV data)"""
    
    def __init__(
        self,
        base_url: str = "https://api.binance.com",
        timeout: float = 10.0
    ):
        """Initialize client with configurable base URL and timeout"""
        pass
    
    async def fetch_ohlcv(
        self,
        symbol: str = "BTCUSDT",
        interval: str = "1h",
        limit: int = 1
    ) -> List[Tuple[datetime, float, float, float, float, float]]:
        """
        Fetch OHLCV data from Binance.
        
        Args:
            symbol: Trading pair (default: BTCUSDT)
            interval: Candle interval (1m, 5m, 1h, 1d, etc.)
            limit: Number of candles to fetch (1-1000)
            
        Returns:
            List of tuples: (timestamp, open, high, low, close, volume)
            Ordered by timestamp descending (newest first)
            
        Raises:
            ValueError: Invalid parameters (limit out of range, invalid symbol)
            TimeoutError: API did not respond in time
            RateLimitError: API rate limit exceeded (429)
            BinanceAPIError: Other API errors (4xx, 5xx)
        """
        pass
```

### Custom Exceptions

```python
class BinanceAPIError(Exception):
    """Base exception for Binance API errors"""
    pass

class RateLimitError(BinanceAPIError):
    """Raised when API returns 429 Too Many Requests"""
    def __init__(self, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.retry_after = retry_after

class InvalidSymbolError(BinanceAPIError):
    """Raised when API returns 400 for invalid symbol"""
    pass
```

## User Stories

This spec implements **US-003: Cliente Binance API para obtener OHLCV 1h**

Full user story: https://github.com/cuauhtemocbe/btc-predictor/issues/4

## Testing Strategy

### Unit Tests

**File:** `workers/fetch_price/tests/test_binance_client.py`

All tests use `respx` to mock httpx requests (no real API calls).

**Test Coverage:**
- ✅ Fetch 1 candle (latest)
- ✅ Fetch 168 candles (1 week)
- ✅ Timeout handling (10s)
- ✅ Rate limit handling (429 + Retry-After header)
- ✅ Invalid symbol (400 error)
- ✅ ZOMBIES edge cases:
  - Zero: `limit=0` → ValueError
  - One: `limit=1` → returns 1 candle
  - Many: `limit=1000` → returns 1000 candles
  - Boundary: `limit=1001` → ValueError
  - Exceptions: network errors, 500 errors
  - Security: no credentials in logs

**Target Coverage:** ≥90%

### Integration Tests

Not needed for this story (no database yet). Integration will be tested in US-004 when we store data in `btc_prices` table.

### Test Execution

```bash
# Inside container
docker compose exec api pytest workers/fetch_price/tests/ -v
docker compose exec api pytest workers/fetch_price/tests/ --cov=fetch_price --cov-report=term-missing
```

## Boundaries & Constraints

### In Scope
- Fetch OHLCV data from Binance public API
- Error handling for common API failures
- Async implementation with httpx
- Structured return data (tuples)
- Custom exceptions

### Out of Scope
- Database storage (US-004 will handle persistence)
- Authentication or private endpoints
- WebSocket streaming (only REST API)
- Multiple symbols or intervals in one call
- Retry logic with exponential backoff (future enhancement)
- Caching or rate limit management (future enhancement)

### Technical Constraints
- Must use `httpx` (already in dependencies)
- Must be async (FastAPI/workers are async)
- Must work inside Docker container
- Must parse Binance's specific JSON format
- Must convert Unix milliseconds to Python datetime

## Success Criteria

- [ ] All 5 Gherkin scenarios have passing automated tests
- [ ] All ZOMBIES edge cases covered in tests
- [ ] Code coverage ≥90%
- [ ] Lint passes (`ruff check`)
- [ ] Type hints added (passes `mypy` if used)
- [ ] Can fetch real data from Binance in manual testing
- [ ] Execution time <5s for limit=168 (empirical test)
- [ ] No credentials or sensitive data in logs
- [ ] Code review approved
- [ ] Documentation strings complete (docstrings)

## Implementation Plan

See: [binance-api-client-plan.md](./binance-api-client-plan.md)

## Notes

- Binance API documentation: https://binance-docs.github.io/apidocs/spot/en/#kline-candlestick-data
- The API returns 12 fields per candle, but we only need the first 6 (OHLCV + timestamp)
- Future enhancement: Add retry logic with exponential backoff for transient failures
- Future enhancement: Add request/response logging for debugging
