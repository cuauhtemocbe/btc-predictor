# BTC Predictor

Webapp de Data Science para predecir el precio del Bitcoin al día siguiente usando modelos de Machine Learning. Registra predicciones, calcula errores históricos y simula PnL (ganancia/pérdida) basado en la dirección predicha.

**Es un proyecto de aprendizaje, no asesoría financiera.** Cada resultado se compara contra baselines triviales y, como muestra la sección [Resultados](#-resultados), el modelo actual **no supera de forma significativa** a esos baselines.

---

## 🚀 Estado del Proyecto

✅ **Proyecto Completo** — Todas las User Stories implementadas y desplegadas a Railway  
✅ **16 User Stories (US-001 a US-016)** — 8 iteraciones completadas  
✅ **Deployed:** [Railway Production](https://btc-predictor.railway.app)

[Ver User Stories en GitHub →](https://github.com/cuauhtemocbe/btc-predictor/issues)  
[Ver Proyecto Board →](https://github.com/users/cuauhtemocbe/projects/1/views/1)

---

## 📊 Stack Tecnológico

- **Lenguaje:** Python 3.13
- **Framework Web:** FastAPI + Jinja2
- **Base de datos:** PostgreSQL + SQLAlchemy 2.0 + Alembic
- **Machine Learning:** scikit-learn, pandas, numpy
- **Fuente de datos:** Binance vía [data.binance.vision](https://data.binance.vision) (archivos de historial y diarios) con REST `data-api.binance.vision` como respaldo. Gratis y sin API key.
- **Activos:** `BTCUSDT` y `PAXGUSDT` (proxy del oro)
- **Deploy:** Railway (5 servicios: postgres, api, fetch-price, daily, monthly-backtest)
- **Gestión de dependencias:** Poetry (monorepo con paquetes internos)

---

## 🏗️ Arquitectura

El proyecto se despliega como **6 servicios en Railway**:

```
┌──────────────────┐
│     postgres     │  Plugin nativo de Railway
└──────────────────┘
         ↓
┌──────────────────┐
│       api        │  Servicio web siempre activo (FastAPI + Dashboard)
└──────────────────┘
         ↓
┌──────────────────┐
│   fetch-price    │  Cron diario 00:05 UTC: guarda la vela diaria cerrada de cada símbolo
└──────────────────┘
         ↓
┌──────────────────┐
│      daily       │  Cron diario 00:10 UTC: evalúa → entrena → predice (horizonte 1 día)
└──────────────────┘
┌──────────────────┐
│ monthly-backtest │  Cron día 1 de cada mes, 00:00 UTC: backtest walk-forward con la configuración de producción
└──────────────────┘
```

**Ver documentación completa:** [IMPLEMENTATION_HISTORY.md](docs/archive/specs/IMPLEMENTATION_HISTORY.md)

---

## 📂 Estructura del Proyecto

```
btc-predictor/
├── shared/              # Paquete compartido: shared
│   ├── shared/
│   │   ├── config.py    # Configuración (DATABASE_URL, TRAINING_WINDOW_DAYS)
│   │   ├── assets.py    # Activos soportados (BTCUSDT, PAXGUSDT)
│   │   ├── binance_vision.py  # Historial y velas diarias de Binance
│   │   ├── features.py  # Features basadas en retornos (producción y backtest)
│   │   ├── baselines.py # always-up, persistence, buy-and-hold y p-value
│   │   ├── db/          # SQLAlchemy models, engine, CRUD
│   │   └── utils.py     # Helpers (PnL, cálculo de errores)
│   └── alembic/         # Migraciones de base de datos
│
├── api-service/         # Servicio web (FastAPI)
│   └── api/
│       ├── main.py      # App FastAPI
│       ├── routers/     # REST endpoints
│       └── templates/   # Dashboard HTML (Jinja2)
│
└── workers/
    ├── fetch_price/     # Cron diario: vela diaria cerrada de cada símbolo
    ├── daily/           # Cron diario: evaluate → train → predict
    │   └── models/      # BaseModel abstract + modelos ML
    └── backtest/        # Cron mensual: backtest walk-forward
```

**Nota:** Estructura final implementada. Todos los workers están funcionando en Railway.

---

## 🗄️ Base de Datos

### Tablas principales

1. **`prices`** — Una vela diaria OHLCV por símbolo, desde Binance
   - `symbol` (`BTCUSDT`, `PAXGUSDT`) y `timestamp` (apertura de la vela, 00:00 UTC)
   - Constraint UNIQUE en `(symbol, timestamp)` (idempotencia)

2. **`models`** — Modelos ML entrenados (serializados con pickle)
   - Columna `artifact` (BYTEA) contiene el modelo
   - Solo 1 modelo activo por `(symbol, familia, timeframe)` (familia = nombre sin el sufijo `_v<N>`)

3. **`predictions`** — Predicciones + evaluación (horizonte `1d`, el único permitido)
   - Fase 1: Insertar predicción (hoy predice mañana)
   - Fase 2: Evaluar cuando la vela que la liquida ya está guardada (calcular error, PnL)

4. **`backtest_results`** — Una fila por día de cada corrida walk-forward
   - `backtest_run_id` (UUID por corrida) y `evaluation_slice` (`validation` o `test`)

---

## 🧭 Enfoque

- **Datos:** una vela diaria cerrada (UTC) por símbolo, de [data.binance.vision](https://data.binance.vision). Es gratis, trae volumen y tiene historial desde 2017-08 (BTC) y 2020-08 (PAXG). La fuente anterior se reemplazó (#102) porque solo daba 30 días de historial y no traía volumen.
- **Features:** `W` retornos logarítmicos rezagados, su desviación estándar (volatilidad) y `W` cambios logarítmicos de volumen. `W` es `TRAINING_WINDOW_DAYS` (21 por defecto).
- **Modelo:** regresión lineal que predice el retorno logarítmico del día siguiente; el precio predicho es `último cierre × exp(retorno predicho)`. XGBoost, LSTM y ARIMA se eliminaron (issue [#184](https://github.com/cuauhtemocbe/btc-predictor/issues/184)); quedan en el historial de git.
- **Evaluación honesta:** cada exactitud o PnL se muestra junto a tres baselines (*always-up*, *persistence* y *buy-and-hold*) sobre los mismos días, con el tamaño de muestra, la ventaja (edge) y un p-value binomial. El backtest usa el mismo código de features y modelos que producción y separa un tramo de validación de un tramo de test que nunca se usa para decidir nada.
- **Oro vía PAXG:** Binance no tiene un par de oro spot (XAU). El dashboard muestra el oro con `PAXGUSDT`, el token PAX Gold (1 token = 1 onza troy de oro físico), que opera 24/7. Es un **proxy**, no XAU spot: puede cotizar con una prima o descuento sobre el oro y sigue el horario y la liquidez de un exchange de cripto, no el fixing de Londres. Su historial es más corto (desde 2020-08). El worker `daily` solo entrenan y predicen `BTCUSDT`; PAXG se ingesta y se muestra en el dashboard.

---

## 📉 Resultados

**Conclusión: el modelo lineal no supera de forma significativa a los baselines.** Con todos los datos y el mismo código que producción, la diferencia contra el mejor baseline es de unas décimas de punto porcentual y su p-value está lejos de 0.05. En el último tramo corto de 100 días el modelo incluso quedó por debajo de ambos baselines.

Corridas reales de `scripts/backtest.py` (Linear, ventana 21 días, seed 42, reentrenando cada día; datos de `BTCUSDT` hasta 2026-08-31; PnL *simple* = largo 1 BTC cuando predice subida, en USDT, sin fees). El p-value es binomial unilateral contra el mejor baseline.

**Corrida larga: 2019-01-01 a 2026-08-31, test desde 2024-01-01**

| Tramo | Días | Exactitud modelo | Always-up | Persistence | Edge vs mejor baseline | p-value | PnL modelo | PnL always-up (= buy-and-hold) | PnL persistence |
|-------|-----:|-----------------:|----------:|------------:|-----------------------:|--------:|-----------:|-------------------------------:|----------------:|
| **Test (fuera de muestra)** | 974 | 51.23% | 50.72% | 49.08% | +0.51 pp | 0.39 | $38,486 | $36,298 | $23,100 |
| Validación | 1826 | 48.69% | 51.20% | 45.29% | −2.52 pp | 0.99 | −$8,660 | $38,581 | −$9,999 |

**Corrida con la configuración del cron mensual: 2025-09-01 a 2026-08-31, últimos 100 días como test**

| Tramo | Días | Exactitud modelo | Always-up | Persistence | Edge vs mejor baseline | p-value | PnL modelo | PnL always-up (= buy-and-hold) | PnL persistence |
|-------|-----:|-----------------:|----------:|------------:|-----------------------:|--------:|-----------:|-------------------------------:|----------------:|
| **Test (fuera de muestra)** | 100 | 43.00% | 49.00% | 50.00% | −7.00 pp | 0.93 | −$4,603 | $1,829 | $11,451 |
| Validación | 265 | 51.32% | 49.06% | 53.58% | −2.26 pp | 0.79 | −$19,972 | −$31,494 | −$6,581 |

Cómo leerlo:

- **Ninguna ventaja es significativa.** Un +0.51 pp sobre 974 días es indistinguible de ruido, y con 100 días una diferencia de varios puntos también lo es.
- **El PnL positivo del test largo no es mérito del modelo.** El mercado subió en ese periodo; always-up (comprar y mantener) gana casi lo mismo ($36,298 contra $38,486), y el modelo pierde dinero en el tramo de validación mientras always-up gana.
- **Las exactitudes rondan el 50%** porque la dirección diaria de BTC es casi un volado; la referencia histórica de 2017 a 2026 es 51.1% para always-up y 46.5% para persistence.
- **Limitaciones:** un solo modelo, una sola semilla, un solo activo (`BTCUSDT`), sin fees en el PnL simple ni costos de slippage. No hay resultados de LSTM, XGBoost ni ARIMA (se eliminaron del código en #184; producción solo usó regresión lineal) y la frecuencia horaria se probó y se descartó: la ventaja de dirección es de ~1 pp pero vale ~2 bps por operación contra 20 bps de comisiones ([spike #109](docs/spikes/109-intraday-prediction.md)).

Para reproducirlo:

```bash
docker compose exec api python scripts/load_binance_history.py   # una vez
docker compose exec api python scripts/backtest.py \
  --start-date=2019-01-01 --end-date=2026-08-31 \
  --test-start-date=2024-01-01 --training-window=21 --seed=42 --retrain-every=1
```

Ver [docs/BACKTESTING.md](docs/BACKTESTING.md) para el detalle de cómo se calculan los baselines y el p-value.

---

## 🚦 Inicio Rápido

### Prerrequisitos

- **Docker + Docker Compose** (OBLIGATORIO)
- Git
- Un editor de código (VS Code, PyCharm, etc.)

**IMPORTANTE:** NO necesitas instalar Python, Poetry, ni PostgreSQL en tu máquina local. Todo se ejecuta dentro de contenedores.

### Desarrollo Local (Container-First)

```bash
# 1. Clonar el repositorio
git clone https://github.com/cuauhtemocbe/btc-predictor.git
cd btc-predictor

# 2. Copiar variables de entorno (opcional - hay defaults)
cp .env.example .env

# 3. Levantar servicios con Docker Compose
docker compose up

# 4. Acceder al API
open http://localhost:8010/docs  # Swagger UI
open http://localhost:8010/health  # Health check
```

El comando `docker compose up` levanta:
- ✅ PostgreSQL en puerto 5432
- ✅ API con hot-reload en puerto 8000
- ✅ Todos los volumes montados para desarrollo

### Correr Tests (SIEMPRE dentro del contenedor)

```bash
# Levantar servicios (si no están corriendo)
docker compose up -d

# Ejecutar TODOS los tests del proyecto (shared + api-service + workers)
docker compose exec api pytest

# Con coverage
docker compose exec api pytest --cov --cov-report=term-missing

# Tests de un servicio específico
docker compose exec api pytest shared/tests/
docker compose exec api pytest api-service/tests/
docker compose exec api pytest workers/fetch_price/tests/
docker compose exec api pytest workers/daily/tests/

# Un test específico
docker compose exec api pytest shared/tests/test_utils.py::test_calculate_pnl

# Verbose + mostrar prints
docker compose exec api pytest -v -s

# Tests en paralelo (más rápido)
docker compose exec api pytest -n auto
```

**⚠️ NUNCA ejecutes `pytest` directamente en el host** — no tendrá acceso al entorno correcto.

**Aislamiento de datos:** Los tests usan fixtures de pytest (`conftest.py`) que crean datos de entrada y los eliminan automáticamente al final de cada test (patrón `yield`).

### CI/CD

GitHub Actions ejecuta la misma validación dentro de Docker en cada push y pull request:

- Ruff lint y formato sobre `shared`, `api`, `workers` y `scripts`
- mypy estricto sobre `shared`, `workers`, `api` y `scripts` (sin los tests de workers, api y scripts)
- pytest con cobertura mínima del proyecto
- Cobertura mínima por módulo crítico (`[tool.coverage_thresholds]` en `pyproject.toml`)
- Reporte de cobertura como artefacto del workflow

El workflow semanal de calidad ejecuta mutation testing con Cosmic Ray. Los despliegues a Railway continúan gestionados por la integración nativa de Railway con GitHub; no se duplican mediante otro workflow ni requieren secretos Railway en GitHub Actions.

La protección de `main` y la exigencia de checks obligatorios se configura por separado en la issue [#49](https://github.com/cuauhtemocbe/btc-predictor/issues/49).

### Carga de Historial de Precios (#101)

Para cargar años de precios diarios de BTC (`BTCUSDT`, desde 2017-08) y oro (`PAXGUSDT`, proxy desde 2020-08) desde [data.binance.vision](https://data.binance.vision) y entrenar/evaluar con miles de días:

```bash
# Cargar todo el historial de ambos símbolos hasta el último mes cerrado
docker compose exec api python scripts/load_binance_history.py

# Un solo símbolo
docker compose exec api python scripts/load_binance_history.py --symbols PAXGUSDT

# Verificar que el host es alcanzable desde Railway (sin HTTP 451/403), sin escribir en la BD
railway run -s api python scripts/load_binance_history.py --check

# Carga en producción (Railway)
railway run -s api python scripts/load_binance_history.py
```

**Características:**
- ✅ **Idempotente:** volver a ejecutarlo no duplica filas (`ON CONFLICT DO NOTHING` sobre `unique_price_per_symbol`)
- ✅ **Verificación SHA256:** cada zip se compara con su `.CHECKSUM`; si no coincide no se inserta nada de ese archivo y el error nombra el archivo
- ✅ **Falla de forma clara:** un mes faltante (404) o un zip corrupto detiene la carga con un error explícito
- ✅ **Validación de continuidad:** al terminar, reporta cualquier día faltante o con volumen 0
- ✅ **Timestamps normalizados:** los CSV usan milisegundos hasta 2024 y microsegundos desde 2025-01-01; ambos se guardan como 00:00 UTC
- El código vive en `shared/shared/binance_vision.py` (solo stdlib para HTTP)

### Backtesting Walk-Forward (US-020)

Para validar la efectividad del modelo simulando predicciones históricas:

```bash
# Backtest de mayo 2024 (30 días)
docker compose exec api python scripts/backtest.py \
  --start-date=2024-05-01 --end-date=2024-05-30

# Backtest con ventana de entrenamiento de 60 días
docker compose exec api python scripts/backtest.py \
  --start-date=2024-05-01 --end-date=2024-05-30 \
  --training-window=60

# Split validación/test explícito, reentrenando cada 30 días
docker compose exec api python scripts/backtest.py \
  --start-date=2023-01-01 --end-date=2025-12-31 \
  --retrain-every=30 --test-start-date=2025-01-01

# Backtest de últimos 90 días
docker compose exec api python scripts/backtest.py \
  --start-date=2024-02-01 --end-date=2024-04-30
```

**Características:**
- ✅ **Walk-Forward Testing:** Entrena modelo progresivamente sin lookahead bias, con el mismo código de features y modelos que el worker diario
- ✅ **Baselines y significancia:** compara contra always-up, persistence y buy-and-hold, con tamaño de muestra, edge y p-value; el headline usa solo el slice de test
- ✅ **4 Estrategias PnL:** Simple, Long/Short, Threshold, Realistic (con fees)
- ✅ **UUID por Run:** Distingue múltiples simulaciones
- ✅ **Progress Logging:** Muestra progreso cada 10 días
- ✅ **Manejo de Errores:** Skipea días con datos faltantes o errores de entrenamiento

**Ver resultados:**
```bash
docker compose exec postgres psql -U btcpredictor -d btcpredictor \
  -c "SELECT backtest_run_id, COUNT(*) AS predictions, 
      SUM(pnl_realistic) AS total_pnl 
      FROM backtest_results GROUP BY backtest_run_id;"
```

**Documentación completa:** Ver [docs/BACKTESTING.md](docs/BACKTESTING.md)

### Aplicar Migraciones (después de Iteración 1)

```bash
# Ejecutar dentro del contenedor
docker compose exec api sh -c "cd shared && alembic upgrade head"
```

### Shell Interactivo (para debugging)

```bash
# Acceder al contenedor
docker compose exec api bash

# Desde dentro del contenedor puedes ejecutar:
pytest
python -m fetch_price.main
alembic upgrade head
```

---

## 📡 API Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/?symbol=BTCUSDT&source=all` | Dashboard HTML con predicciones y PnL (`symbol`: `BTCUSDT` o `PAXGUSDT`; `source`: `live`, `replay` o `all`) |
| `GET` | `/models/?symbol=BTCUSDT&source=all` | Comparación de modelos contra baselines |
| `GET` | `/backtesting?symbol=BTCUSDT` | Resultados de backtesting |
| `GET` | `/health` | Health check del servicio |
| `GET` | `/api/prices?limit=24&symbol=BTCUSDT` | Últimas N velas diarias |
| `GET` | `/api/predictions/history?from=…&to=…&timeframe=1d&source=all` | Historial de predicciones; cada fila trae `is_replay` |
| `GET` | `/api/predictions/pnl` | PnL acumulado simulado |
| `GET` | `/api/predictions/strategies` | PnL por estrategia |
| `GET` | `/api/backtesting/metrics` | Métricas de backtesting |
| `GET` | `/docs` | Swagger UI (auto-generado) |

`source` separa las predicciones que hizo el sistema en producción (`live`) de las que `scripts/simulate_history.py` repitió sobre días anteriores al lanzamiento (`replay`); sin el parámetro devuelve ambas (`all`). Un valor distinto de los tres da 422. `/api/predictions/pnl` y `/api/predictions/strategies` todavía no tienen `source`.

---

## 🔄 Flujo de Trabajo

### Cada día (00:05 UTC): `fetch-price` (cron)

```
data.binance.vision → fetch-price job → prices table
```

1. Por cada símbolo (`BTCUSDT`, `PAXGUSDT`) lee el archivo `daily/` de data.binance.vision; si aún no está publicado, usa el REST `data-api.binance.vision`
2. Inserta las velas diarias cerradas que falten, sin guardar nunca el día en curso (idempotente: omite lo que ya existe)
3. Termina con código distinto de cero si ambas fuentes fallan

### Cada día (00:10 UTC): `daily` (cron)

```
Evaluator → Trainer → Predictor
```

1. **Evaluator:** Evalúa predicción de ayer (calcula error, PnL)
2. **Trainer:** Entrena el modelo con todas las velas diarias de `BTCUSDT`, guarda en `models`
3. **Predictor:** Predice el precio de mañana, guarda en `predictions`

### Cada mes (día 1, 00:00 UTC): `monthly-backtest` (cron)

Corre `scripts/backtest.py` con la configuración de producción (ventana `TRAINING_WINDOW_DAYS`, últimos 365 días, últimos 100 como test) y guarda el resultado en `backtest_results`.

---

## 🧪 Testing

### Regla Fundamental

**Cada criterio de aceptación (Gherkin) debe tener al menos 1 test automatizado.**

Esta regla es **no negociable**:
- Si el criterio no tiene un test que falla cuando se rompe, el criterio no está cubierto
- "Lo probé manualmente", "se ve bien en el browser", "confío en que funciona" **NO son aceptables**
- Una User Story no se puede cerrar hasta que todos sus escenarios Gherkin tengan tests que pasen

### Estructura de Tests

Cada servicio tiene su carpeta `tests/`:

```
shared/tests/           # Config, models, CRUD, utils
api-service/tests/              # API endpoints + dashboard
workers/fetch_price/tests/ # Job de ingesta diaria
workers/daily/tests/       # Evaluator, trainer, predictor, models ML
```

### Tipos de Tests

- **Unit:** Funciones puras (`calculate_pnl`, model `predict()`)
- **Integration:** Operaciones de DB, migraciones Alembic
- **API:** Endpoints FastAPI con `httpx.AsyncClient`
- **Job:** Idempotencia, error handling, mocking de APIs externas

### Comandos de Tests (SIEMPRE dentro del contenedor)

**⚠️ IMPORTANTE:** Todos los comandos de test deben ejecutarse con `docker compose exec api`.

**El comando `docker compose exec api pytest` (sin argumentos) ejecuta TODOS los tests del proyecto** — no solo los del API, sino también shared, workers, fetch_price, daily, etc.

```bash
# Levantar servicios (si no están corriendo)
docker compose up -d

# ✅ Correr TODOS los tests del proyecto (shared + api-service + workers)
docker compose exec api pytest

# Tests de un servicio específico
docker compose exec api pytest shared/tests/
docker compose exec api pytest api-service/tests/
docker compose exec api pytest workers/fetch_price/tests/
docker compose exec api pytest workers/daily/tests/

# Tests con cobertura (target: >80%)
docker compose exec api pytest --cov --cov-report=term-missing
docker compose exec api pytest --cov --cov-report=html  # genera htmlcov/index.html

# Un test específico
docker compose exec api pytest shared/tests/test_utils.py::test_calculate_pnl

# Verbose + print statements
docker compose exec api pytest -v -s

# Tests en paralelo (más rápido)
docker compose exec api pytest -n auto
```

**❌ NO ejecutes `pytest` directamente en el host** — no tendrá el entorno Python correcto ni acceso a la base de datos.

### Aislamiento de Tests

**Estrategia simple:** Los tests usan la misma base de datos `postgres` que desarrollo.

El aislamiento se logra mediante **fixtures de pytest** en `conftest.py`:

```python
# Ejemplo: tests/conftest.py
@pytest.fixture
def db_session():
    """Session con rollback automático"""
    session = SessionLocal()
    yield session
    session.rollback()  # Deshace cambios después del test
    session.close()


@pytest.fixture
def sample_data(db_session):
    """Crea datos de prueba, auto-eliminados al terminar"""
    data = MyModel(name="test")
    db_session.add(data)
    db_session.commit()
    yield data
    # Cleanup automático por rollback de session
```

**Beneficios:**
- ✅ Simple: una sola base de datos
- ✅ Rápido: no necesitas levantar contenedores adicionales
- ✅ Seguro: fixtures garantizan cleanup automático
- ✅ Estándar: patrón común en pytest

**Opción 2: SQLite in-memory** (para CI rápido)
```python
# conftest.py usa sqlite:///:memory: automáticamente
```

### Frameworks & Tools

- `pytest` — test runner principal
- `pytest-asyncio` — soporte para tests async
- `httpx` — async HTTP client para API tests
- `pytest-mock` / `respx` — mocking (Binance API, etc.)
- `pytest-cov` — reportes de cobertura
- `pytest-xdist` — ejecución en paralelo

### Ver Testing Strategy Completa

Para ejemplos detallados, fixtures, y configuración de CI/CD:
- **[IMPLEMENTATION_HISTORY.md](docs/archive/specs/IMPLEMENTATION_HISTORY.md#testing-strategy)** — Testing Strategy completa

---

## 🌍 Variables de Entorno

```bash
# Requeridas
DATABASE_URL=postgresql://user:password@localhost:5432/btcpredictor

# Opcionales (defaults)
TRAINING_WINDOW_DAYS=21
TZ=America/Mexico_City
PORT=8000
ENVIRONMENT=development
```

**Railway inyecta automáticamente:**
- `DATABASE_URL` (del plugin postgres)
- `PORT` (solo para servicio `api`)

---

## 🚢 Deploy en Railway

### Configuración

1. Crear proyecto en Railway
2. Agregar plugin PostgreSQL
3. Crear 5 servicios (detalle en [RAILWAY_DEPLOYMENT.md](RAILWAY_DEPLOYMENT.md) y [RAILWAY_MULTISTAGE_CONFIG.md](RAILWAY_MULTISTAGE_CONFIG.md)):
   - **api:** Web service (`Dockerfile.api`)
   - **fetch-price:** Cron `5 0 * * *` (00:05 UTC diario)
   - **daily:** Cron `10 0 * * *` (00:10 UTC diario, termina con código 1 si la última vela cerró hace más de 2 horas)
   - **monthly-backtest:** Cron `0 0 1 * *` (día 1 de cada mes, 00:00 UTC)
   - **postgres:** Plugin (automático)

4. Conectar servicios al repo de GitHub
5. Agregar variables de entorno
6. Deploy automático en cada push a `main`

### Ver Logs

```bash
railway logs --service api
railway logs --service fetch-price
railway logs --service daily
railway logs --service monthly-backtest
```

---

## 📈 Desarrollo Iterativo

El proyecto siguió un enfoque **incremental y deployable**. Cada iteración agregó features y fue desplegada a Railway.

| Iteración | Goal | User Stories | Status |
|-----------|------|--------------|--------|
| 0 | Hello World | - | ✅ Done |
| 1 | Database Foundation | US-001, US-002 | ✅ Done |
| 2 | Fetch BTC Prices | US-003, US-004 | ✅ Done |
| 3 | Prices API | US-005 | ✅ Done |
| 4 | ML Foundation | US-006, US-007 | ✅ Done |
| 5 | Predictions & Evaluation | US-008, US-009, US-010 | ✅ Done |
| 6 | Dashboard UI | US-011, US-012 | ✅ Done |
| 7 | PnL Simulation | US-013, US-014 | ✅ Done |
| 8 | Production Crons | US-015, US-016 | ✅ Done |

**Todas las iteraciones completadas** — Ver historial detallado en [IMPLEMENTATION_HISTORY.md](docs/archive/specs/IMPLEMENTATION_HISTORY.md)

---

## 📚 Documentación

- **[IMPLEMENTATION_HISTORY.md](docs/archive/specs/IMPLEMENTATION_HISTORY.md)** — Historial completo de implementación (8 iteraciones)
- **[.claude/CLAUDE.md](.claude/CLAUDE.md)** — Contexto del proyecto para Claude Code
- **[User Stories](https://github.com/cuauhtemocbe/btc-predictor/issues)** — 16 User Stories (todas cerradas ✅)

---

## 🤝 Contribuir

Este es un proyecto personal de aprendizaje, pero se aceptan sugerencias vía issues.

1. Fork el proyecto
2. Crea una branch: `git checkout -b feature/nueva-feature`
3. Commit cambios: `git commit -m 'Agrega nueva feature'`
4. Push a la branch: `git push origin feature/nueva-feature`
5. Abre un Pull Request

**Importante:** Asegúrate de que los tests pasen antes de abrir PR.

---

## 📝 Notas

### Modelo ML

**Regresión lineal sobre retornos** con ventana de `TRAINING_WINDOW_DAYS` días (21 por defecto), entrenada con todas las velas diarias de `BTCUSDT`:
- **Features:** `W` retornos logarítmicos rezagados, su volatilidad y `W` cambios logarítmicos de volumen (`2W + 1` features)
- **Target:** retorno logarítmico del día siguiente
- **Librería:** scikit-learn

**Otros modelos:** XGBoost, LSTM y ARIMA se eliminaron en la issue [#184](https://github.com/cuauhtemocbe/btc-predictor/issues/184) (siguen en el historial de git). `BaseModel` abstract queda como la interfaz que usan el trainer y el predictor; cualquier modelo nuevo debe superar a la regresión lineal y a la regla de trading después de comisiones. El trainer diario (`python -m workers.daily.trainer`) entrena y activa el modelo lineal; no hay modo multi-modelo ni selección del mejor de varios (se quitaron en #184, segundo paso).

### Estrategia PnL

- Si el modelo predice **subida** → entramos long 1 BTC
- Si predice **bajada** → nos quedamos en cash (PnL = 0)
- **Fórmula:** `PnL = actual_price - price_at_prediction` (si entramos long)
- El backtest calcula además las estrategias long/short, con umbral y realista (fees de 0.1% y stop-loss de 2%); ver [docs/BACKTESTING.md](docs/BACKTESTING.md)

### Idempotencia

Todos los jobs son **idempotentes** (se pueden ejecutar múltiples veces sin duplicar datos):
- `fetch-price`: UNIQUE constraint en `(symbol, timestamp)`
- `predictor`: Check si predicción ya existe antes de insertar

---

## 📞 Contacto

**Autor:** Cuauhtémoc  
**Email:** cuauhtemocbe@gmail.com  
**GitHub:** [@cuauhtemocbe](https://github.com/cuauhtemocbe)

---

## 📄 Licencia

Este proyecto es de código abierto bajo licencia MIT.

---

**⚡ Ready to build the future of Bitcoin prediction!**
