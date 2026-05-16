# BTC Predictor

Webapp de Data Science para predecir el precio del Bitcoin al día siguiente usando modelos de Machine Learning. Registra predicciones, calcula errores históricos y simula PnL (ganancia/pérdida) basado en la dirección predicha.

---

## 🚀 Estado del Proyecto

**Iteración actual:** Iteración 0 ✅ (Hello World completado)  
**Próxima iteración:** Iteración 1 - Database Foundation (US-001, US-002)

[Ver User Stories en GitHub →](https://github.com/cuauhtemocbe/btc-predictor/issues)  
[Ver Proyecto Board →](https://github.com/users/cuauhtemocbe/projects/1/views/1)

---

## 📊 Stack Tecnológico

- **Lenguaje:** Python 3.13
- **Framework Web:** FastAPI + Jinja2
- **Base de datos:** PostgreSQL + SQLAlchemy 2.0 + Alembic
- **Machine Learning:** scikit-learn, pandas, numpy
- **Fuente de datos:** Binance Public API (sin autenticación)
- **Deploy:** Railway (4 servicios: postgres, api, fetch-price, daily)
- **Gestión de dependencias:** Poetry (monorepo con paquetes internos)

---

## 🏗️ Arquitectura Objetivo

El proyecto se despliega como **4 servicios en Railway**:

```
┌─────────────┐
│  postgres   │  Plugin nativo de Railway
└─────────────┘
      ↓
┌─────────────┐
│     api     │  Servicio web siempre activo (FastAPI + Dashboard)
└─────────────┘
      ↓
┌─────────────┐
│ fetch-price │  Cron cada hora: obtiene precios de Binance
└─────────────┘
      ↓
┌─────────────┐
│    daily    │  Cron diario (7am): evalúa → entrena → predice
└─────────────┘
```

**Ver documentación completa:** [ARCHITECTURE.md](ARCHITECTURE.md)

---

## 📂 Estructura del Proyecto

```
btc-predictor/
├── shared/              # Paquete compartido: shared
│   ├── shared/
│   │   ├── config.py    # Configuración (DATABASE_URL, etc.)
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
    ├── fetch_price/     # Cron horario: fetch precios BTC
    └── daily/           # Cron diario: evaluate → train → predict
        └── models/      # BaseModel abstract + modelos ML
```

**Nota:** Estructura actualizada y reorganizada. Próximos pasos: implementar workers de cron (US-003+).

---

## 🗄️ Base de Datos

### Tablas principales

1. **`btc_prices`** — Precios horarios OHLCV desde Binance
   - Constraint UNIQUE en `timestamp` (idempotencia)

2. **`models`** — Modelos ML entrenados (serializados con pickle)
   - Columna `artifact` (BYTEA) contiene el modelo
   - Solo 1 modelo activo por nombre

3. **`predictions`** — Predicciones diarias + evaluación
   - Fase 1: Insertar predicción (hoy predice mañana)
   - Fase 2: Evaluar al día siguiente (calcular error, PnL)

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
open http://localhost:8000/docs  # Swagger UI
open http://localhost:8000/health  # Health check
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

### Actuales (Iteración 0)

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/health` | Health check del servicio |
| `GET` | `/api/v1/hello?name=` | Endpoint de prueba |
| `GET` | `/docs` | Swagger UI (auto-generado) |

### Futuros (según iteraciones)

| Método | Ruta | Iteración | Descripción |
|--------|------|-----------|-------------|
| `GET` | `/api/prices?limit=168` | 3 | Últimos N precios horarios |
| `GET` | `/api/predictions/history` | 6 | Historial de predicciones evaluadas |
| `GET` | `/api/predictions/pnl` | 7 | PnL acumulado simulado |
| `GET` | `/` | 6 | Dashboard HTML con tabla de predicciones |

---

## 🔄 Flujo de Trabajo

### Cada hora: `fetch-price` (cron)

```
Binance API → fetch-price job → btc_prices table
```

1. Consulta Binance Public API: `GET /api/v3/klines`
2. Inserta nuevo precio en `btc_prices` (skip si ya existe)

### Cada día (7am): `daily` (cron)

```
Evaluator → Trainer → Predictor
```

1. **Evaluator:** Evalúa predicción de ayer (calcula error, PnL)
2. **Trainer:** Entrena modelo con datos históricos, guarda en `models`
3. **Predictor:** Predice precio de mañana, guarda en `predictions`

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
workers/fetch_price/tests/ # Binance client + job
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
- **[ARCHITECTURE.md](ARCHITECTURE.md#testing-strategy)** — Sección Testing Strategy

---

## 🌍 Variables de Entorno

```bash
# Requeridas
DATABASE_URL=postgresql://user:password@localhost:5432/btcpredictor

# Opcionales (defaults)
BINANCE_BASE_URL=https://api.binance.com
MODEL_WINDOW_DAYS=30
MODEL_NAME=linear_v1
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
3. Crear 4 servicios:
   - **api:** Web service (start command: `uvicorn api.main:app --host 0.0.0.0 --port $PORT`)
   - **fetch-price:** Cron `0 * * * *` (cada hora)
   - **daily:** Cron `0 7 * * *` (7am diario)
   - **postgres:** Plugin (automático)

4. Conectar servicios al repo de GitHub
5. Agregar variables de entorno
6. Deploy automático en cada push a `main`

### Ver Logs

```bash
railway logs --service api
railway logs --service fetch-price
railway logs --service daily
```

---

## 📈 Desarrollo Iterativo

El proyecto sigue un enfoque **incremental y deployable**. Cada iteración agrega features y se puede deployar a Railway.

| Iteración | Goal | User Stories | Status |
|-----------|------|--------------|--------|
| 0 | Hello World | - | ✅ Done |
| 1 | Database Foundation | US-001, US-002 | 🔲 Todo |
| 2 | Fetch BTC Prices | US-003, US-004 | 🔲 Todo |
| 3 | Prices API | US-005 | 🔲 Todo |
| 4 | ML Foundation | US-006, US-007 | 🔲 Todo |
| 5 | Predictions & Evaluation | US-008, US-009, US-010 | 🔲 Todo |
| 6 | Dashboard UI | US-011, US-012 | 🔲 Todo |
| 7 | PnL Simulation | US-013, US-014 | 🔲 Todo |
| 8 | Production Crons | US-015, US-016 | 🔲 Todo |

**Regla de oro:** No pasar a la próxima iteración hasta que la actual esté testeada y deployada.

---

## 📚 Documentación

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — Arquitectura completa del sistema
- **[.claude/CLAUDE.md](.claude/CLAUDE.md)** — Contexto del proyecto para Claude AI
- **[User Stories](https://github.com/cuauhtemocbe/btc-predictor/issues)** — Backlog en GitHub Issues

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

### Modelo ML Inicial

**Linear Regression** con ventana deslizante de 30 días:
- **Features:** Últimos 30 cierres diarios
- **Target:** Precio del día siguiente
- **Librería:** scikit-learn

**Futuros modelos:** ARIMA, LSTM, XGBoost (gracias a `BaseModel` abstract)

### Estrategia PnL

- Si el modelo predice **subida** → entramos long 1 BTC
- Si predice **bajada** → nos quedamos en cash (PnL = 0)
- **Fórmula:** `PnL = actual_price - price_at_prediction` (si entramos long)

### Idempotencia

Todos los jobs son **idempotentes** (se pueden ejecutar múltiples veces sin duplicar datos):
- `fetch-price`: UNIQUE constraint en `timestamp`
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
