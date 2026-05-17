"""
Tests for GET /api/prices endpoint.

Covers all Gherkin scenarios from US-005:
- Scenario 1: Fetch last 24 prices (default)
- Scenario 2: Fetch custom limit (168)
- Scenario 3: Empty table returns empty array
- Scenario 4: Invalid limit parameter
"""

from datetime import datetime


# Scenario 1: Fetch last 24 prices (default)
async def test_get_prices_default_limit(client, db_session, sample_prices):
    """
    Given the btc_prices table has 100 records
    When I send GET /api/prices
    Then the response status is 200 OK
    And the response body is a JSON array with 24 items (default limit)
    And each item has keys: timestamp, open, high, low, close, volume, source
    And items are ordered by timestamp DESC (newest first)
    """
    # Given: 100 records in database
    sample_prices(100)

    # When: GET /api/prices (no limit parameter)
    response = await client.get("/api/prices")

    # Then: 200 OK
    assert response.status_code == 200

    # And: JSON array with 24 items
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 24

    # And: Each item has all required keys
    required_keys = {"timestamp", "open", "high", "low", "close", "volume", "source"}
    for item in data:
        assert set(item.keys()) == required_keys

    # And: Items ordered by timestamp DESC (newest first)
    timestamps = [
        datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00"))
        for item in data
    ]
    assert timestamps == sorted(timestamps, reverse=True)


# Scenario 2: Fetch last 168 prices (1 week)
async def test_get_prices_custom_limit(client, db_session, sample_prices):
    """
    Given the btc_prices table has 500 records
    When I send GET /api/prices?limit=168
    Then the response body is a JSON array with 168 items
    And items are ordered by timestamp DESC
    """
    # Given: 500 records in database
    sample_prices(500)

    # When: GET /api/prices?limit=168
    response = await client.get("/api/prices?limit=168")

    # Then: 200 OK
    assert response.status_code == 200

    # And: JSON array with 168 items
    data = response.json()
    assert len(data) == 168

    # And: Items ordered by timestamp DESC
    timestamps = [
        datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00"))
        for item in data
    ]
    assert timestamps == sorted(timestamps, reverse=True)


# Scenario 3: Empty table returns empty array
async def test_get_prices_empty_table(client, db_session):
    """
    Given the btc_prices table is empty
    When I send GET /api/prices
    Then the response status is 200 OK
    And the response body is an empty JSON array []
    """
    # Given: Empty table - explicitly clean to ensure isolation
    from shared.db.models import BtcPrice
    db_session.query(BtcPrice).delete()
    db_session.commit()

    # When: GET /api/prices
    response = await client.get("/api/prices")

    # Then: 200 OK
    assert response.status_code == 200

    # And: Empty array
    data = response.json()
    assert data == []


# Scenario 4: Invalid limit parameter (negative)
async def test_get_prices_invalid_limit_negative(client, db_session):
    """
    Given I send GET /api/prices?limit=-1
    Then the response status is 422 Unprocessable Entity
    And the error message indicates "limit must be positive"
    """
    # When: GET /api/prices?limit=-1
    response = await client.get("/api/prices?limit=-1")

    # Then: 422 Unprocessable Entity
    assert response.status_code == 422

    # And: Error message indicates validation failure
    data = response.json()
    assert "detail" in data
    # FastAPI validation error for query param
    assert any("limit" in str(error).lower() for error in data["detail"])


# Scenario 5: Invalid limit parameter (zero)
async def test_get_prices_invalid_limit_zero(client, db_session):
    """
    Given I send GET /api/prices?limit=0
    Then the response status is 422 Unprocessable Entity
    """
    # When: GET /api/prices?limit=0
    response = await client.get("/api/prices?limit=0")

    # Then: 422 Unprocessable Entity
    assert response.status_code == 422

    # And: Error message indicates validation failure
    data = response.json()
    assert "detail" in data


# Scenario 6: Invalid limit parameter (exceeds max)
async def test_get_prices_invalid_limit_exceeds_max(client, db_session):
    """
    Given I send GET /api/prices?limit=1001
    Then the response status is 422 Unprocessable Entity
    And the error message indicates limit exceeds maximum (1000)
    """
    # When: GET /api/prices?limit=1001
    response = await client.get("/api/prices?limit=1001")

    # Then: 422 Unprocessable Entity
    assert response.status_code == 422

    # And: Error message indicates validation failure
    data = response.json()
    assert "detail" in data
    assert any("limit" in str(error).lower() for error in data["detail"])


# Scenario 7: Verify ordering (newest first)
async def test_get_prices_ordering(client, db_session, sample_prices):
    """
    Verify that prices are returned in descending timestamp order (newest first).
    """
    # Given: 50 records with known timestamps
    sample_prices(50)

    # When: GET /api/prices?limit=50
    response = await client.get("/api/prices?limit=50")

    # Then: 200 OK
    assert response.status_code == 200

    # And: Timestamps are in descending order
    data = response.json()
    timestamps = [item["timestamp"] for item in data]

    # Verify each timestamp is >= the next one
    for i in range(len(timestamps) - 1):
        assert timestamps[i] >= timestamps[i + 1], \
            f"Ordering violated: {timestamps[i]} should be >= {timestamps[i + 1]}"


# Scenario 8: Response schema validation
async def test_get_prices_response_schema(client, db_session, sample_prices):
    """
    Verify that each price object in the response has all required fields
    with correct data types.
    """
    # Given: Some records in database
    sample_prices(5)

    # When: GET /api/prices
    response = await client.get("/api/prices")

    # Then: 200 OK
    assert response.status_code == 200

    # And: Each item has correct schema
    data = response.json()
    assert len(data) > 0, "Should have at least 1 record"

    for item in data:
        # Required keys
        assert "timestamp" in item
        assert "open" in item
        assert "high" in item
        assert "low" in item
        assert "close" in item
        assert "volume" in item
        assert "source" in item

        # Type validation
        assert isinstance(item["timestamp"], str)  # ISO 8601 string
        assert isinstance(item["open"], int | float)
        assert isinstance(item["high"], int | float)
        assert isinstance(item["low"], int | float)
        assert isinstance(item["close"], int | float)
        assert isinstance(item["volume"], int | float)
        assert isinstance(item["source"], str)

        # Value validation
        assert item["open"] > 0
        assert item["high"] >= item["low"]
        assert item["volume"] >= 0
        assert len(item["source"]) > 0
