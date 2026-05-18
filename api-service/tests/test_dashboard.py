"""
Integration tests for dashboard web interface.

Tests the GET / endpoint that renders the dashboard HTML:
- Dashboard with predictions shows table
- Dashboard with no data shows empty state message
- Dashboard displays model name and version
"""

import pytest
from bs4 import BeautifulSoup
from httpx import AsyncClient
from sqlalchemy.orm import Session


# Gherkin Scenario 1: Render dashboard with predictions
@pytest.mark.asyncio
async def test_dashboard_with_predictions(
    client: AsyncClient,
    db_session: Session,
    sample_predictions_factory,
):
    """
    Given the predictions table has 10 evaluated records
    When I navigate to GET /
    Then the response status is 200 OK
    And the response content-type is text/html
    And the HTML contains a table with 10 rows (one per prediction)
    And each row shows: predicted_for, predicted_price, actual_price, error_pct, direction_correct
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

    # Each row should have 7 cells: date, price_at_prediction, predicted, actual, error, direction, model
    assert len(cells) == 7

    # Verify cells contain data (not empty)
    for cell in cells:
        assert cell.text.strip() != "", f"Cell should not be empty: {cell}"

    # Verify table header exists
    thead = table.find("thead")
    assert thead is not None
    headers = [th.text.strip() for th in thead.find_all("th")]
    expected_headers = ["Date", "Price at Prediction", "Predicted", "Actual", "Error %", "Direction", "Model"]
    assert headers == expected_headers


# Gherkin Scenario 2: Dashboard with no data
@pytest.mark.asyncio
async def test_dashboard_with_no_data(
    client: AsyncClient,
    db_session: Session,
):
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
    sample_predictions_factory,
):
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
    sample_predictions_factory,
):
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
    sample_predictions_factory,
):
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
    stat_labels = [card.find(class_="stat-label").get_text() for card in stat_cards]
    expected_labels = ["Total Predictions", "Correct Direction", "Avg Error", "Active Model"]

    for expected in expected_labels:
        assert expected in stat_labels, f"Missing stat card: {expected}"

    # Verify first stat shows total count
    first_value = stat_cards[0].find(class_="stat-value").get_text()
    assert "10" in first_value, "Total predictions should be 10"


# Edge case: Verify responsive design meta tag
@pytest.mark.asyncio
async def test_dashboard_responsive_meta_tag(
    client: AsyncClient,
    db_session: Session,
):
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
    assert "width=device-width" in viewport.get("content", "")
