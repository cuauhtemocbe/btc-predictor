"""
Replayed (simulated) predictions are labeled and shown apart from live ones (#176).

The replay trains models that carry ``params["simulated"] = True``; the history,
the dashboard and the models page must tell them apart from the live models.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from bs4 import BeautifulSoup, Tag
from httpx import AsyncClient
from soup_helpers import find_tag
from sqlalchemy.orm import Session

from shared.db.models import Model, Prediction

FIRST_DAY = date(2026, 9, 1)


def _model(db: Session, name: str, params: dict[str, Any]) -> Model:
    model = Model(
        name=name,
        version="sim-2026.09.01" if params.get("simulated") else "1.0.0",
        params=params,
        artifact=b"fake_pickle",
        trained_at=datetime(2026, 9, 1, tzinfo=UTC),
        train_from=date(2026, 8, 1),
        train_to=date(2026, 8, 31),
        is_active=False,
    )
    db.add(model)
    db.flush()
    return model


def _predictions(
    db: Session, model: Model, count: int, offset: int, correct: bool
) -> None:
    """``count`` evaluated daily predictions of ``model`` on distinct days."""
    for i in range(offset, offset + count):
        day = FIRST_DAY + timedelta(days=i)
        db.add(
            Prediction(
                model_id=model.id,
                predicted_for=day,
                timeframe="1d",
                predicted_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
                price_at_prediction=Decimal("100"),
                predicted_price=Decimal("101"),
                actual_price=Decimal("102") if correct else Decimal("99"),
                evaluated_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
                error_abs=Decimal("1"),
                error_pct=Decimal("1"),
                direction_correct=correct,
                pnl_simulated=Decimal("2") if correct else Decimal("0"),
            )
        )
    db.flush()


@pytest.fixture
def mixed_sources(db_session: Session) -> dict[str, Model]:
    """3 replay rows (all wrong, $0 PnL) and 2 live rows (all right, $2 each)."""
    replay = _model(db_session, "linear_v1", {"window_days": 21, "simulated": True})
    live = _model(db_session, "linear_v1", {"window_days": 21})
    _predictions(db_session, replay, count=3, offset=0, correct=False)
    _predictions(db_session, live, count=2, offset=3, correct=True)
    db_session.commit()
    return {"replay": replay, "live": live}


# Gherkin 1: the history labels each row
@pytest.mark.asyncio
async def test_history_rows_carry_is_replay(
    client: AsyncClient, mixed_sources: dict[str, Model]
) -> None:
    """
    Given a prediction of a model with params.simulated = true
    When /api/predictions/history is called
    Then its row has is_replay: true; for a normal model, false
    """
    rows = (await client.get("/api/predictions/history")).json()

    by_model = {(r["model_version"], r["is_replay"]) for r in rows}
    assert by_model == {("sim-2026.09.01", True), ("1.0.0", False)}
    assert sum(r["is_replay"] for r in rows) == 3


@pytest.mark.asyncio
async def test_simulated_false_is_not_a_replay(
    client: AsyncClient, db_session: Session
) -> None:
    """Only a true ``simulated`` marks a replay; false is a live model."""
    model = _model(db_session, "linear_v1", {"simulated": False})
    _predictions(db_session, model, count=1, offset=0, correct=True)
    db_session.commit()

    rows = (await client.get("/api/predictions/history?source=live")).json()

    assert [r["is_replay"] for r in rows] == [False]


# Gherkin 2: the source parameter filters in SQL
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected_rows", "expected_replay"),
    [
        ("?source=live", 2, {False}),
        ("?source=replay", 3, {True}),
        ("?source=all", 5, {True, False}),
        ("", 5, {True, False}),
    ],
)
async def test_history_source_filter(
    client: AsyncClient,
    mixed_sources: dict[str, Model],
    query: str,
    expected_rows: int,
    expected_replay: set[bool],
) -> None:
    """
    Given 3 replay rows and 2 live rows
    When the history is requested with source=live, replay, or without it
    Then it returns 2, 3 and 5 rows
    """
    rows = (await client.get(f"/api/predictions/history{query}")).json()

    assert len(rows) == expected_rows
    assert {r["is_replay"] for r in rows} == expected_replay


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/api/predictions/history", "/", "/models/", "/models/metrics"]
)
async def test_invalid_source_is_rejected(client: AsyncClient, path: str) -> None:
    """An unknown source fails validation instead of showing everything."""
    response = await client.get(f"{path}?source=simulated")

    assert response.status_code == 422


def _block(soup: BeautifulSoup, key: str) -> Tag:
    return find_tag(soup, "section", attrs={"data-source": key})


def _block_values(block: Tag) -> dict[str, str]:
    """Text of the count, accuracy and PnL cells of one headline block."""
    return {
        name: find_tag(block, class_=f"source-{name}").get_text(strip=True)
        for name in ("count", "accuracy", "pnl")
    }


# Gherkin 3: the dashboard separates the headline numbers
@pytest.mark.asyncio
async def test_dashboard_scores_live_and_replay_in_separate_blocks(
    client: AsyncClient, mixed_sources: dict[str, Model]
) -> None:
    """
    Given the same data
    When the dashboard renders
    Then replay and live accuracy and PnL appear in separate blocks, each with its
    row count, and the combined block is labeled live + replay
    """
    soup = BeautifulSoup((await client.get("/")).text, "html.parser")

    assert _block_values(_block(soup, "live")) == {
        "count": "2",
        "accuracy": "100.0%",
        "pnl": "▲ $4.00",
    }
    assert _block_values(_block(soup, "replay")) == {
        "count": "3",
        "accuracy": "0.0%",
        "pnl": "▲ $0.00",
    }
    combined = _block(soup, "combined")
    assert find_tag(combined, "h3").get_text(strip=True) == "Live + replay"
    assert find_tag(combined, class_="source-count").get_text(strip=True) == "5"


@pytest.mark.asyncio
async def test_dashboard_blocks_show_baselines_next_to_each_source(
    client: AsyncClient, mixed_sources: dict[str, Model]
) -> None:
    """Each block carries the always-up baseline of its own days."""
    soup = BeautifulSoup((await client.get("/")).text, "html.parser")

    # Live days closed above the prediction price, replay days below it.
    live = find_tag(_block(soup, "live"), class_="source-always-up")
    replay = find_tag(_block(soup, "replay"), class_="source-always-up")
    assert live.get_text(strip=True) == "100.0%"
    assert replay.get_text(strip=True) == "0.0%"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "blocks"),
    [
        ("?source=live", ["live"]),
        ("?source=replay", ["replay"]),
        ("?source=all", ["live", "replay", "combined"]),
        ("", ["live", "replay", "combined"]),
    ],
)
async def test_combined_block_only_under_source_all(
    client: AsyncClient,
    mixed_sources: dict[str, Model],
    query: str,
    blocks: list[str],
) -> None:
    """A combined total never appears when one source was asked for."""
    soup = BeautifulSoup((await client.get(f"/{query}")).text, "html.parser")

    shown = [
        str(s["data-source"]) for s in soup.find_all("section", class_="source-block")
    ]
    assert shown == blocks


@pytest.mark.asyncio
async def test_dashboard_marks_replay_rows_with_a_badge(
    client: AsyncClient, mixed_sources: dict[str, Model]
) -> None:
    """Replay rows wear a Replay badge; live rows do not."""
    soup = BeautifulSoup((await client.get("/")).text, "html.parser")

    rows = find_tag(soup, "table").find_all("tr")[1:]
    badged = [bool(r.find(class_="replay-badge")) for r in rows]
    assert sorted(badged) == [False, False, True, True, True]


@pytest.mark.asyncio
async def test_dashboard_without_live_rows_shows_an_empty_live_block(
    client: AsyncClient, db_session: Session
) -> None:
    """A missing live history is visible as 0 predictions, not silently absent."""
    replay = _model(db_session, "linear_v1", {"simulated": True})
    _predictions(db_session, replay, count=2, offset=0, correct=True)
    db_session.commit()

    soup = BeautifulSoup((await client.get("/")).text, "html.parser")

    live = _block(soup, "live")
    assert "0 predictions" in live.get_text()
    assert _block_values(_block(soup, "replay"))["count"] == "2"


@pytest.mark.asyncio
async def test_dashboard_source_filter_scopes_the_rows_and_strategies(
    client: AsyncClient, mixed_sources: dict[str, Model]
) -> None:
    """source=live keeps only live rows in the table and in the strategy table."""
    soup = BeautifulSoup((await client.get("/?source=live")).text, "html.parser")

    rows = find_tag(soup, "table").find_all("tr")[1:]
    assert len(rows) == 2
    assert all(r.find(class_="replay-badge") is None for r in rows)
    strategy_trades = find_tag(soup, class_="strategy-table").find_all("tr")[1]
    assert strategy_trades.find_all("td")[-1].get_text(strip=True) == "2"


@pytest.mark.asyncio
async def test_source_selector_keeps_the_other_filters(
    client: AsyncClient, mixed_sources: dict[str, Model]
) -> None:
    """Each source option links to the same page, replacing only ``source``."""
    soup = BeautifulSoup(
        (await client.get("/?timeframe=1d&source=live")).text, "html.parser"
    )

    options = {
        str(a["data-source"]): a for a in soup.find_all("a", class_="source-option")
    }
    assert set(options) == {"all", "live", "replay"}
    assert options["replay"]["href"] == "?timeframe=1d&source=replay"
    assert options["live"].get("aria-current") == "page"
    assert options["all"].get("aria-current") is None


# Gherkin 4: the models page and its JSON mark simulated models
@pytest.mark.asyncio
async def test_models_page_marks_simulated_models(
    client: AsyncClient, mixed_sources: dict[str, Model]
) -> None:
    """
    Given a simulated model
    When /models/ renders
    Then its row shows the replay marker; a family that also has a live
    version is not marked, because its row mixes both
    """
    mixed = BeautifulSoup((await client.get("/models/")).text, "html.parser")
    mixed_rows = find_tag(mixed, "tbody").find_all("tr")
    assert len(mixed_rows) == 1
    assert mixed_rows[0].find(class_="replay-badge") is None

    soup = BeautifulSoup(
        (await client.get("/models/?source=replay")).text, "html.parser"
    )
    rows = find_tag(soup, "tbody").find_all("tr")
    assert len(rows) == 1
    assert "Replay" in find_tag(rows[0], class_="replay-badge").get_text()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("?source=live", [False]),
        ("?source=replay", [True]),
        ("?source=all", [False]),
        ("", [False]),
    ],
)
async def test_models_metrics_flags_and_filters_by_source(
    client: AsyncClient,
    mixed_sources: dict[str, Model],
    query: str,
    expected: list[bool],
) -> None:
    """The metrics JSON carries is_replay per family and honors ``source``.

    Under ``all`` the live and the replay version share one family row, which is
    not marked as replay because only some of its versions are.
    """
    body = (await client.get(f"/models/metrics{query}")).json()

    assert sorted(m["is_replay"] for m in body["models"]) == expected
    assert body["filters"]["source"] == (query.split("=")[1] if query else "all")


@pytest.mark.asyncio
async def test_models_page_source_filter(
    client: AsyncClient, mixed_sources: dict[str, Model]
) -> None:
    """source=live hides the simulated model from the comparison table."""
    soup = BeautifulSoup((await client.get("/models/?source=live")).text, "html.parser")

    rows = find_tag(soup, "tbody").find_all("tr")
    assert len(rows) == 1
    assert rows[0].find(class_="replay-badge") is None
