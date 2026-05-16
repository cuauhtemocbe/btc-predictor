"""
Pytest fixtures para tests de BTC Predictor.

Este archivo define fixtures reutilizables para todos los tests.
Los fixtures con `yield` garantizan cleanup automático después de cada test.
"""

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Importar cuando estén disponibles (después de Iteración 1)
# from shared.db.database import get_engine
# from shared.db.models import Base, BtcPrice, Model, Prediction
# from shared.config import settings


@pytest.fixture(scope="session")
def db_engine():
    """
    Database engine para toda la sesión de tests.
    Usa la misma DB que desarrollo (postgres).
    """
    # TODO: Descomentar después de Iteración 1
    # engine = get_engine()
    # Base.metadata.create_all(engine)
    # yield engine
    # Base.metadata.drop_all(engine)
    pass


@pytest.fixture
def db_session(db_engine):
    """
    Session de base de datos con rollback automático.

    Cada test obtiene una session limpia.
    Al terminar el test, se hace rollback de todos los cambios.
    Esto garantiza que los tests no afecten la DB.
    """
    # TODO: Descomentar después de Iteración 1
    # SessionLocal = sessionmaker(bind=db_engine)
    # session = SessionLocal()
    # yield session
    # session.rollback()  # Deshacer todos los cambios del test
    # session.close()
    pass


@pytest.fixture
def sample_btc_price(db_session):
    """
    Crea un precio BTC de ejemplo para tests.
    Se elimina automáticamente al terminar el test.

    Example:
        def test_something(sample_btc_price):
            assert sample_btc_price.close == 50000.0
    """
    # TODO: Descomentar después de Iteración 2 (cuando exista BtcPrice model)
    # price = BtcPrice(
    #     timestamp=datetime(2024, 1, 1, 12, 0, 0),
    #     open=49000.0,
    #     high=51000.0,
    #     low=48500.0,
    #     close=50000.0,
    #     volume=1000.0,
    #     source="binance"
    # )
    # db_session.add(price)
    # db_session.commit()
    # db_session.refresh(price)
    # yield price
    # # Cleanup automático por rollback de db_session
    pass


@pytest.fixture
def sample_model(db_session):
    """
    Crea un modelo ML de ejemplo para tests.
    Se elimina automáticamente al terminar el test.

    Example:
        def test_prediction(sample_model):
            assert sample_model.name == "test_model"
    """
    # TODO: Descomentar después de Iteración 4 (cuando exista Model table)
    # import pickle
    # from sklearn.linear_model import LinearRegression
    #
    # model = LinearRegression()
    # model_artifact = pickle.dumps(model)
    #
    # db_model = Model(
    #     name="test_model",
    #     version="1.0",
    #     params={"window_days": 30},
    #     artifact=model_artifact,
    #     trained_at=datetime.now(),
    #     train_from=datetime(2024, 1, 1),
    #     train_to=datetime(2024, 1, 31),
    #     is_active=True
    # )
    # db_session.add(db_model)
    # db_session.commit()
    # db_session.refresh(db_model)
    # yield db_model
    # # Cleanup automático por rollback de db_session
    pass


@pytest.fixture
def sample_prediction(db_session, sample_model):
    """
    Crea una predicción de ejemplo para tests.
    Depende de sample_model (fixture dependency).
    Se elimina automáticamente al terminar el test.

    Example:
        def test_evaluation(sample_prediction):
            assert sample_prediction.predicted_price == 51000.0
    """
    # TODO: Descomentar después de Iteración 5 (cuando exista Prediction table)
    # from datetime import date
    #
    # prediction = Prediction(
    #     model_id=sample_model.id,
    #     predicted_for=date(2024, 1, 2),
    #     predicted_at=datetime(2024, 1, 1, 12, 0, 0),
    #     price_at_prediction=50000.0,
    #     predicted_price=51000.0,
    #     actual_price=None,  # Aún no evaluada
    #     evaluated_at=None
    # )
    # db_session.add(prediction)
    # db_session.commit()
    # db_session.refresh(prediction)
    # yield prediction
    # # Cleanup automático por rollback de db_session
    pass


# Fixture para mockear Binance API (después de Iteración 2)
@pytest.fixture
def mock_binance_response():
    """
    Mock de respuesta de Binance API para tests.
    Evita llamar a la API real durante tests.

    Example:
        def test_fetch_price(mock_binance_response, respx_mock):
            respx_mock.get("https://api.binance.com/api/v3/klines").mock(
                return_value=mock_binance_response
            )
            # ... test code
    """
    return {
        "status_code": 200,
        "json": [[
            1704110400000,  # timestamp
            "49000.0",      # open
            "51000.0",      # high
            "48500.0",      # low
            "50000.0",      # close
            "1000.0",       # volume
            1704114000000,  # close time
            "50000000.0",   # quote asset volume
            100,            # number of trades
            "500.0",        # taker buy base
            "25000000.0",   # taker buy quote
            "0"             # ignore
        ]]
    }


# Fixture para cliente FastAPI de tests (después de Iteración 3)
@pytest.fixture
def test_client():
    """
    Cliente HTTP de prueba para testear endpoints de FastAPI.

    Example:
        def test_health_endpoint(test_client):
            response = test_client.get("/health")
            assert response.status_code == 200
    """
    # TODO: Descomentar después de Iteración 3
    # from fastapi.testclient import TestClient
    # from btc_api.main import app
    #
    # client = TestClient(app)
    # yield client
    pass
