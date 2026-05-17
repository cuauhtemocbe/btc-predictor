---
title: Migration from Binance to CoinGecko API
status: completed
created: 2026-05-17
updated: 2026-05-17
completed: 2026-05-17
issue: #18
replaces: US-003 (binance-api-client.md)
---

# Migration from Binance to CoinGecko API

## Objective

Replace the Binance API client with a CoinGecko API client to avoid HTTP 451 (geo-blocking) errors encountered in Railway deployment. CoinGecko provides similar OHLCV data without geographic restrictions, ensuring reliable data ingestion regardless of deployment region.

## Context

**Problem discovered**: When deployed to Railway, the fetch-price service receives HTTP 451 "Unavailable For Legal Reasons" from Binance API. This indicates Binance is blocking requests from Railway's deployment region due to regulatory restrictions.

**Impact**: 
- ❌ fetch_price job fails on every execution
- ❌ No price data being ingested into btc_prices table
- ❌ Cannot proceed with ML training/predictions without data

**Why CoinGecko**:
- ✅ No geographic restrictions
- ✅ Free public API without authentication
- ✅ Similar OHLCV data structure
- ✅ Well-documented and stable API
- ✅ Good rate limits (10-50 calls/min on free tier)
- ⚠️ OHLC endpoint doesn't include volume (acceptable tradeoff)

**Verified**: Manual test confirms CoinGecko API works from current environment:
```bash
curl "https://api.coingecko.com/api/v3/coins/bitcoin/ohlc?vs_currency=usd&days=1"
# Returns: [[timestamp, open, high, low, close], ...]
```

## Requirements

### Functional Requirements

- [ ] Create `CoinGeckoClient` with same interface as `BinanceClient`
- [ ] Fetch OHLCV data for Bitcoin (coin_id: "bitcoin")
- [ ] Support configurable timeframe (days parameter: 1, 7, 14, 30, etc.)
- [ ] Return structured data: list of tuples `(timestamp, open, high, low, close, volume)`
- [ ] Timestamps must be UTC datetime objects (convert from Unix ms)
- [ ] Price values must be parsed as floats
- [ ] Volume should be set to `Decimal('0')` (CoinGecko OHLC doesn't include volume)
- [ ] Candles ordered by timestamp descending (newest first)
- [ ] Update `fetch_price/main.py` to use `CoinGeckoClient` instead of `BinanceClient`
- [ ] Update `source` field from "binance" to "coingecko"

### Non-Functional Requirements

- [ ] **Performance**: API response time < 5 seconds under normal conditions
- [ ] **Reliability**: Configurable timeout (default: 10 seconds)
- [ ] **Error Handling**: Custom exceptions for timeout, rate limit, invalid coin
- [ ] **Async**: Use httpx async client for non-blocking I/O
- [ ] **Backward Compatibility**: Existing `btc_prices` table works without schema changes
- [ ] **Maintainability**: Clear error messages with context
- [ ] **Testability**: All API calls mockable via httpx/respx

## Architecture

### Components

```
workers/fetch_price/
├── __init__.py
├── binance_client.py        # DEPRECATED - keep for reference
├── coingecko_client.py      # NEW - CoinGecko implementation
├── exceptions.py             # UPDATE - generalize exceptions
├── main.py                   # UPDATE - switch to CoinGeckoClient
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_binance_client.py    # KEEP - legacy tests
    ├── test_coingecko_client.py  # NEW - CoinGecko tests
    └── test_main.py               # UPDATE - test with CoinGecko
```

### Data Model

**Input:**
```python
coin_id: str = "bitcoin"
vs_currency: str = "usd"
days: int = 1  # 1 day = ~24 hourly candles
```

**Output:**
```python
List[Tuple[datetime, float, float, float, float, float]]
# [(timestamp, open, high, low, close, volume), ...]
# Note: volume will be 0.0 for all records
```

**CoinGecko API Response (JSON):**
```json
[
  [1778909400000, 78968.0, 78985.0, 78968.0, 78984.0],
  [1778911200000, 78990.0, 78990.0, 78916.0, 78944.0]
]
```
Format: `[timestamp_ms, open, high, low, close]`

### External Dependencies

- **httpx** (already in project): Async HTTP client
- **CoinGecko Public API**: `https://api.coingecko.com/api/v3`
  - Endpoint: `/coins/{coin_id}/ohlc?vs_currency={currency}&days={days}`
  - No authentication required
  - Rate limit: 10-50 calls/minute (free tier)
  - No geographic restrictions

### Class Design

```python
class CoinGeckoClient:
    """Async client for CoinGecko Public API (OHLCV data)"""
    
    def __init__(
        self,
        base_url: str = "https://api.coingecko.com/api/v3",
        timeout: float = 10.0
    ):
        """Initialize client with configurable base URL and timeout"""
        pass
    
    async def fetch_ohlcv(
        self,
        coin_id: str = "bitcoin",
        vs_currency: str = "usd",
        days: int = 1
    ) -> List[Tuple[datetime, float, float, float, float, float]]:
        """
        Fetch OHLCV data from CoinGecko.
        
        Args:
            coin_id: Coin identifier (default: bitcoin)
            vs_currency: Target currency (default: usd)
            days: Number of days of data (1, 7, 14, 30, 90, 180, 365)
            
        Returns:
            List of tuples: (timestamp, open, high, low, close, volume)
            Ordered by timestamp descending (newest first)
            Note: volume will always be 0.0 (not provided by OHLC endpoint)
            
        Raises:
            ValueError: Invalid parameters
            TimeoutError: API did not respond in time
            RateLimitError: API rate limit exceeded (429)
            PriceAPIError: Other API errors (4xx, 5xx)
        """
        pass
```

### Exception Updates

Update `exceptions.py` to use generic base class:

```python
class PriceAPIError(Exception):
    """Base exception for price API errors (Binance, CoinGecko, etc.)"""
    pass

# Specific exceptions inherit from PriceAPIError
class RateLimitError(PriceAPIError): ...
class InvalidSymbolError(PriceAPIError): ...

# Legacy aliases for backward compatibility
BinanceAPIError = PriceAPIError
CoinGeckoAPIError = PriceAPIError
```

## Migration Path

### Phase 1: Create CoinGecko Client (Parallel Implementation)

1. ✅ Verify CoinGecko API works (manual curl test)
2. Create `coingecko_client.py` with same interface as `BinanceClient`
3. Generalize exceptions in `exceptions.py`
4. Write tests for `CoinGeckoClient` (mirror existing Binance tests)
5. Verify all tests pass

**No changes to production yet** - just add new code alongside existing.

### Phase 2: Switch Main Job

1. Update `fetch_price/main.py`:
   - Import `CoinGeckoClient` instead of `BinanceClient`
   - Change `source="binance"` to `source="coingecko"`
   - Update docstrings/comments
2. Update `test_main.py` to mock CoinGecko instead of Binance
3. Run full test suite
4. Manual test in local Docker environment

### Phase 3: Deploy & Verify

1. Deploy to Railway
2. Monitor logs for successful execution
3. Verify data insertion in btc_prices table
4. If successful: deprecate `BinanceClient` (keep for reference but don't use)

## Testing Strategy

### Unit Tests

**File**: `workers/fetch_price/tests/test_coingecko_client.py`

Mirror all existing Binance tests:
- ✅ Fetch 1 day of data (~24 candles)
- ✅ Timeout handling (10s)
- ✅ Rate limit handling (429)
- ✅ Invalid coin_id (404 error)
- ✅ ZOMBIES edge cases:
  - Zero: Invalid days parameter
  - One: days=1 → returns ~24 hourly candles
  - Many: days=7 → returns ~168 candles
  - Boundary: days > 365 → handle gracefully
  - Exceptions: network errors, 500 errors
  - Security: no credentials in logs

**Target Coverage**: ≥90%

### Integration Tests

Update `test_main.py`:
- Mock CoinGeckoClient instead of BinanceClient
- Verify volume field is set to 0
- Verify source field is "coingecko"
- All existing scenarios still pass

### Manual Testing

```bash
# Start services
docker compose up -d

# Run fetch_price job with new CoinGecko client
docker compose exec api python -m fetch_price.main

# Verify data
docker compose exec postgres psql -U btcpredictor -d btcpredictor \
  -c "SELECT timestamp, close, volume, source FROM btc_prices ORDER BY timestamp DESC LIMIT 5;"

# Expected: source='coingecko', volume=0.00000000
```

## Boundaries & Constraints

### In Scope

- Replace BinanceClient with CoinGeckoClient
- Update tests to reflect new API
- Update source field in database
- Generalize exceptions for any price API
- Maintain same interface (drop-in replacement)

### Out of Scope

- ❌ Fetching volume data from separate endpoint (accept volume=0)
- ❌ Supporting multiple cryptocurrencies (still BTC-only)
- ❌ Migrating existing records (old data stays as source='binance')
- ❌ Implementing CoinGecko paid tier features
- ❌ Adding retry logic or caching (future enhancement)

### Technical Constraints

- Must maintain same return type as BinanceClient
- Must work inside Docker container
- Must work in Railway deployment region
- CoinGecko OHLC endpoint only supports specific day intervals (1,7,14,30,90,180,365)
- Volume data not available in OHLC endpoint (tradeoff accepted)

### Acceptable Tradeoffs

1. **No volume data**: CoinGecko OHLC endpoint doesn't include volume
   - **Impact**: Volume column will be 0 for all new records
   - **Mitigation**: Could fetch from `/market_chart` endpoint in future if needed
   - **Decision**: Accept 0 volume for now - not critical for initial ML models

2. **Different rate limits**: CoinGecko has lower rate limits (10-50/min vs Binance 1200/min)
   - **Impact**: Minimal - we only call once per hour
   - **Mitigation**: Already well within limits

3. **Less granular intervals**: CoinGecko only supports specific day values
   - **Impact**: Less flexibility than Binance
   - **Mitigation**: days=1 gives us hourly data for last 24h (sufficient)

## Success Criteria

- [ ] CoinGeckoClient passes all unit tests (≥90% coverage)
- [ ] fetch_price job runs successfully in Railway without HTTP 451 error
- [ ] New records inserted with source='coingecko'
- [ ] Volume field correctly set to 0
- [ ] All existing tests still pass (with updated mocks)
- [ ] Lint passes (ruff check)
- [ ] Manual testing confirms data ingestion works
- [ ] Deployment to Railway successful
- [ ] Monitoring shows no errors for 24 hours post-deployment

## Rollback Plan

If CoinGecko fails in production:

1. Revert `main.py` to use `BinanceClient`
2. Change source back to "binance"
3. Investigate alternative APIs:
   - Kraken API (less restrictive than Binance)
   - CryptoCompare API
   - CoinCap API
4. Consider deploying to different Railway region (if available)

## Implementation Plan

Will be created in Phase 2 after spec approval.

## Notes

- **Why not Binance.US?** Requires different endpoint and may still have restrictions
- **Why not use proxy?** Violates Binance ToS and unreliable for production
- **Why not change Railway region?** Not guaranteed to work, CoinGecko more reliable
- **Future enhancement**: Could combine CoinGecko OHLC + market_chart to get volume
- **Volume impact**: Initial linear regression models don't use volume, so no immediate impact
