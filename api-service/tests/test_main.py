from typing import NoReturn

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session


async def test_health(client: AsyncClient, db_session: Session) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "reachable"}


async def test_health_reports_database_outage(
    client: AsyncClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import OperationalError

    def broken_execute(*args: object, **kwargs: object) -> NoReturn:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(db_session, "execute", broken_execute)

    response = await client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "unhealthy", "database": "unreachable"}


async def test_hello_default(client: AsyncClient) -> None:
    response = await client.get("/api/v1/hello")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello, world!"}


async def test_hello_with_name(client: AsyncClient) -> None:
    response = await client.get("/api/v1/hello?name=Claude")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello, Claude!"}
