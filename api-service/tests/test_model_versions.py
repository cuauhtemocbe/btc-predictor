"""
One model family trained over several days: the API and the dashboard keep working.

With ``linear`` as the only model (#184), the models table gains one row per training
(``linear_v1``, ``linear_v2``, ...), only the latest active. The pages and endpoints
that list models or predictions must show every version without breaking.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from shared.db.models import Model, Prediction

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


@pytest.mark.asyncio
async def test_models_metrics_lists_every_version_and_only_the_last_is_active(
    client: AsyncClient, three_linear_versions: list[Model]
) -> None:
    response = await client.get("/models/metrics")

    assert response.status_code == 200
    rows = {row["name"]: row for row in response.json()["models"]}
    assert set(rows) == set(VERSIONS)
    assert [name for name, row in rows.items() if row["is_active"]] == ["linear_v3"]
    assert all(row["predictions_count"] == 1 for row in rows.values())


@pytest.mark.asyncio
async def test_models_page_renders_every_version(
    client: AsyncClient, three_linear_versions: list[Model]
) -> None:
    response = await client.get("/models/")

    assert response.status_code == 200
    for name in VERSIONS:
        assert name in response.text


@pytest.mark.asyncio
async def test_prediction_history_returns_the_rows_of_every_version(
    client: AsyncClient, three_linear_versions: list[Model]
) -> None:
    response = await client.get("/api/predictions/history")

    assert response.status_code == 200
    assert len(response.json()) == len(VERSIONS)
