async def test_health(client, db_session):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "reachable"}


async def test_health_reports_database_outage(client, db_session, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def broken_execute(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(db_session, "execute", broken_execute)

    response = await client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "unhealthy", "database": "unreachable"}


async def test_hello_default(client):
    response = await client.get("/api/v1/hello")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello, world!"}


async def test_hello_with_name(client):
    response = await client.get("/api/v1/hello?name=Claude")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello, Claude!"}
