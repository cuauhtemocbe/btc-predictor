# BTC Predictor

Webapp de Data Science para predecir el precio del Bitcoin al día siguiente usando modelos de Machine Learning. Registra predicciones, calcula errores históricos y simula PnL (ganancia/pérdida) basado en la dirección predicha.

**Es un proyecto de aprendizaje, no asesoría financiera.** Cada resultado se compara contra baselines triviales y, como muestra la sección [Resultados](#-resultados), el modelo actual **no supera de forma significativa** a esos baselines.

---

## 🚀 Estado del Proyecto

Desplegado en Railway: <https://btc-predictor-production-096e.up.railway.app>. El trabajo pendiente y el histórico están en los [issues](https://github.com/cuauhtemocbe/btc-predictor/issues) y en el [tablero](https://github.com/users/cuauhtemocbe/projects/1/views/1).

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

Cinco servicios en Railway. Los comandos de inicio y los horarios viven en el dashboard de Railway, no en los `railway.*.toml` ([RAILWAY_MULTISTAGE_CONFIG.md](RAILWAY_MULTISTAGE_CONFIG.md)).

| Servicio | Tipo | Qué hace |
|----------|------|----------|
| `postgres` | Plugin de Railway | Base de datos compartida |
| `api` | Web, siempre activo | FastAPI y dashboard |
| `fetch-price` | Cron `5 0 * * *` | Guarda la vela diaria cerrada de cada símbolo |
| `daily` | Cron `10 0 * * *` | Evalúa, entrena y predice (horizonte 1 día) |
| `monthly-backtest` | Cron `0 0 1 * *` | Backtest walk-forward con la configuración de producción |

Historial de decisiones: [IMPLEMENTATION_HISTORY.md](docs/archive/specs/IMPLEMENTATION_HISTORY.md).

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

Todo corre en Docker: no instales Python, Poetry ni PostgreSQL en tu máquina, y no ejecutes `pytest` en el host.

```bash
git clone https://github.com/cuauhtemocbe/btc-predictor.git
cd btc-predictor
cp .env.example .env        # opcional, hay valores por defecto
docker compose up           # PostgreSQL (5433 en el host) y API con hot-reload (8010 en el host)
```

La API queda en <http://localhost:8010/docs> (Swagger) y <http://localhost:8010/health>. Migraciones: `docker compose exec api sh -c "cd shared && alembic upgrade head"`. Shell: `docker compose exec api bash`.

### Tests

```bash
docker compose exec api pytest                                    # todo el proyecto
docker compose exec api pytest -n 4 --dist loadscope              # en paralelo, una base de datos por worker
docker compose exec api pytest --cov --cov-report=term-missing    # con cobertura
docker compose exec api pytest shared/tests/test_utils.py::test_calculate_pnl   # uno solo
```

Los tests usan bases de datos propias (`btcpredictor_test`, `btcpredictor_test_gw0`, ...); la base de desarrollo no se toca. Cada criterio de aceptación (Gherkin) tiene al menos un test que falla cuando el criterio se rompe; una User Story no se cierra sin ellos. Las reglas y los comandos de calidad completos están en [CLAUDE.md](CLAUDE.md).

### CI/CD

GitHub Actions (`.github/workflows/ci.yml`, en cada pull request y en cada push a `main`) corre en Docker: Ruff (lint y formato), mypy estricto sobre `shared`, `workers`, `api` y `scripts` con sus tests, pytest con cobertura y la cobertura mínima por módulo (`[tool.coverage_thresholds]` en `pyproject.toml`). Un workflow semanal (`quality.yml`) corre mutation testing con Cosmic Ray, con un máximo de 45 minutos, y sube el artefacto `mutation-report`. Railway despliega con su integración nativa con GitHub. Las protecciones de `main` están en [CLAUDE.md](CLAUDE.md).

### Carga de historial de precios (#101)

Carga los precios diarios de `BTCUSDT` (desde 2017-08) y `PAXGUSDT` (desde 2020-08) de [data.binance.vision](https://data.binance.vision):

```bash
docker compose exec api python scripts/load_binance_history.py                      # ambos símbolos
docker compose exec api python scripts/load_binance_history.py --symbols PAXGUSDT   # uno solo
railway run -s api python scripts/load_binance_history.py --check                   # solo verifica que el host responda desde Railway
```

El código está en `shared/shared/binance_vision.py` (solo stdlib para HTTP):

- **Idempotente:** `ON CONFLICT DO NOTHING` sobre `unique_price_per_symbol`.
- **Verificación SHA256:** cada zip se compara con su `.CHECKSUM`; si no coincide no se inserta nada de ese archivo.
- **Falla de forma clara:** un mes faltante (404) o un zip corrupto detiene la carga y el error nombra el archivo.
- **Validación de continuidad:** al terminar reporta los días faltantes o con volumen 0.
- **Timestamps normalizados:** los CSV traen milisegundos hasta 2024 y microsegundos desde 2025-01-01; ambos se guardan como 00:00 UTC.

### Backtesting walk-forward (US-020)

```bash
docker compose exec api python scripts/backtest.py --start-date=2024-05-01 --end-date=2024-05-30
docker compose exec api python scripts/backtest.py --start-date=2023-01-01 --end-date=2025-12-31 \
  --retrain-every=30 --test-start-date=2025-01-01
```

Entrena de forma progresiva sin sesgo de anticipación, con el mismo código de features y modelos que el worker diario; compara contra los baselines con tamaño de muestra, edge y p-value (el titular usa solo el tramo de test); calcula las 4 estrategias de PnL; y guarda cada corrida con su `backtest_run_id`. Opciones, columnas y consultas: [docs/BACKTESTING.md](docs/BACKTESTING.md).

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

Cada push a `main` despliega solo. Servicios, comandos de inicio y variables: [RAILWAY_DEPLOYMENT.md](RAILWAY_DEPLOYMENT.md) y [RAILWAY_MULTISTAGE_CONFIG.md](RAILWAY_MULTISTAGE_CONFIG.md). `daily` termina con código 1 si la última vela cerró hace más de 2 horas. Logs: `railway logs --service <api|fetch-price|daily|monthly-backtest>`.

---

## 📚 Documentación

- [IMPLEMENTATION_HISTORY.md](docs/archive/specs/IMPLEMENTATION_HISTORY.md): historial de decisiones.
- [CLAUDE.md](CLAUDE.md): contexto del proyecto para Claude Code.
- [CHANGELOG.md](CHANGELOG.md) e [issues](https://github.com/cuauhtemocbe/btc-predictor/issues).

## 🤝 Contribuir

Proyecto personal de aprendizaje; se aceptan sugerencias en issues. Abre una branch, haz commit, abre un Pull Request y asegúrate de que los tests pasen.

---

## 📝 Notas

### Modelo ML

Regresión lineal sobre retornos, descrita en [Enfoque](#-enfoque). `BaseModel` es la interfaz que usan el trainer, el predictor y el backtest; cualquier modelo nuevo debe superar a la regresión lineal y a la regla de trading después de comisiones. No hay modo multi-modelo ni selección del mejor de varios (se quitaron en #184).

### Estrategia PnL

- Si el modelo predice **subida** → entramos long 1 BTC
- Si predice **bajada** → nos quedamos en cash (PnL = 0)
- **Fórmula:** `PnL = actual_price - price_at_prediction` (si entramos long)
- El backtest calcula además las estrategias long/short, con umbral y realista (fees de 0.1% y stop-loss de 2%); ver [docs/BACKTESTING.md](docs/BACKTESTING.md)

### Idempotencia

Los jobs se pueden repetir sin duplicar datos: `fetch-price` por el UNIQUE `(symbol, timestamp)` y el predictor porque comprueba si la predicción ya existe.

---

## 📞 Contacto

**Autor:** Cuauhtémoc  
**Email:** cuauhtemocbe@gmail.com  
**GitHub:** [@cuauhtemocbe](https://github.com/cuauhtemocbe)

---

## 📄 Licencia

Este proyecto es de código abierto bajo licencia MIT.
