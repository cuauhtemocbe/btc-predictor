"""
One model family trained over several days: the API and the dashboard keep working.

With ``linear`` as the only model (#184), the models table gains one row per training
(``linear_v1``, ``linear_v2``, ...), only the latest active. The models page
and its JSON summarize every version of the family in one row (#178); the other
pages and endpoints that list predictions must keep working.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from bs4 import BeautifulSoup
from httpx import AsyncClient
from soup_helpers import find_tag
from sqlalchemy import event
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from shared.db.models import Model, Prediction
from shared.returns import max_drawdown_pct, sharpe_ratio

FIRST_DAY = date(2026, 9, 1)
VERSIONS = ("linear_v1", "linear_v2", "linear_v3")


@pytest.fixture
def three_linear_versions(db_session: Session) -> list[Model]:
    """Three linear models trained on consecutive days, one prediction each."""
    models: list[Model] = []
    for i, name in enumerate(VERSIONS):
        day = FIRST_DAY + timedelta(days=i)
        model = Model(
            name=name,
            version=f"v{i + 1}",
            params={"window_days": 21},
            artifact=b"fake_pickle",
            trained_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
            train_from=day - timedelta(days=150),
            train_to=day,
            is_active=name == VERSIONS[-1],
        )
        db_session.add(model)
        db_session.flush()
        db_session.add(
            Prediction(
                model_id=model.id,
                predicted_for=day,
                timeframe="1d",
                predicted_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
                price_at_prediction=Decimal("100"),
                predicted_price=Decimal("101"),
                actual_price=Decimal("102"),
                evaluated_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
                error_abs=Decimal("1"),
                error_pct=Decimal("1"),
                direction_correct=True,
                pnl_simulated=Decimal("2"),
            )
        )
        models.append(model)
    db_session.commit()
    return models


def _add_versions(
    db: Session,
    count: int,
    *,
    params: dict[str, Any] | None = None,
    first_index: int = 1,
    first_day: date = FIRST_DAY,
    activate_last: bool = True,
) -> list[Model]:
    """
    ``count`` linear versions with one evaluated prediction each, on consecutive days.

    Version i is correct unless ``i % 4 == 0``: it earns +2 on a price of 100 when
    right and -3 when wrong. The last version is active unless ``activate_last``
    is false.
    """
    models: list[Model] = []
    for offset in range(count):
        index = first_index + offset
        day = first_day + timedelta(days=offset)
        correct = index % 4 != 0
        model = Model(
            name=f"linear_v{index}",
            version=f"v{index}",
            params=params or {"window_days": 21},
            artifact=b"x",
            trained_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
            train_from=day - timedelta(days=150),
            train_to=day,
            is_active=activate_last and offset == count - 1,
        )
        db.add(model)
        db.flush()
        db.add(
            Prediction(
                model_id=model.id,
                predicted_for=day,
                timeframe="1d",
                predicted_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
                price_at_prediction=Decimal("100"),
                predicted_price=Decimal("102") if correct else Decimal("98"),
                actual_price=Decimal("102") if correct else Decimal("97"),
                evaluated_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
                error_abs=Decimal("0"),
                error_pct=Decimal("0"),
                direction_correct=correct,
                pnl_simulated=Decimal("2") if correct else Decimal("-3"),
            )
        )
        models.append(model)
    db.commit()
    return models


@contextmanager
def _count_queries(db: Session) -> Iterator[list[str]]:
    """Collect every SQL statement the engine executes inside the block."""
    bind = db.get_bind()
    engine = bind.engine if isinstance(bind, Connection) else bind
    assert isinstance(engine, Engine)
    statements: list[str] = []

    def record(*args: Any) -> None:
        statements.append(str(args[2]))

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


@pytest.fixture
def forty_linear_versions(db_session: Session) -> list[Model]:
    """Forty linear versions, one evaluated prediction each (30 right, 10 wrong)."""
    return _add_versions(db_session, 40)


@pytest.mark.asyncio
async def test_models_metrics_shows_one_family_row_over_every_version(
    client: AsyncClient, three_linear_versions: list[Model]
) -> None:
    response = await client.get("/models/metrics")

    assert response.status_code == 200
    (row,) = response.json()["models"]
    assert row["name"] == "linear"
    assert row["versions_count"] == len(VERSIONS)
    assert row["predictions_count"] == len(VERSIONS)
    assert row["is_active"] is True
    assert row["version"] == "v3"
    assert row["id"] == three_linear_versions[-1].id
    assert row["first_train_to"] == "2026-09-01"
    assert row["last_train_to"] == "2026-09-03"


@pytest.mark.asyncio
async def test_models_page_shows_one_linear_row_with_all_forty_predictions(
    client: AsyncClient, forty_linear_versions: list[Model]
) -> None:
    """
    Given 40 versions of linear_vN with 1 prediction each
    When /models/ renders
    Then it shows one linear row with 40 predictions and its accuracy, Sharpe and
    drawdown computed over all 40
    """
    soup = BeautifulSoup((await client.get("/models/")).text, "html.parser")

    rows = find_tag(soup, "tbody").find_all("tr")
    assert len(rows) == 1
    cells = [td.get_text(" ", strip=True) for td in rows[0].find_all("td")]
    returns = [0.02 if i % 4 != 0 else -0.03 for i in range(1, 41)]
    sharpe = sharpe_ratio(returns)
    drawdown = max_drawdown_pct(returns)
    assert sharpe is not None
    assert drawdown is not None
    assert cells[0].startswith("linear ")
    assert "40 versions" in cells[0]
    assert cells[1] == "40"
    assert cells[2] == "75.0%"
    assert cells[4] == "$30.00"
    assert cells[6] == f"{sharpe:.2f}"
    assert cells[7] == f"{drawdown:,.2f}%"


@pytest.mark.asyncio
async def test_models_metrics_computes_over_all_versions_in_date_order(
    client: AsyncClient, forty_linear_versions: list[Model]
) -> None:
    returns = [0.02 if i % 4 != 0 else -0.03 for i in range(1, 41)]

    (row,) = (await client.get("/models/metrics")).json()["models"]

    assert row["predictions_count"] == 40
    assert row["accuracy"] == 0.75
    assert row["win_rate"] == 0.75
    assert row["total_pnl"] == 30.0
    assert row["sharpe_ratio"] == round(sharpe_ratio(returns) or 0.0, 2)
    assert row["max_drawdown_pct"] == round(max_drawdown_pct(returns) or 0.0, 2)
    assert row["baseline"]["n_days"] == 40


@pytest.mark.asyncio
async def test_models_metrics_daily_pnl_is_one_series_per_family(
    client: AsyncClient, forty_linear_versions: list[Model]
) -> None:
    body = (await client.get("/models/metrics")).json()

    assert list(body["daily_pnl"]) == ["linear"]
    series = body["daily_pnl"]["linear"]
    assert len(series) == 40
    assert series[0] == {"date": "2026-09-01", "cumulative_pnl": 2.0}
    assert series[-1]["cumulative_pnl"] == 30.0


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/models/", "/models/metrics"])
async def test_models_query_count_does_not_depend_on_the_number_of_models(
    client: AsyncClient, db_session: Session, path: str
) -> None:
    """
    Given N models
    When the models page (or its JSON) is requested
    Then the number of SQL queries is the same for N = 5 and N = 50
    """
    _add_versions(db_session, 5)
    with _count_queries(db_session) as few:
        assert (await client.get(path)).status_code == 200

    _add_versions(
        db_session,
        45,
        first_index=6,
        first_day=FIRST_DAY + timedelta(days=5),
        activate_last=False,
    )
    with _count_queries(db_session) as many:
        assert (await client.get(path)).status_code == 200

    assert len(few) == len(many)
    assert len(many) <= 8


@pytest.mark.asyncio
async def test_models_page_renders_the_family_with_its_versions(
    client: AsyncClient, three_linear_versions: list[Model]
) -> None:
    response = await client.get("/models/")

    assert response.status_code == 200
    assert "3 versions" in response.text
    assert "2026-09-01 to 2026-09-03" in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "versions", "predictions"),
    [
        ("", 3, 3),
        ("?source=all", 3, 3),
        ("?source=live", 1, 1),
        ("?source=replay", 2, 2),
    ],
)
async def test_family_row_counts_replay_versions_according_to_source(
    client: AsyncClient,
    db_session: Session,
    query: str,
    versions: int,
    predictions: int,
) -> None:
    """
    Given one live version and two replay versions of linear
    When /models/metrics is requested with each source
    Then the family row covers only the versions and predictions of that source
    """
    _add_versions(db_session, 1)
    _add_versions(
        db_session,
        2,
        params={"simulated": True},
        first_index=2,
        first_day=FIRST_DAY + timedelta(days=1),
        activate_last=False,
    )

    (row,) = (await client.get(f"/models/metrics{query}")).json()["models"]

    assert row["versions_count"] == versions
    assert row["predictions_count"] == predictions
    assert row["is_replay"] is (query == "?source=replay")


@pytest.mark.asyncio
async def test_prediction_history_returns_the_rows_of_every_version(
    client: AsyncClient, three_linear_versions: list[Model]
) -> None:
    response = await client.get("/api/predictions/history")

    assert response.status_code == 200
    assert len(response.json()) == len(VERSIONS)
