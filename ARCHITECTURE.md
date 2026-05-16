# BTC Predictor — Arquitectura del Sistema

## Descripción General

Webapp de Data Science para predecir el precio del Bitcoin al día siguiente usando modelos ML. Registra predicciones, calcula errores históricos y simula PnL (ganancia/pérdida) basado en la dirección predicha.

---

## Stack Tecnológico

| Capa | Tecnología |
|---|---|
| Lenguaje | Python 3.13 |
| Gestión de dependencias | Poetry |
| API / Dashboard | FastAPI + Jinja2 |
| ORM | SQLAlchemy 2.0 |
| Base de datos | PostgreSQL |
| Migraciones | Alembic |
| ML | scikit-learn, pandas, numpy |
| HTTP client | httpx |
| Datos BTC | Binance API (gratis, sin API key) |
| Deploy | Railway |

---

## Arquitectura de Servicios

El proyecto despliega **4 servicios** en Railway que comparten una misma base de datos PostgreSQL:

```
Railway Project: btc-predictor
│
├── postgres          ← Plugin nativo de Railway
├── api               ← Siempre activo. Web pública con dashboard
├── fetch-price       ← Cron cada hora:  "0 * * * *"
└── daily             ← Cron cada día:   "0 7 * * *"
```

### Responsabilidades de cada servicio

#### `api` — Servicio Web (siempre activo)
- Sirve el dashboard HTML (Jinja2 + CSS)
- Expone endpoints REST para consultar precios, predicciones e historial de errores
- Muestra PnL acumulado simulado
- Puerto: 8000 (configurable vía `PORT` env var)

#### `fetch-price` — Cron Horario
- **Frecuencia:** cada hora (`0 * * * *`)
- Consulta Binance Public API (OHLCV 1h)
- Guarda el precio en tabla `btc_prices`
- **Idempotente:** no duplica si ya existe el timestamp (UNIQUE constraint)
- Sin necesidad de API key

#### `daily` — Cron Diario
- **Frecuencia:** 7:00am cada día (`0 7 * * *`)
- **Orquestación de 3 pasos:**
  1. **Evaluator:** evalúa la predicción de ayer (busca `predictions` sin `actual_price`, toma el precio de las 7am de hoy, calcula error y PnL)
  2. **Trainer:** entrena el modelo con los datos hasta hoy, serializa con pickle, guarda en tabla `models`
  3. **Predictor:** predice el precio de mañana y guarda en `predictions`

---

## Estructura del Repositorio

```
btc-predictor/
├── pyproject.toml              # Raíz Poetry (dev tools: black, ruff, pytest)
├── poetry.lock
├── docker-compose.yml          # Desarrollo local (postgres + servicios)
├── .env.example                # Variables de entorno requeridas
├── README.md
├── ARCHITECTURE.md             # Este archivo
│
├── shared/                     # Paquete interno: shared
│   ├── pyproject.toml
│   ├── shared/
│   │   ├── __init__.py
│   │   ├── config.py           # Settings con pydantic-settings (DATABASE_URL, etc.)
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── database.py     # Engine SQLAlchemy + SessionLocal
│   │   │   ├── models.py       # Definición de tablas ORM
│   │   │   └── crud.py         # Operaciones reutilizables (insert, query)
│   │   └── utils.py            # Helpers: cálculo de error, PnL
│   ├── tests/                  # Tests del shared package
│   │   ├── __init__.py
│   │   ├── test_config.py      # Tests de configuración
│   │   ├── test_models.py      # Tests de modelos SQLAlchemy
│   │   ├── test_crud.py        # Tests de operaciones DB
│   │   └── test_utils.py       # Tests de helpers (PnL, errores)
│   └── alembic/                # Migraciones de base de datos
│       ├── alembic.ini
│       ├── env.py
│       └── versions/
│
├── api-service/                # Service 1 (Web API)
│   ├── pyproject.toml
│   ├── Dockerfile
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py             # App FastAPI, monta routers
│   │   ├── routers/
│   │   │   ├── prices.py       # GET /api/prices
│   │   │   └── predictions.py  # GET /api/predictions/*
│   │   └── templates/
│   │       └── dashboard.html  # Jinja2: tabla de predicciones + PnL acumulado
│   └── tests/                  # Tests del API
│       ├── __init__.py
│       ├── conftest.py         # Fixtures de pytest (test DB, test client)
│       ├── test_main.py        # Tests de endpoints principales
│       ├── test_prices.py      # Tests de /api/prices
│       └── test_predictions.py # Tests de /api/predictions/*
│
└── workers/
    ├── fetch_price/            # Service 2 (Cron horario)
    │   ├── pyproject.toml
    │   ├── Dockerfile
    │   ├── fetch_price/
    │   │   ├── __init__.py
    │   │   ├── main.py         # Entry point del cron
    │   │   └── binance.py      # Cliente Binance API
    │   └── tests/              # Tests del fetch_price job
    │       ├── __init__.py
    │       ├── test_binance.py # Tests del cliente Binance (mocked)
    │       └── test_main.py    # Tests de integración del job
    │
    └── daily/                  # Service 3 (Cron diario)
        ├── pyproject.toml
        ├── Dockerfile
        ├── daily/
        │   ├── __init__.py
        │   ├── main.py         # Orquesta: evaluate → train → predict
        │   ├── evaluator.py    # Calcula error_abs, error_pct, direction, PnL
        │   ├── trainer.py      # Entrena y serializa modelo
        │   ├── predictor.py    # Predice precio de mañana
        │   └── models/
        │       ├── base.py     # Clase abstracta BaseModel
        │       └── linear.py   # LinearRegressionModel (ventana deslizante)
        └── tests/              # Tests del daily job
            ├── __init__.py
            ├── test_evaluator.py   # Tests de evaluación de predicciones
            ├── test_trainer.py     # Tests de entrenamiento de modelos
            ├── test_predictor.py   # Tests de predicción
            └── test_models.py      # Tests de BaseModel y LinearRegression
```

---

## Testing Strategy

### Regla Fundamental

**Cada criterio de aceptación (Gherkin) DEBE tener al menos 1 test automatizado.**

- No se acepta: "lo probé manualmente", "se ve bien en el browser", "confío en que funciona"
- Si el criterio no tiene un test que falla cuando se rompe, el criterio no está cubierto
- Esta regla es **no negociable**

### Tipos de Tests

#### 1. Unit Tests
**Qué testear:**
- Funciones puras (`calculate_pnl`, `calculate_error_pct`)
- Modelos ML (`BaseModel.train()`, `LinearRegressionModel.predict()`)
- Validaciones de Pydantic (config, API schemas)
- Lógica de negocio sin dependencias externas

**Herramientas:**
- `pytest` (test runner)
- `pytest-mock` (para mocking)

**Ejemplo:**
```python
# shared/tests/test_utils.py
def test_calculate_pnl_predicted_up_went_up():
    pnl = calculate_pnl(
        predicted_price=68000,
        price_at_prediction=67000,
        actual_price=68500
    )
    assert pnl == 1500  # profit
```

---

#### 2. Integration Tests (con base de datos)
**Qué testear:**
- Operaciones CRUD (insert, query, update)
- Migraciones de Alembic (up/down)
- Constraints de DB (UNIQUE, FK, NOT NULL)
- Transacciones y rollbacks

**Herramientas:**
- `pytest` + `pytest-asyncio`
- Test database (PostgreSQL en Docker o SQLite in-memory para CI)
- Fixtures en `conftest.py` para setup/teardown

**Ejemplo:**
```python
# shared/tests/test_crud.py
@pytest.mark.asyncio
async def test_insert_btc_price_duplicate_timestamp_fails(db_session):
    # Arrange
    timestamp = datetime(2026, 5, 16, 14, 0, 0, tzinfo=timezone.utc)
    
    # Act: insert first record
    insert_btc_price(db_session, timestamp=timestamp, close=67000)
    
    # Act: attempt duplicate insert
    with pytest.raises(IntegrityError):
        insert_btc_price(db_session, timestamp=timestamp, close=67100)
```

---

#### 3. API Tests (FastAPI endpoints)
**Qué testear:**
- Endpoints REST (status codes, response schema)
- Query params validation
- Error handling (404, 422, 500)
- Dashboard rendering (HTML)

**Herramientas:**
- `httpx.AsyncClient` (async HTTP client)
- `FastAPI.TestClient` (sync alternative)
- Fixtures para test DB y app instance

**Ejemplo:**
```python
# api-service/tests/test_prices.py
@pytest.mark.asyncio
async def test_get_prices_returns_json_array(client: httpx.AsyncClient):
    # Arrange: insert test data
    insert_test_prices(count=10)
    
    # Act
    response = await client.get("/api/prices?limit=5")
    
    # Assert
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 5
    assert "timestamp" in data[0]
    assert "close" in data[0]
```

---

#### 4. Job Tests (cron jobs)
**Qué testear:**
- Idempotencia (correr el job 2 veces no duplica datos)
- Error handling (Binance timeout, DB connection failure)
- Mocking de APIs externas (Binance)

**Herramientas:**
- `pytest-mock` o `unittest.mock`
- `respx` (para mockear httpx requests)

**Ejemplo:**
```python
# workers/fetch_price/tests/test_main.py
@pytest.mark.asyncio
@respx.mock
async def test_fetch_price_idempotent(db_session):
    # Arrange: mock Binance API
    respx.get("https://api.binance.com/api/v3/klines").mock(
        return_value=httpx.Response(200, json=[...])
    )
    
    # Act: run job twice
    await fetch_price_main()
    await fetch_price_main()
    
    # Assert: only 1 record inserted (idempotency)
    count = db_session.query(BtcPrice).count()
    assert count == 1
```

---

### Test Database Setup

**Opción 1: PostgreSQL en Docker (preferida para local)**
```yaml
# docker-compose.test.yml
services:
  postgres-test:
    image: postgres:16
    environment:
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
      POSTGRES_DB: btcpredictor_test
    ports:
      - "5433:5432"
```

**Opción 2: SQLite in-memory (para CI rápido)**
```python
# conftest.py
@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
```

---

### Cobertura de Tests

**Target:** >80% code coverage

```bash
# Instalar coverage
poetry add --group dev pytest-cov

# Correr tests con cobertura
pytest --cov=shared --cov=api --cov=fetch_price --cov=daily

# Reporte HTML
pytest --cov=shared --cov-report=html
open htmlcov/index.html
```

---

### Fixtures Comunes

**`shared/tests/conftest.py`**
```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from shared.db.models import Base

@pytest.fixture
def db_engine():
    engine = create_engine("postgresql://test:test@localhost:5433/btcpredictor_test")
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)

@pytest.fixture
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()
```

**`api-service/tests/conftest.py`**
```python
import pytest
from httpx import AsyncClient
from api.main import app

@pytest.fixture
async def client():
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client
```

---

### Comandos de Testing

```bash
# Correr todos los tests
pytest

# Correr tests de un paquete específico
pytest shared/tests/
pytest api-service/tests/
pytest workers/fetch_price/tests/
pytest workers/daily/tests/

# Correr un archivo específico
pytest shared/tests/test_utils.py

# Correr un test específico
pytest shared/tests/test_utils.py::test_calculate_pnl_predicted_up_went_up

# Verbose output
pytest -v

# Ver print statements
pytest -s

# Correr en paralelo (más rápido)
pytest -n auto  # requiere pytest-xdist
```

---

### CI/CD con GitHub Actions

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
          POSTGRES_DB: btcpredictor_test
        ports:
          - 5432:5432
    
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.13'
      
      - name: Install Poetry
        run: pip install poetry
      
      - name: Install dependencies
        run: poetry install
      
      - name: Run tests
        run: poetry run pytest --cov --cov-report=xml
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/btcpredictor_test
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

---

## Base de Datos

### Tecnología
**PostgreSQL** con **SQLAlchemy 2.0** como ORM.

```
Python → SQLAlchemy (ORM) → PostgreSQL
```

### Tablas

#### `btc_prices` — Precios crudos por hora

```sql
CREATE TABLE btc_prices (
    id          SERIAL PRIMARY KEY,
    timestamp   TIMESTAMPTZ NOT NULL UNIQUE,  -- UNIQUE evita duplicados
    open        FLOAT,
    high        FLOAT,
    low         FLOAT,
    close       FLOAT,        -- variable que usa el modelo
    volume      FLOAT,
    source      VARCHAR(50)   -- 'binance'
);
```

**Índices:**
- `UNIQUE` en `timestamp` para idempotencia del job `fetch-price`
- `INDEX` en `timestamp DESC` para queries rápidas de últimos precios

---

#### `models` — Registro de versiones de modelos ML

```sql
CREATE TABLE models (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100),  -- 'linear_v1', 'lstm_v1'
    version     VARCHAR(50),
    params      JSONB,         -- {"window_days": 30, "features": ["close"]}
    artifact    BYTEA,         -- modelo serializado (pickle)
    trained_at  TIMESTAMPTZ,
    train_from  DATE,
    train_to    DATE,
    is_active   BOOLEAN DEFAULT FALSE
);
```

**Lógica de negocio:**
- Solo 1 modelo activo a la vez por `name` (controlado por aplicación)
- `artifact` contiene el modelo serializado con `pickle`
- `params` en JSONB permite queryar por hiperparámetros

---

#### `predictions` — Predicciones diarias e historial de errores

```sql
CREATE TABLE predictions (
    id                      SERIAL PRIMARY KEY,
    model_id                INTEGER REFERENCES models(id),
    predicted_for           DATE NOT NULL,      -- día al que aplica la predicción
    predicted_at            TIMESTAMPTZ,        -- cuándo se generó (~7am de hoy)
    price_at_prediction     FLOAT,              -- close de hoy (input del modelo)
    predicted_price         FLOAT,              -- precio predicho para mañana

    -- Se llena por el job daily al día siguiente:
    actual_price            FLOAT,
    evaluated_at            TIMESTAMPTZ,
    error_abs               FLOAT,             -- |actual - predicted|
    error_pct               FLOAT,             -- error_abs / actual * 100
    direction_correct       BOOLEAN,           -- ¿acertó la tendencia?
    pnl_simulated           FLOAT              -- USD ganados/perdidos (posición de 1 BTC)
);
```

**Flujo de datos:**
1. **Día 1 (7am):** Job `predictor` inserta registro con `predicted_for=Día2`, `actual_price=NULL`
2. **Día 2 (7am):** Job `evaluator` actualiza el registro con `actual_price`, `error_abs`, `error_pct`, `direction_correct`, `pnl_simulated`

---

## Flujo de Datos Completo

### 1. Cada hora — `fetch-price`

```
┌─────────────────┐
│ Binance API     │ GET /api/v3/klines?symbol=BTCUSDT&interval=1h&limit=1
│ (público)       │
└────────┬────────┘
         │
         v
┌─────────────────┐
│ fetch-price job │ httpx async request
└────────┬────────┘
         │
         v
┌─────────────────┐
│ btc_prices      │ INSERT (skip if timestamp exists)
│ (PostgreSQL)    │
└─────────────────┘
```

**Idempotencia:** UNIQUE constraint en `timestamp` asegura que múltiples ejecuciones no dupliquen datos.

---

### 2. Cada día (7:00am) — `daily`

```
┌─────────────────────────────────────────────────────────────┐
│                     daily.main (orchestrator)               │
└───────────┬──────────────────┬──────────────────┬───────────┘
            │                  │                  │
            v                  v                  v
    ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
    │ 1. evaluator  │  │ 2. trainer    │  │ 3. predictor  │
    └───────┬───────┘  └───────┬───────┘  └───────┬───────┘
            │                  │                  │
            v                  v                  v
┌─────────────────────────────────────────────────────────────┐
│                         PostgreSQL                          │
│  predictions (UPDATE)    models (INSERT)   predictions (INSERT)
└─────────────────────────────────────────────────────────────┘
```

#### Paso 1 — `evaluator.py`
```python
# Buscar predicción sin evaluar
prediction = db.query(Prediction).filter(
    Prediction.predicted_for == today,
    Prediction.actual_price.is_(None)
).first()

# Obtener precio real de hoy (7am)
actual_price = db.query(BtcPrice).filter(
    BtcPrice.timestamp == today_7am
).first().close

# Calcular métricas
error_abs = abs(actual_price - prediction.predicted_price)
error_pct = (error_abs / actual_price) * 100
direction_correct = (prediction.predicted_price > prediction.price_at_prediction) == \
                    (actual_price > prediction.price_at_prediction)
pnl_simulated = calculate_pnl(prediction.predicted_price, 
                               prediction.price_at_prediction, 
                               actual_price)

# Actualizar
prediction.actual_price = actual_price
prediction.error_abs = error_abs
prediction.error_pct = error_pct
prediction.direction_correct = direction_correct
prediction.pnl_simulated = pnl_simulated
prediction.evaluated_at = datetime.utcnow()
db.commit()
```

#### Paso 2 — `trainer.py`
```python
# Obtener datos históricos
prices = db.query(BtcPrice).order_by(BtcPrice.timestamp.desc()).limit(window_days).all()

# Crear features (sliding window)
X, y = create_features(prices, window_days=30)

# Entrenar modelo
model = LinearRegressionModel(window_days=30)
model.train(X, y)

# Serializar y guardar
artifact = model.serialize()  # pickle.dumps()
db.add(Model(
    name="linear_v1",
    artifact=artifact,
    params={"window_days": 30},
    is_active=True,
    trained_at=datetime.utcnow()
))
# Desactivar modelos anteriores
db.query(Model).filter(Model.name == "linear_v1", Model.is_active == True).update({"is_active": False})
db.commit()
```

#### Paso 3 — `predictor.py`
```python
# Cargar modelo activo
model_record = db.query(Model).filter(Model.name == "linear_v1", Model.is_active == True).first()
model = LinearRegressionModel.deserialize(model_record.artifact)

# Obtener últimos N precios
last_prices = db.query(BtcPrice).order_by(BtcPrice.timestamp.desc()).limit(30).all()
X_new = prepare_features(last_prices)

# Predecir
predicted_price = model.predict(X_new)
price_at_prediction = last_prices[0].close  # precio actual (hoy)

# Guardar predicción
db.add(Prediction(
    model_id=model_record.id,
    predicted_for=tomorrow,
    predicted_at=datetime.utcnow(),
    price_at_prediction=price_at_prediction,
    predicted_price=predicted_price
))
db.commit()
```

---

## Modelo ML

### Modelo Inicial: Linear Regression con Ventana Deslizante

**Features:** Últimos 30 cierres diarios (sliding window)  
**Target:** Precio del día siguiente  
**Librería:** `scikit-learn.LinearRegression`

```python
# Ejemplo de features
X = [
    [67000, 66800, 66500, ..., 65000],  # día 1: últimos 30 closes
    [67200, 67000, 66800, ..., 66500],  # día 2: últimos 30 closes
    ...
]
y = [67500, 67800, ...]  # targets: precio del día siguiente
```

### Clase Abstracta para Extensibilidad

```python
from abc import ABC, abstractmethod
import numpy as np

class BaseModel(ABC):
    @abstractmethod
    def train(self, X: np.ndarray, y: np.ndarray) -> None:
        """Entrenar el modelo con datos históricos"""
        pass

    @abstractmethod
    def predict(self, X: np.ndarray) -> float:
        """Predecir el precio del próximo día"""
        pass

    @abstractmethod
    def serialize(self) -> bytes:
        """Serializar modelo a bytes (pickle)"""
        pass

    @classmethod
    @abstractmethod
    def deserialize(cls, data: bytes) -> "BaseModel":
        """Deserializar modelo desde bytes"""
        pass
```

**Beneficio:** Facilita agregar nuevos modelos (ARIMA, LSTM, XGBoost) sin cambiar la infraestructura.

---

## Lógica PnL Simulado

**Estrategia:** Si el modelo predice que el precio SUBE → simulamos que "compramos" 1 BTC. Si predice que BAJA → nos quedamos en cash (PnL = 0).

```python
def calculate_pnl(predicted_price: float, 
                  price_at_prediction: float, 
                  actual_price: float) -> float:
    """
    Calcula PnL simulado basado en dirección predicha.
    
    Args:
        predicted_price: Precio predicho para mañana
        price_at_prediction: Precio actual (hoy)
        actual_price: Precio real de mañana (observado)
    
    Returns:
        PnL en USD (ganancia o pérdida si entramos long, 0 si no entramos)
    """
    if predicted_price > price_at_prediction:
        # Predijimos subida → entramos long con 1 BTC
        return actual_price - price_at_prediction
    else:
        # Predijimos bajada → nos quedamos en cash
        return 0.0
```

**Ejemplo:**
- Hoy: BTC = $67,000
- Predicción: $68,000 (↑) → **entramos long**
- Mañana real: $68,500
- **PnL = $68,500 - $67,000 = +$1,500**

---

## API REST

### Endpoints Disponibles

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/` | Dashboard HTML (Jinja2) con tabla de predicciones |
| `GET` | `/health` | Health check del servicio |
| `GET` | `/api/prices?limit=168` | Últimos N precios horarios |
| `GET` | `/api/predictions` | Todas las predicciones (evaluadas y no evaluadas) |
| `GET` | `/api/predictions/history` | Historial de predicciones evaluadas con errores |
| `GET` | `/api/predictions/pnl` | PnL acumulado total |
| `GET` | `/api/models` | Listado de modelos entrenados |
| `GET` | `/docs` | Swagger UI (auto-generado por FastAPI) |

### Ejemplo de respuesta: `/api/predictions/history`

```json
[
  {
    "predicted_for": "2026-05-16",
    "predicted_at": "2026-05-15T07:00:00Z",
    "predicted_price": 67500.0,
    "actual_price": 67800.0,
    "error_abs": 300.0,
    "error_pct": 0.44,
    "direction_correct": true,
    "pnl_simulated": 800.0,
    "model_name": "linear_v1"
  },
  ...
]
```

---

## Variables de Entorno

```bash
# .env.example

# Base de datos
DATABASE_URL=postgresql://user:password@localhost:5432/btcpredictor

# Binance API (público, sin API key)
BINANCE_BASE_URL=https://api.binance.com

# Configuración del modelo
MODEL_WINDOW_DAYS=30        # días de historial como features
MODEL_NAME=linear_v1

# Timezone para jobs cron
TZ=America/Mexico_City

# Puerto del servidor (inyectado por Railway)
PORT=8000

# Entorno
ENVIRONMENT=development
```

---

## Dependencias por Servicio

### `shared/pyproject.toml`
```toml
[tool.poetry.dependencies]
python = "^3.13"
sqlalchemy = "^2.0"
psycopg2-binary = "^2.9"
alembic = "^1.13"
pydantic-settings = "^2.0"
```

### `api/pyproject.toml`
```toml
[tool.poetry.dependencies]
python = "^3.13"
shared = {path = "../shared", develop = true}
fastapi = "^0.115"
uvicorn = "^0.34"
jinja2 = "^3.1"
```

### `workers/fetch_price/pyproject.toml`
```toml
[tool.poetry.dependencies]
python = "^3.13"
shared = {path = "../../shared", develop = true}
httpx = "^0.28"
```

### `workers/daily/pyproject.toml`
```toml
[tool.poetry.dependencies]
python = "^3.13"
shared = {path = "../../shared", develop = true}
scikit-learn = "^1.4"
pandas = "^2.0"
numpy = "^1.26"
httpx = "^0.28"
```

---

## Docker — Desarrollo Local

### `docker-compose.yml`

```yaml
version: "3.9"

services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: btc
      POSTGRES_PASSWORD: btc
      POSTGRES_DB: btcpredictor
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  api:
    build:
      context: .
      dockerfile: api/Dockerfile
    ports:
      - "8000:8000"
    env_file: .env
    depends_on: [postgres]
    volumes:
      - ./api:/app/api
      - ./shared:/app/shared

  fetch-price:
    build:
      context: .
      dockerfile: workers/fetch_price/Dockerfile
    env_file: .env
    depends_on: [postgres]
    profiles: ["manual"]  # no se inicia con docker compose up

  daily:
    build:
      context: .
      dockerfile: workers/daily/Dockerfile
    env_file: .env
    depends_on: [postgres]
    profiles: ["manual"]  # no se inicia con docker compose up

volumes:
  pgdata:
```

### Dockerfile Patrón (todos los servicios)

```dockerfile
# Ejemplo: workers/fetch_price/Dockerfile
FROM python:3.13-slim

WORKDIR /app

# Instalar Poetry
RUN pip install poetry && \
    poetry config virtualenvs.create false

# Copiar shared primero (dependencia común)
COPY shared/ ./shared/

# Copiar el servicio específico
COPY workers/fetch_price/ ./job/

# Instalar dependencias
WORKDIR /app/job
RUN poetry install --no-root

# Entry point
CMD ["python", "-m", "fetch_price.main"]
```

---

## Configuración en Railway

### Servicios y Cron Schedules

| Servicio | Tipo | Config |
|----------|------|--------|
| `postgres` | Plugin | Nativo Railway (inyecta `DATABASE_URL` automáticamente) |
| `api` | Web service | `uvicorn api.main:app --host 0.0.0.0 --port $PORT` |
| `fetch-price` | Cron | `0 * * * *` (cada hora) |
| `daily` | Cron | `0 7 * * *` (7am UTC, ajustar según timezone) |

### Variables de Entorno en Railway

Railway inyecta automáticamente:
- `DATABASE_URL` — conexión al plugin de Postgres
- `PORT` — puerto asignado (solo para `api`)

Agregar manualmente:
- `BINANCE_BASE_URL=https://api.binance.com`
- `MODEL_WINDOW_DAYS=30`
- `MODEL_NAME=linear_v1`
- `TZ=America/Mexico_City`

---

## Orden de Implementación (Desarrollo Iterativo)

1. ✅ **Iteración 0:** Hello World FastAPI (ya existe)
2. **Iteración 1:** `shared/` — config, database, models, Alembic
3. **Iteración 2:** `fetch_price` — Binance client + job manual
4. **Iteración 3:** `api` — endpoints `/api/prices`
5. **Iteración 4:** `daily/models` — BaseModel + LinearRegressionModel + tabla `models`
6. **Iteración 5:** `daily` — evaluator + predictor + tabla `predictions`
7. **Iteración 6:** `api` — dashboard HTML + `/api/predictions/history`
8. **Iteración 7:** PnL logic + `/api/predictions/pnl`
9. **Iteración 8:** Deploy en Railway con crons

**Ver:** [User Stories en GitHub](https://github.com/cuauhtemocbe/btc-predictor/issues) para el backlog completo.

---

## Consideraciones Futuras

### Modelos ML Avanzados
- ARIMA / SARIMA (modelos de series temporales)
- XGBoost / LightGBM (gradient boosting)
- LSTM / GRU (deep learning para series temporales)
- Ensemble models (combinar múltiples predicciones)

### Features Adicionales
- Volumen de trading
- Indicadores técnicos (RSI, MACD, Bollinger Bands)
- Medias móviles (7d, 30d, 90d)
- Sentiment de redes sociales (Twitter, Reddit)
- Fear & Greed Index

### Mejoras Operacionales
- **Backtesting:** evaluar modelos sobre datos históricos antes de activarlos
- **Alertas:** notificación vía email/Telegram cuando error supere cierto umbral
- **Monitoreo:** integración con Grafana/Prometheus para métricas en tiempo real
- **CI/CD:** tests automatizados en GitHub Actions antes de cada deploy
- **Validación de modelos:** A/B testing entre múltiples modelos activos

### Frontend Avanzado
- Migrar dashboard a **React/Next.js** para interactividad avanzada
- Gráficos con **Chart.js** o **Recharts**
- Filtros por rango de fechas, modelo, error mínimo/máximo
- Comparación de modelos side-by-side

---

## Referencias

- **Binance API Docs:** https://binance-docs.github.io/apidocs/spot/en/
- **SQLAlchemy 2.0:** https://docs.sqlalchemy.org/en/20/
- **FastAPI:** https://fastapi.tiangolo.com/
- **Railway Deploy:** https://docs.railway.app/
- **Scikit-learn:** https://scikit-learn.org/stable/
