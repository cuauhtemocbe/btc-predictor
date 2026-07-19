"""
Integration tests for backtesting API endpoints.

Tests the /api/backtesting/metrics endpoint with various scenarios:
- Fetching backtest metrics with strategy comparison
- Empty result when no backtest data exists
- Date range filtering
- Metrics calculations (win rate, Sharpe ratio, max drawdown, etc.)
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from shared.db.models import BacktestResult


@pytest.fixture
def sample_backtest_results_factory(db_session: Session):
    """
    Factory fixture for creating backtest result records.

    Usage:
        sample_backtest_results_factory(count=30, backtest_run_id=uuid4())
    """

    def _create_backtest_results(count: int = 30, backtest_run_id=None):
        if backtest_run_id is None:
            backtest_run_id = uuid4()

        results = []
        base_date = date.today()

        for i in range(count):
            predicted_for = base_date - timedelta(days=count - i - 1)
            predicted_at = datetime.combine(
                predicted_for - timedelta(days=1), datetime.min.time(), tzinfo=UTC
            ).replace(hour=19)

            price_at_prediction = Decimal("67000.0") + Decimal(i * 50)
            predicted_price = Decimal("67500.0") + Decimal(i * 50)
            actual_price = Decimal("67800.0") + Decimal(i * 50)

            # Vary PnL to create wins and losses
            # Even days: wins, Odd days: losses (for testing)
            if i % 2 == 0:
                pnl_simple = Decimal("100.0")
                pnl_long_short = Decimal("120.0")
                pnl_threshold = Decimal("90.0")
                pnl_realistic = Decimal("85.0")
            else:
                pnl_simple = Decimal("-50.0")
                pnl_long_short = Decimal("-30.0")
                pnl_threshold = Decimal("-20.0")
                pnl_realistic = Decimal("-35.0")

            result = BacktestResult(
                backtest_run_id=backtest_run_id,
                predicted_for=predicted_for,
                predicted_at=predicted_at,
                price_at_prediction=price_at_prediction,
                predicted_price=predicted_price,
                actual_price=actual_price,
                pnl_simple=pnl_simple,
                pnl_long_short=pnl_long_short,
                pnl_threshold=pnl_threshold,
                pnl_realistic=pnl_realistic,
                model_params={"model_name": "linear_v1", "window_days": 30},
                created_at=datetime.now(UTC),
            )

            db_session.add(result)
            results.append(result)

        db_session.commit()
        for r in results:
            db_session.refresh(r)

        return results

    return _create_backtest_results


# Gherkin Scenario 1: Fetch backtest metrics successfully
@pytest.mark.asyncio
async def test_fetch_backtest_metrics_success(
    client: AsyncClient,
    db_session: Session,
    sample_backtest_results_factory,
):
    """
    Given there is a backtest run with 30 results
    And each result has all 4 PnL strategies calculated
    When I send GET /api/backtesting/metrics
    Then the response status is 200 OK
    And the response contains metadata
        (backtest_run_id, start_date, end_date, total_days)
    And the response contains 4 strategies with metrics
    And the response contains daily_pnl array with 30 entries
    """
    # Arrange: Create 30 backtest results
    sample_backtest_results_factory(count=30)

    # Act: Fetch backtesting metrics
    response = await client.get("/api/backtesting/metrics")

    # Assert
    assert response.status_code == 200
    data = response.json()

    # Verify metadata
    assert "metadata" in data
    assert "backtest_run_id" in data["metadata"]
    assert "start_date" in data["metadata"]
    assert "end_date" in data["metadata"]
    assert data["metadata"]["total_days"] == 30
    assert data["metadata"]["model_name"] == "linear_v1"

    # Verify strategies
    assert "strategies" in data
    assert len(data["strategies"]) == 4
    strategy_names = {s["name"] for s in data["strategies"]}
    assert strategy_names == {"simple", "long_short", "threshold", "realistic"}

    # Verify each strategy has required metrics
    for strategy in data["strategies"]:
        assert "name" in strategy
        assert "display_name" in strategy
        assert "color" in strategy
        assert "total_pnl" in strategy
        assert "win_rate" in strategy
        assert "max_drawdown" in strategy
        assert "best_day" in strategy
        assert "worst_day" in strategy
        assert "sharpe_ratio" in strategy
        assert "trade_count" in strategy

    # Verify daily_pnl
    assert "daily_pnl" in data
    assert len(data["daily_pnl"]) == 30
    first_day = data["daily_pnl"][0]
    assert "date" in first_day
    assert "simple" in first_day
    assert "long_short" in first_day
    assert "threshold" in first_day
    assert "realistic" in first_day


# Gherkin Scenario 2: Empty state when no backtest results exist
@pytest.mark.asyncio
async def test_fetch_backtest_metrics_empty_data(
    client: AsyncClient,
    db_session: Session,
):
    """
    Given the backtest_results table is empty
    When I send GET /api/backtesting/metrics
    Then the response status is 404 Not Found
    And the response contains error message "No backtest results found"
    """
    # Arrange: No backtest results in database (db_session is clean)

    # Act: Fetch backtesting metrics
    response = await client.get("/api/backtesting/metrics")

    # Assert
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert "No backtest results found" in data["detail"]


# Gherkin Scenario 3: Date range filter
@pytest.mark.asyncio
async def test_fetch_backtest_metrics_date_filter(
    client: AsyncClient,
    db_session: Session,
    sample_backtest_results_factory,
):
    """
    Given backtest results from May 1-30 (30 days)
    When I send GET /api/backtesting/metrics?start=2024-05-10&end=2024-05-20
    Then the response status is 200 OK
    And the response contains only 11 days of data (May 10-20 inclusive)
    """
    # Arrange: Create 30 backtest results starting from May 1
    base_date = date(2024, 5, 1)
    backtest_run_id = uuid4()

    for i in range(30):
        predicted_for = base_date + timedelta(days=i)
        result = BacktestResult(
            backtest_run_id=backtest_run_id,
            predicted_for=predicted_for,
            predicted_at=datetime.combine(
                predicted_for - timedelta(days=1), datetime.min.time(), tzinfo=UTC
            ).replace(hour=19),
            price_at_prediction=Decimal("67000.0"),
            predicted_price=Decimal("67500.0"),
            actual_price=Decimal("67800.0"),
            pnl_simple=Decimal("100.0"),
            pnl_long_short=Decimal("120.0"),
            pnl_threshold=Decimal("90.0"),
            pnl_realistic=Decimal("85.0"),
            model_params={"model_name": "linear_v1"},
            created_at=datetime.now(UTC),
        )
        db_session.add(result)

    db_session.commit()

    # Act: Fetch with date filter
    response = await client.get(
        "/api/backtesting/metrics?start=2024-05-10&end=2024-05-20"
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["metadata"]["total_days"] == 11  # May 10-20 inclusive
    assert data["metadata"]["start_date"] == "2024-05-10"
    assert data["metadata"]["end_date"] == "2024-05-20"
    assert len(data["daily_pnl"]) == 11


# Gherkin Scenario 4: Calculate Win Rate correctly
@pytest.mark.asyncio
async def test_calculate_win_rate(
    client: AsyncClient,
    db_session: Session,
):
    """
    Given backtest results with mixed wins and losses
    When the dashboard calculates Win Rate for each strategy
    Then it counts wins (PnL > 0) correctly
    And Win Rate = wins / total_trades
    """
    # Arrange: Create results with known PnL pattern
    # 6 trades: [100, -50, 200, -30, 150, 0]
    # Wins: 3 (100, 200, 150)
    # Losses: 2 (-50, -30)
    # Zeros: 1 (0) - should still be counted in trade_count
    # Win Rate: 3 / 6 = 0.5 (50%)
    backtest_run_id = uuid4()
    pnl_values = [
        Decimal("100.0"),
        Decimal("-50.0"),
        Decimal("200.0"),
        Decimal("-30.0"),
        Decimal("150.0"),
        Decimal("0.0"),
    ]

    base_date = date.today()
    for i, pnl in enumerate(pnl_values):
        result = BacktestResult(
            backtest_run_id=backtest_run_id,
            predicted_for=base_date - timedelta(days=len(pnl_values) - i - 1),
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("67000.0"),
            predicted_price=Decimal("67500.0"),
            actual_price=Decimal("67800.0"),
            pnl_simple=pnl,
            pnl_long_short=pnl,
            pnl_threshold=pnl,
            pnl_realistic=pnl,
            model_params={"model_name": "test_model"},
            created_at=datetime.now(UTC),
        )
        db_session.add(result)

    db_session.commit()

    # Act
    response = await client.get("/api/backtesting/metrics")

    # Assert
    assert response.status_code == 200
    data = response.json()

    # Check simple strategy
    simple_strategy = next(s for s in data["strategies"] if s["name"] == "simple")
    assert simple_strategy["trade_count"] == 6
    assert simple_strategy["win_rate"] == 0.5  # 3 wins / 6 trades


# Gherkin Scenario 5: Calculate Max Drawdown (worst single-day loss)
@pytest.mark.asyncio
async def test_calculate_max_drawdown(
    client: AsyncClient,
    db_session: Session,
):
    """
    Given backtest results with PnL values: [100, -450, 200, -30, 150]
    When the dashboard calculates Max Drawdown
    Then it finds the minimum PnL = -450
    And displays it as Max Drawdown = -450.00
    """
    # Arrange
    backtest_run_id = uuid4()
    pnl_values = [
        Decimal("100.0"),
        Decimal("-450.0"),
        Decimal("200.0"),
        Decimal("-30.0"),
        Decimal("150.0"),
    ]

    base_date = date.today()
    for i, pnl in enumerate(pnl_values):
        result = BacktestResult(
            backtest_run_id=backtest_run_id,
            predicted_for=base_date - timedelta(days=len(pnl_values) - i - 1),
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("67000.0"),
            predicted_price=Decimal("67500.0"),
            actual_price=Decimal("67800.0"),
            pnl_realistic=pnl,
            pnl_simple=pnl,
            pnl_long_short=pnl,
            pnl_threshold=pnl,
            model_params={"model_name": "test_model"},
            created_at=datetime.now(UTC),
        )
        db_session.add(result)

    db_session.commit()

    # Act
    response = await client.get("/api/backtesting/metrics")

    # Assert
    assert response.status_code == 200
    data = response.json()

    realistic_strategy = next(s for s in data["strategies"] if s["name"] == "realistic")
    assert realistic_strategy["max_drawdown"] == -450.0
    assert realistic_strategy["worst_day"] == -450.0


# Gherkin Scenario 6: Best Day and Worst Day correctly identified
@pytest.mark.asyncio
async def test_best_and_worst_day(
    client: AsyncClient,
    db_session: Session,
):
    """
    Given backtest results with PnL values: [100, -50, 320, -30, 150]
    When the dashboard displays Best/Worst Day
    Then Best Day = +320.00 (maximum PnL)
    And Worst Day = -50.00 (minimum PnL)
    """
    # Arrange
    backtest_run_id = uuid4()
    pnl_values = [
        Decimal("100.0"),
        Decimal("-50.0"),
        Decimal("320.0"),
        Decimal("-30.0"),
        Decimal("150.0"),
    ]

    base_date = date.today()
    for i, pnl in enumerate(pnl_values):
        result = BacktestResult(
            backtest_run_id=backtest_run_id,
            predicted_for=base_date - timedelta(days=len(pnl_values) - i - 1),
            predicted_at=datetime.now(UTC),
            price_at_prediction=Decimal("67000.0"),
            predicted_price=Decimal("67500.0"),
            actual_price=Decimal("67800.0"),
            pnl_simple=pnl,
            pnl_long_short=pnl,
            pnl_threshold=pnl,
            pnl_realistic=pnl,
            model_params={"model_name": "test_model"},
            created_at=datetime.now(UTC),
        )
        db_session.add(result)

    db_session.commit()

    # Act
    response = await client.get("/api/backtesting/metrics")

    # Assert
    assert response.status_code == 200
    data = response.json()

    simple_strategy = next(s for s in data["strategies"] if s["name"] == "simple")
    assert simple_strategy["best_day"] == 320.0
    assert simple_strategy["worst_day"] == -50.0


# Gherkin Scenario 7: Dashboard page loads successfully
@pytest.mark.asyncio
async def test_backtesting_dashboard_page_loads(
    client: AsyncClient,
    db_session: Session,
    sample_backtest_results_factory,
):
    """
    Given there is a backtest run with results
    When I navigate to GET /backtesting
    Then I see a page with status 200
    And the page contains "Backtesting Results" title
    """
    # Arrange
    sample_backtest_results_factory(count=10)

    # Act
    response = await client.get("/backtesting")

    # Assert
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert (
        b"Backtesting Results" in response.content
        or b"backtesting" in response.content.lower()
    )


# Gherkin Scenario 8: Dashboard shows empty state
@pytest.mark.asyncio
async def test_backtesting_dashboard_empty_state(
    client: AsyncClient,
    db_session: Session,
):
    """
    Given the backtest_results table is empty
    When I visit /backtesting
    Then I see an empty state message
    And I see instructions to run the backtest script
    """
    # Arrange: Empty database

    # Act
    response = await client.get("/backtesting")

    # Assert
    assert response.status_code == 200
    content = response.content.decode()
    assert "No backtest results" in content or "no data" in content.lower()


# Gherkin Scenario 9: Multiple backtest runs - fetches most recent
@pytest.mark.asyncio
async def test_fetch_most_recent_backtest_run(
    client: AsyncClient,
    db_session: Session,
):
    """
    Given there are 2 backtest runs (run_1 created yesterday, run_2 created today)
    When I send GET /api/backtesting/metrics
    Then the response contains data from run_2 (most recent by created_at)
    """
    # Arrange: Create two backtest runs
    run_1_id = uuid4()
    run_2_id = uuid4()

    # Run 1 - created yesterday
    result_old = BacktestResult(
        backtest_run_id=run_1_id,
        predicted_for=date.today() - timedelta(days=10),
        predicted_at=datetime.now(UTC) - timedelta(days=10),
        price_at_prediction=Decimal("60000.0"),
        predicted_price=Decimal("60500.0"),
        actual_price=Decimal("60800.0"),
        pnl_simple=Decimal("50.0"),
        pnl_long_short=Decimal("60.0"),
        pnl_threshold=Decimal("40.0"),
        pnl_realistic=Decimal("35.0"),
        model_params={"model_name": "old_model"},
        created_at=datetime.now(UTC) - timedelta(days=1),
    )
    db_session.add(result_old)

    # Run 2 - created today
    result_new = BacktestResult(
        backtest_run_id=run_2_id,
        predicted_for=date.today() - timedelta(days=5),
        predicted_at=datetime.now(UTC) - timedelta(days=5),
        price_at_prediction=Decimal("70000.0"),
        predicted_price=Decimal("70500.0"),
        actual_price=Decimal("70800.0"),
        pnl_simple=Decimal("100.0"),
        pnl_long_short=Decimal("120.0"),
        pnl_threshold=Decimal("90.0"),
        pnl_realistic=Decimal("85.0"),
        model_params={"model_name": "new_model"},
        created_at=datetime.now(UTC),
    )
    db_session.add(result_new)
    db_session.commit()

    # Act
    response = await client.get("/api/backtesting/metrics")

    # Assert
    assert response.status_code == 200
    data = response.json()

    # Should fetch run_2 (most recent)
    assert data["metadata"]["backtest_run_id"] == str(run_2_id)
    assert data["metadata"]["model_name"] == "new_model"
