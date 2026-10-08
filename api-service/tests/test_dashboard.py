"""
Integration tests for dashboard web interface.

Tests the GET / endpoint that renders the dashboard HTML:
- Dashboard with predictions shows table
- Dashboard with no data shows empty state message
- Dashboard displays model name and version
"""

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from bs4 import BeautifulSoup
from httpx import AsyncClient
from soup_helpers import attribute, find_tag
from sqlalchemy.orm import Session

from shared.db.models import Model, Prediction


# Gherkin Scenario 1: Render dashboard with predictions
@pytest.mark.asyncio
async def test_dashboard_with_predictions(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_factory: Callable[..., list[Prediction]],
) -> None:
    """
    Given the predictions table has 10 evaluated records
    When I navigate to GET /
    Then the response status is 200 OK
    And the response content-type is text/html
    And the HTML contains a table with 10 rows (one per prediction)
    And each row shows: predicted_for, predicted_price, actual_price, error_pct,
    direction_correct
    """
    # Arrange: Create 10 evaluated predictions
    sample_predictions_factory(count=10, evaluated=True)

    # Act: Fetch dashboard
    response = await client.get("/")

    # Assert
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    # Parse HTML
    soup = BeautifulSoup(response.text, "html.parser")

    # Verify table exists
    table = soup.find("table")
    assert table is not None, "Dashboard should contain a table"

    # Verify table has tbody
    tbody = table.find("tbody")
    assert tbody is not None, "Table should have tbody"

    # Verify number of rows
    rows = tbody.find_all("tr")
    assert len(rows) == 10, f"Expected 10 rows, got {len(rows)}"

    # Verify first row contains expected data
    first_row = rows[0]
    cells = first_row.find_all("td")

    # Each row should have 7 cells: date, price_at_prediction, predicted, actual,
    # error, direction, model
    assert len(cells) == 7

    # Verify cells contain data (not empty)
    for cell in cells:
        assert cell.text.strip() != "", f"Cell should not be empty: {cell}"

    # Verify table header exists
    thead = table.find("thead")
    assert thead is not None
    headers = [th.text.strip() for th in thead.find_all("th")]
    expected_headers = [
        "Date",
        "Price at Prediction",
        "Predicted",
        "Actual",
        "Error %",
        "Direction",
        "Model",
    ]
    assert headers == expected_headers


# Gherkin Scenario 2: Dashboard with no data
@pytest.mark.asyncio
async def test_dashboard_with_no_data(
    client: AsyncClient,
    db_session: Session,
) -> None:
    """
    Given the predictions table is empty
    When I navigate to GET /
    Then the HTML contains a message "No predictions yet"
    """
    # Arrange: No predictions in database (db_session is clean)

    # Act: Fetch dashboard
    response = await client.get("/")

    # Assert
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    # Parse HTML
    soup = BeautifulSoup(response.text, "html.parser")

    # Verify empty state message
    empty_state = soup.find(class_="empty-state")
    assert empty_state is not None, "Dashboard should show empty state when no data"

    # Verify message text
    text = empty_state.get_text()
    assert "No predictions yet" in text

    # Verify table does NOT exist
    table = soup.find("table")
    assert table is None, "Dashboard should not show table when no data"


# Gherkin Scenario 3: Dashboard shows model name
@pytest.mark.asyncio
async def test_dashboard_shows_model_name(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_factory: Callable[..., list[Prediction]],
) -> None:
    """
    Given a prediction was made by model "linear_v1"
    When I navigate to GET /
    Then the table row shows "linear_v1" in the Model column
    """
    # Arrange: Create predictions with known model
    sample_predictions_factory(count=5, evaluated=True)

    # Act: Fetch dashboard
    response = await client.get("/")

    # Assert
    assert response.status_code == 200

    # Parse HTML
    soup = BeautifulSoup(response.text, "html.parser")

    # Find model badges
    model_badges = soup.find_all(class_="model-badge")
    assert len(model_badges) > 0, "Dashboard should show model badges"

    # Verify model name in first badge
    first_badge = model_badges[0]
    badge_text = first_badge.get_text()
    assert "linear_v1" in badge_text
    assert "v1.0.0" in badge_text


# Additional test: Verify direction indicators
@pytest.mark.asyncio
async def test_dashboard_direction_indicators(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_factory: Callable[..., list[Prediction]],
) -> None:
    """
    Test that direction correctness is visualized with checkmarks and X marks.
    """
    # Arrange
    sample_predictions_factory(count=5, evaluated=True)

    # Act
    response = await client.get("/")

    # Assert
    soup = BeautifulSoup(response.text, "html.parser")

    # Find direction spans
    correct_directions = soup.find_all(class_="correct")
    incorrect_directions = soup.find_all(class_="incorrect")

    # Should have direction indicators (either correct or incorrect)
    total_directions = len(correct_directions) + len(incorrect_directions)
    assert total_directions == 5, "Each prediction should have a direction indicator"

    # Verify correct direction has checkmark
    if correct_directions:
        assert "✓" in correct_directions[0].get_text()

    # Verify incorrect direction has X mark
    if incorrect_directions:
        assert "✗" in incorrect_directions[0].get_text()


# Additional test: Verify stats summary
@pytest.mark.asyncio
async def test_dashboard_stats_summary(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_factory: Callable[..., list[Prediction]],
) -> None:
    """
    Test that dashboard shows summary statistics cards.
    """
    # Arrange: Create predictions
    sample_predictions_factory(count=10, evaluated=True)

    # Act
    response = await client.get("/")

    # Assert
    soup = BeautifulSoup(response.text, "html.parser")

    # Find stats section
    stats = soup.find(class_="stats")
    assert stats is not None, "Dashboard should show stats summary"

    # Find stat cards
    stat_cards = stats.find_all(class_="stat-card")
    assert len(stat_cards) == 4, "Should show 4 stat cards"

    # Verify stat labels
    stat_labels = [
        find_tag(card, class_="stat-label").get_text() for card in stat_cards
    ]
    expected_labels = [
        "Total Predictions",
        "Correct Direction",
        "Avg Error",
        "Active Model",
    ]

    for expected in expected_labels:
        assert expected in stat_labels, f"Missing stat card: {expected}"

    # Verify first stat shows total count
    first_value = find_tag(stat_cards[0], class_="stat-value").get_text()
    assert "10" in first_value, "Total predictions should be 10"


# Edge case: Verify responsive design meta tag
@pytest.mark.asyncio
async def test_dashboard_responsive_meta_tag(
    client: AsyncClient,
    db_session: Session,
) -> None:
    """
    Verify that dashboard includes viewport meta tag for responsive design.
    """
    # Act
    response = await client.get("/")

    # Assert
    soup = BeautifulSoup(response.text, "html.parser")

    # Find viewport meta tag
    viewport = soup.find("meta", attrs={"name": "viewport"})
    assert viewport is not None, "Dashboard should have viewport meta tag"
    assert "width=device-width" in attribute(viewport, "content")


# Gherkin: Redundant non-color signal for PnL indicators (accessibility)
@pytest.mark.asyncio
async def test_pnl_glyphs_are_redundant_non_color_signal(
    client: AsyncClient,
    db_session: Session,
    sample_model: Model,
) -> None:
    """
    Given a strategy row with total_pnl >= 0 and another with total_pnl < 0
    When dashboard.html renders the positive-pnl/negative-pnl cells
    Then each cell is prefixed with a glyph (▲ for positive, ▼ for negative)
    in addition to its color, and the static max_drawdown/avg_win/avg_loss
    columns also carry their corresponding glyph.
    """
    # Arrange: one winning trade (positive total_pnl) so the "simple"
    # strategy renders with the positive-pnl class and glyph.
    db_session.add(
        Prediction(
            model_id=sample_model.id,
            predicted_for=date(2024, 5, 1),
            predicted_at=datetime(2024, 4, 30, 10, 0, tzinfo=UTC),
            price_at_prediction=Decimal("67000.00"),
            predicted_price=Decimal("68000.00"),
            actual_price=Decimal("67500.00"),
            evaluated_at=datetime(2024, 5, 1, 10, 0, tzinfo=UTC),
            error_abs=Decimal("500.00"),
            error_pct=Decimal("0.74"),
            direction_correct=True,
            pnl_simulated=Decimal("500.00"),
        )
    )
    db_session.commit()

    # Act
    response = await client.get("/")

    # Assert
    soup = BeautifulSoup(response.text, "html.parser")

    positive_cells = soup.find_all(class_="positive-pnl")
    negative_cells = soup.find_all(class_="negative-pnl")

    assert positive_cells, "Expected at least one positive-pnl cell"
    assert negative_cells, "Expected at least one negative-pnl cell"

    assert any("▲" in cell.get_text() for cell in positive_cells), (
        "positive-pnl cells should be prefixed with a ▲ glyph"
    )
    assert any("▼" in cell.get_text() for cell in negative_cells), (
        "negative-pnl cells should be prefixed with a ▼ glyph"
    )


@pytest.mark.asyncio
async def test_dashboard_has_no_weekly_tab(
    client: AsyncClient, db_session: Session
) -> None:
    """
    Gherkin: The dashboard renders without a Weekly tab (#183).

    When I navigate to GET /
    Then the page has the Daily tab and no tab for the 1w timeframe
    """
    response = await client.get("/")

    assert response.status_code == 200
    soup = BeautifulSoup(response.text, "html.parser")
    tabs = {tab.get("data-timeframe") for tab in soup.select("button.tab")}
    assert tabs == {"1d"}
    assert "Weekly" not in soup.get_text()


@pytest.mark.asyncio
async def test_dashboard_shows_worst_trade_and_max_drawdown_as_two_figures(
    client: AsyncClient,
    db_session: Session,
    sample_model: Model,
) -> None:
    """
    Given three predictions with returns of +10%, -10% and -10%
    When the dashboard renders
    Then the strategies table has a "Worst trade" column (the minimum single-day
    return, -10.00%) and a "Max drawdown" column (from the compounded equity
    curve, -19.00%), as two different figures (#177)
    """
    for day, pnl in [(1, "10"), (2, "-10"), (3, "-10")]:
        db_session.add(
            Prediction(
                model_id=sample_model.id,
                predicted_for=date(2024, 5, day),
                predicted_at=datetime(2024, 5, day, 0, 10, tzinfo=UTC),
                price_at_prediction=Decimal("100.00"),
                predicted_price=Decimal("101.00"),
                actual_price=Decimal("100.00") + Decimal(pnl),
                evaluated_at=datetime(2024, 5, day, 10, 0, tzinfo=UTC),
                error_abs=Decimal("1.00"),
                error_pct=Decimal("1.00"),
                direction_correct=True,
                pnl_simulated=Decimal(pnl),
                pnl_long_short=Decimal(pnl),
                pnl_threshold=Decimal(pnl),
                pnl_realistic=Decimal(pnl),
            )
        )
    db_session.commit()

    response = await client.get("/")

    soup = BeautifulSoup(response.text, "html.parser")
    table = find_tag(soup, "table", class_="strategy-table")
    headers = [th.get_text(strip=True) for th in table.find_all("th")]
    assert "Worst trade" in headers
    assert "Max drawdown" in headers
    assert "Max Drawdown" not in headers
    row = find_tag(find_tag(table, "tbody"), "tr")
    cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
    assert cells[headers.index("Worst trade")] == "▼ -10.00%"
    assert cells[headers.index("Max drawdown")] == "▼ -19.00%"


@pytest.mark.asyncio
async def test_dashboard_states_the_assumptions_of_each_strategy(
    client: AsyncClient,
    db_session: Session,
    sample_model: Model,
) -> None:
    """
    Given the strategies table is shown
    Then the page states, next to it, that shorting is not possible on Binance spot
    and funding is not modeled, that the fee is charged every day, and that the
    stop-loss acts on closes because there is no intraday data (#177)
    """
    db_session.add(
        Prediction(
            model_id=sample_model.id,
            predicted_for=date(2024, 5, 1),
            predicted_at=datetime(2024, 4, 30, 10, 0, tzinfo=UTC),
            price_at_prediction=Decimal("100.00"),
            predicted_price=Decimal("101.00"),
            actual_price=Decimal("101.00"),
            evaluated_at=datetime(2024, 5, 1, 10, 0, tzinfo=UTC),
            error_abs=Decimal("0.00"),
            error_pct=Decimal("0.00"),
            direction_correct=True,
            pnl_simulated=Decimal("1"),
        )
    )
    db_session.commit()

    response = await client.get("/")

    soup = BeautifulSoup(response.text, "html.parser")
    text = find_tag(soup, "div", class_="strategy-assumptions").get_text(
        " ", strip=True
    )
    assert "Shorting is not possible on Binance spot" in text
    assert "funding" in text
    assert "fee charged every day" in text
    assert "no intraday data" in text
