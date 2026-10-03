"""
Asset selector and baselines on the dashboard (#107).

One test (or parametrized group) per Gherkin scenario of the issue:

- The default view shows BTC
- Switching to gold shows only gold data
- Baselines are visible next to each model
- A model that does not beat the baseline is shown as such
- An asset with no predictions yet shows an empty state
- An unknown symbol is rejected
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from bs4 import BeautifulSoup
from httpx import AsyncClient, Response
from soup_helpers import attribute, find_tag
from sqlalchemy.orm import Session

from shared.db.models import BacktestResult, Model, Prediction, Price

BTC = "BTCUSDT"
GOLD = "PAXGUSDT"
FIRST_DAY = date(2026, 1, 1)


def add_model(
    db: Session, symbol: str, name: str = "linear_v1", is_active: bool = True
) -> Model:
    model = Model(
        symbol=symbol,
        name=name,
        version="1.0.0",
        params={"window_days": 21},
        artifact=b"fake_pickle",
        trained_at=datetime.now(UTC),
        train_from=FIRST_DAY,
        train_to=FIRST_DAY + timedelta(days=30),
        is_active=is_active,
    )
    db.add(model)
    db.flush()
    return model


def add_prices(db: Session, symbol: str, closes: list[float]) -> None:
    """Store one daily bar per close, starting at FIRST_DAY (day index 0)."""
    for index, close in enumerate(closes):
        day = FIRST_DAY + timedelta(days=index)
        value = Decimal(str(close))
        db.add(
            Price(
                symbol=symbol,
                timestamp=datetime(day.year, day.month, day.day, tzinfo=UTC),
                open=value,
                high=value,
                low=value,
                close=value,
                volume=Decimal("10"),
                source="test",
            )
        )
    db.flush()


def add_evaluated_predictions(
    db: Session,
    model: Model,
    closes: list[float],
    predicts_up: list[bool] | None = None,
    start_index: int = 2,
) -> None:
    """
    Evaluate the model on every day from ``start_index``: price_at_prediction is the
    previous close, actual_price the day's close. ``predicts_up[i]`` is the model's
    direction for the i-th evaluated day (default: always right).
    """
    for offset, index in enumerate(range(start_index, len(closes))):
        price_at = Decimal(str(closes[index - 1]))
        actual = Decimal(str(closes[index]))
        actual_up = actual >= price_at
        up = actual_up if predicts_up is None else predicts_up[offset]
        predicted = price_at + (Decimal("5") if up else Decimal("-5"))
        pnl = actual - price_at if up else Decimal("0")
        day = FIRST_DAY + timedelta(days=index)
        db.add(
            Prediction(
                model_id=model.id,
                predicted_for=day,
                predicted_at=datetime(day.year, day.month, day.day, tzinfo=UTC)
                - timedelta(hours=5),
                price_at_prediction=price_at,
                predicted_price=predicted,
                actual_price=actual,
                evaluated_at=datetime(day.year, day.month, day.day, 7, tzinfo=UTC),
                error_abs=abs(actual - predicted),
                error_pct=abs(actual - predicted) / actual * 100,
                direction_correct=(up == actual_up),
                pnl_simulated=pnl,
                pnl_long_short=pnl,
                pnl_threshold=Decimal("0"),
                pnl_realistic=pnl,
            )
        )
    db.flush()


def alternating(low: float, high: float, days: int) -> list[float]:
    """low, high, low, high, ...: half the days up, persistence always wrong."""
    return [low if i % 2 == 0 else high for i in range(days)]


def add_backtest_run(db: Session, symbol: str | None, created_at: datetime) -> None:
    """One-day backtest run; ``symbol=None`` mimics rows stored before #106."""
    params = {"model_name": "linear"} | ({"symbol": symbol} if symbol else {})
    db.add(
        BacktestResult(
            backtest_run_id=uuid.uuid4(),
            predicted_for=FIRST_DAY,
            predicted_at=created_at,
            price_at_prediction=Decimal("100"),
            predicted_price=Decimal("101"),
            actual_price=Decimal("102"),
            pnl_simple=Decimal("2"),
            pnl_long_short=Decimal("2"),
            pnl_threshold=Decimal("0"),
            pnl_realistic=Decimal("1"),
            model_params=params,
            created_at=created_at,
        )
    )
    db.flush()


def soup_of(response: Response) -> BeautifulSoup:
    assert response.status_code == 200
    return BeautifulSoup(response.text, "html.parser")


def table_rows(soup: BeautifulSoup) -> list[list[str]]:
    body = soup.find("tbody")
    assert body is not None
    return [
        [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
        for row in body.find_all("tr")
    ]


@pytest.fixture
def both_assets(db_session: Session) -> dict[str, Model]:
    """BTC (~67k) and gold (~2k) models, each with 10 evaluated daily predictions."""
    btc_closes = alternating(67000, 67500, 12)
    gold_closes = alternating(2000, 2010, 12)
    btc = add_model(db_session, BTC)
    gold = add_model(db_session, GOLD)
    add_prices(db_session, BTC, btc_closes)
    add_prices(db_session, GOLD, gold_closes)
    add_evaluated_predictions(db_session, btc, btc_closes)
    add_evaluated_predictions(db_session, gold, gold_closes)
    db_session.commit()
    return {BTC: btc, GOLD: gold}


# Scenario: The default view shows BTC
@pytest.mark.asyncio
async def test_default_dashboard_shows_btc(
    client: AsyncClient, both_assets: dict[str, Model]
) -> None:
    """
    When I open the dashboard
    Then it shows data for BTCUSDT
    """
    soup = soup_of(await client.get("/"))

    rows = table_rows(soup)
    assert len(rows) == 10
    assert all(row[1].startswith("$67") for row in rows), "only BTC prices expected"
    assert "Bitcoin" in find_tag(soup, "h1").get_text()
    selected = find_tag(soup, "a", attrs={"aria-current": "page"})
    assert attribute(selected, "data-symbol") == BTC
    assert soup.find(class_="asset-note") is None, "no caveat for BTC"


# Scenario: Switching to gold shows only gold data
@pytest.mark.asyncio
async def test_gold_dashboard_shows_only_gold_and_states_the_proxy(
    client: AsyncClient, both_assets: dict[str, Model]
) -> None:
    """
    Given predictions exist for BTCUSDT and PAXGUSDT
    When I select gold
    Then every table and chart shows PAXGUSDT data only
    And the page states that gold is a gold-backed token proxy
    """
    soup = soup_of(await client.get("/", params={"symbol": GOLD}))

    rows = table_rows(soup)
    assert len(rows) == 10
    assert all(row[1].startswith("$20") for row in rows), "only gold prices expected"
    # The strategy chart and table are built from the same asset.
    strategies = soup.find(class_="strategy-table")
    assert strategies is not None
    note = find_tag(soup, class_="asset-note").get_text()
    assert "gold-backed token" in note
    assert "not XAU spot" in note
    assert (
        attribute(find_tag(soup, "a", attrs={"aria-current": "page"}), "data-symbol")
        == GOLD
    )


@pytest.mark.asyncio
async def test_gold_strategy_chart_data_has_only_gold_pnl(
    client: AsyncClient, both_assets: dict[str, Model]
) -> None:
    """The strategies JSON behind the chart only counts gold predictions."""
    gold = await client.get("/api/predictions/strategies", params={"symbol": GOLD})
    btc = await client.get("/api/predictions/strategies")

    gold_simple = gold.json()["strategies"][0]
    btc_simple = btc.json()["strategies"][0]
    assert gold_simple["trade_count"] == 10
    assert btc_simple["trade_count"] == 10
    assert gold_simple["total_pnl"] == 50.0  # five +10 days
    assert btc_simple["total_pnl"] == 2500.0  # five +500 days


@pytest.mark.asyncio
async def test_json_endpoints_are_scoped_to_the_symbol(
    client: AsyncClient, both_assets: dict[str, Model]
) -> None:
    history = await client.get("/api/predictions/history", params={"symbol": GOLD})
    assert len(history.json()) == 10
    assert all(item["price_at_prediction"] < 5000 for item in history.json())

    history_default = await client.get("/api/predictions/history")
    assert len(history_default.json()) == 10
    assert all(item["price_at_prediction"] > 60000 for item in history_default.json())

    pnl = await client.get("/api/predictions/pnl", params={"symbol": GOLD})
    assert pnl.json() == {"total_pnl": 50.0, "evaluated_predictions": 10}

    metrics = await client.get("/models/metrics", params={"symbol": GOLD})
    body = metrics.json()
    assert [m["symbol"] for m in body["models"]] == [GOLD]
    assert body["filters"]["symbol"] == GOLD
    assert body["models"][0]["predictions_count"] == 10


@pytest.mark.asyncio
async def test_prices_endpoint_returns_only_the_requested_symbol(
    client: AsyncClient, both_assets: dict[str, Model]
) -> None:
    gold = await client.get("/api/prices", params={"symbol": GOLD, "limit": 50})
    btc = await client.get("/api/prices", params={"limit": 50})

    assert len(gold.json()) == 12
    assert all(float(p["close"]) < 5000 for p in gold.json())
    assert len(btc.json()) == 12
    assert all(float(p["close"]) > 60000 for p in btc.json())


@pytest.mark.asyncio
async def test_models_view_lists_only_the_selected_assets_models(
    client: AsyncClient, both_assets: dict[str, Model]
) -> None:
    soup = soup_of(await client.get("/models/", params={"symbol": GOLD}))

    rows = table_rows(soup)
    assert len(rows) == 1
    assert "10" in rows[0][1]
    assert "gold-backed token" in find_tag(soup, class_="asset-note").get_text()


@pytest.mark.asyncio
async def test_backtesting_shows_the_latest_run_of_the_selected_symbol(
    client: AsyncClient, db_session: Session
) -> None:
    """A newer gold run never replaces the BTC view, and legacy rows count as BTC."""
    now = datetime.now(UTC)
    add_backtest_run(db_session, None, now - timedelta(days=2))  # legacy, BTC
    add_backtest_run(db_session, GOLD, now - timedelta(days=1))
    db_session.commit()

    btc = await client.get("/api/backtesting/metrics")
    gold = await client.get("/api/backtesting/metrics", params={"symbol": GOLD})
    page = await client.get("/backtesting", params={"symbol": GOLD})

    assert btc.status_code == 200
    assert gold.status_code == 200
    assert (
        btc.json()["metadata"]["backtest_run_id"]
        != (gold.json()["metadata"]["backtest_run_id"])
    )
    assert (
        "gold-backed token" in find_tag(soup_of(page), class_="asset-note").get_text()
    )


# Scenario: Baselines are visible next to each model
@pytest.mark.asyncio
async def test_models_view_shows_baselines_next_to_each_model(
    client: AsyncClient, db_session: Session
) -> None:
    """
    When I open the models view
    Then each model row shows the always-up and persistence baseline accuracy for
    the same period

    Alternating 100/110 closes, 10 evaluated days: half of them rise (always-up
    50.0%), and persistence repeats yesterday's direction, which is always wrong
    here (0.0%). The model is right every day.
    """
    closes = alternating(100, 110, 12)
    model = add_model(db_session, BTC)
    add_prices(db_session, BTC, closes)
    add_evaluated_predictions(db_session, model, closes)
    db_session.commit()

    soup = soup_of(await client.get("/models/"))

    row = table_rows(soup)[0]
    always_up, persistence, buy_and_hold, verdict = row[8:12]
    assert always_up.startswith("50.0%")
    assert "n=10" in always_up
    assert persistence.startswith("0.0%")
    assert "n=10" in persistence
    # Held from the close before the first evaluated day to the last close: 110 -> 110.
    assert buy_and_hold.startswith("$0.00")
    assert "Beats baseline" in verdict
    assert "+50.0 pts vs always-up" in verdict
    assert "n=10" in verdict


# Scenario: A model that does not beat the baseline is shown as such
@pytest.mark.asyncio
async def test_model_below_always_up_is_marked_as_not_beating(
    client: AsyncClient, db_session: Session
) -> None:
    """
    Given a model whose accuracy is below the always-up baseline
    When I open the models view
    Then it is marked as not beating the baseline

    Prices rise every day (always-up 100%) and the model predicts a fall every day
    (accuracy 0%).
    """
    closes = [100.0 + i for i in range(12)]
    model = add_model(db_session, BTC)
    add_prices(db_session, BTC, closes)
    add_evaluated_predictions(db_session, model, closes, predicts_up=[False] * 10)
    db_session.commit()

    soup = soup_of(await client.get("/models/"))

    cell = find_tag(soup, "td", class_="baseline-verdict")
    assert attribute(cell, "data-verdict") == "not_beating"
    assert "Does not beat baseline" in cell.get_text()
    assert "✗" in cell.get_text(), "state must not rely on color alone"
    assert soup.find(class_="verdict-not-beating") is not None
    body = (await client.get("/models/metrics")).json()
    assert body["models"][0]["baseline"]["verdict"] == "not_beating"
    assert body["models"][0]["baseline"]["edge"] == pytest.approx(-1.0)


@pytest.mark.asyncio
async def test_small_edge_is_marked_not_significant(
    client: AsyncClient, db_session: Session
) -> None:
    """Above the baseline on 4 days is a coin-flip streak, not evidence."""
    closes = alternating(100, 110, 6)  # 4 evaluated days, 2 up
    model = add_model(db_session, BTC)
    add_prices(db_session, BTC, closes)
    add_evaluated_predictions(db_session, model, closes)
    db_session.commit()

    soup = soup_of(await client.get("/models/"))

    cell = find_tag(soup, "td", class_="baseline-verdict")
    assert attribute(cell, "data-verdict") == "inconclusive"
    assert "Not significant" in cell.get_text()


@pytest.mark.asyncio
async def test_weekly_timeframe_has_no_baseline(
    client: AsyncClient, db_session: Session
) -> None:
    """Persistence needs a daily horizon, so weekly shows N/A, never a number."""
    closes = alternating(100, 110, 12)
    model = add_model(db_session, BTC)
    add_prices(db_session, BTC, closes)
    add_evaluated_predictions(db_session, model, closes)
    db_session.commit()

    body = (await client.get("/models/metrics", params={"timeframe": "1w"})).json()

    assert body["models"][0]["baseline"] is None


# Scenario: An asset with no predictions yet shows an empty state
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "needle"),
    [
        ("/", "No predictions yet for Gold"),
        ("/models/", "No Models Found for Gold"),
        ("/backtesting", "No backtest results found for PAXGUSDT"),
    ],
)
async def test_asset_without_predictions_shows_an_empty_state(
    client: AsyncClient, db_session: Session, path: str, needle: str
) -> None:
    """
    Given no predictions exist for the selected asset
    When I open its dashboard
    Then an explanatory empty state is shown instead of errors
    """
    btc = add_model(db_session, BTC)
    closes = alternating(100, 110, 12)
    add_prices(db_session, BTC, closes)
    add_evaluated_predictions(db_session, btc, closes)
    db_session.commit()

    response = await client.get(path, params={"symbol": GOLD})

    soup = soup_of(response)
    assert needle in find_tag(soup, class_="empty-state").get_text()
    assert "gold-backed token" in find_tag(soup, class_="asset-note").get_text()


@pytest.mark.asyncio
async def test_empty_json_endpoints_return_empty_results_for_a_new_asset(
    client: AsyncClient, db_session: Session
) -> None:
    history = await client.get("/api/predictions/history", params={"symbol": GOLD})
    metrics = await client.get("/models/metrics", params={"symbol": GOLD})

    assert history.status_code == 200
    assert history.json() == []
    assert metrics.status_code == 200
    assert metrics.json()["models"] == []


# Scenario: An unknown symbol is rejected
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/models/",
        "/models/metrics",
        "/backtesting",
        "/api/backtesting/metrics",
        "/api/predictions/history",
        "/api/predictions/pnl",
        "/api/predictions/strategies",
        "/api/prices",
    ],
)
async def test_unknown_symbol_is_a_validation_error(
    client: AsyncClient, db_session: Session, path: str
) -> None:
    """
    When I request the API with symbol "FOO"
    Then it responds with a validation error
    """
    response = await client.get(path, params={"symbol": "FOO"})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "symbol"]


@pytest.mark.asyncio
async def test_selector_links_keep_the_other_filters(
    client: AsyncClient, db_session: Session
) -> None:
    """Switching asset keeps dates and timeframe; links are relative."""
    soup = soup_of(
        await client.get(
            "/models/", params={"start_date": "2026-01-01", "timeframe": "1d"}
        )
    )

    links = {
        attribute(a, "data-symbol"): attribute(a, "href")
        for a in soup.select("a.asset-option")
    }
    assert set(links) == {BTC, GOLD}
    gold_href = links[GOLD]
    assert gold_href.startswith("?")
    assert "start_date=2026-01-01" in gold_href
    assert "timeframe=1d" in gold_href
    assert "symbol=PAXGUSDT" in gold_href
    # The selected option is marked by a glyph and aria-current, not only by color.
    selected = find_tag(soup, "a", attrs={"aria-current": "page"})
    assert selected.get_text(strip=True).startswith("✓")
    # The date filter form keeps the asset when submitted.
    hidden = find_tag(soup, "input", attrs={"name": "symbol", "type": "hidden"})
    assert attribute(hidden, "value") == BTC
