# CoinGecko API - Análisis Crítico de Granularidad

**Fecha:** 2026-05-23  
**Estado:** ⚠️ CRÍTICO - Requiere decisión estratégica antes de continuar

---

## 🔍 Resumen Ejecutivo

El análisis revela una **limitación crítica** del plan gratuito de CoinGecko que afecta directamente la estrategia de datos del proyecto BTC Predictor.

### Problema Crítico Identificado

**El backfill de 365 días retorna solo ~92 candles (1 cada 4 días), NO datos diarios.**

---

## 📊 Granularidad de CoinGecko OHLC API

### Plan Gratuito (Demo/Public) - Granularidad AUTOMÁTICA

CoinGecko aplica granularidad automática basada en el parámetro `days`:

| Rango de Días | Granularidad Automática | Candles Esperados | Ejemplo |
|---------------|-------------------------|-------------------|---------|
| **1-2 días** | **30 minutos** | 48-96 candles | `days=1` → 48 candles (24h × 2/hora) |
| **3-30 días** | **4 horas** | 18-180 candles | `days=7` → 42 candles (7d × 6/día) |
| **31+ días** | **4 DÍAS** | ~3-92 candles | `days=365` → 92 candles (365d ÷ 4) |

⚠️ **IMPORTANTE:** En el plan gratuito NO puedes especificar `interval=daily` o `interval=hourly`.

### Planes Pagados - Control Manual de Granularidad

Los suscriptores de planes pagados pueden usar el parámetro `interval`:

- `interval=daily` — disponible para: 1, 7, 14, 30, 90, 180 días
- `interval=hourly` — disponible para: 1, 7, 14, 30, 90 días

**Limitación:** Incluso en planes pagados, `interval=daily` NO funciona con `days=365`.

---

## 🧪 Validación con Datos Reales del Proyecto

### Observaciones en Producción

```
# Backfill ejecutado (2026-05-22 22:26:15)
days=365 → 92 candles
Granularity: ~96.0h between candles
Date range: 2025-05-24 to 2026-05-23

# fetch-price worker (logs anteriores)
days=1 → 48 candles (30-min granularity)
Inserted 2 new records
Skipped 46 existing timestamps
```

### Cálculo de Granularidad Real

| Configuración | Candles | Granularidad Calculada | Coincide con Docs |
|---------------|---------|------------------------|-------------------|
| `days=1` | 48 | 24h ÷ 48 = 30 min | ✅ Correcto |
| `days=7` | 42 | 7d × 24h ÷ 42 = 4h | ✅ Correcto |
| `days=365` | 92 | 365d ÷ 92 = 3.97 días ≈ 4 días | ✅ Correcto |

**Conclusión:** Los datos observados coinciden EXACTAMENTE con la documentación oficial.

---

## ⚠️ Implicaciones para BTC Predictor

### Estado Actual del Sistema

```python
# workers/fetch_price/main.py (línea 149)
prices = await fetch_prices(days=1)  # ← 48 candles de 30 minutos

# Cron schedule (actualizado)
fetch-price: 0 1 * * *  # Diario a la 1 AM UTC

# Backfill ejecutado
days=365 → 92 registros (1 cada 4 días)
```

### Problema 1: Granularidad Mixta en DB

La base de datos ahora contiene:

- **Datos históricos** (backfill): ~92 registros espaciados cada 4 DÍAS
- **Datos nuevos** (fetch-price): 48 registros espaciados cada 30 MINUTOS (diarios)

**Consecuencia:** El daily worker intentará agregar con `DATE_TRUNC('day')` pero encontrará:
- Días con 0 registros (en rango de backfill)
- Días con 48 registros (datos nuevos)

### Problema 2: Modelos Entrenarán con Datos Espaciados

El daily worker necesita 60 días de datos diarios:

```python
# workers/daily/trainer.py
min_days = 60  # Necesita 60 DÍAS

# Con backfill de 365 días espaciados cada 4 días:
# Solo tiene ~92 puntos de datos para 365 días
# ÷ 4 días/punto = ~23 puntos útiles en ventana de 60 días
```

**Resultado:** El modelo NO tendrá 60 días continuos, sino ~15 puntos de datos espaciados.

### Problema 3: Cron Diario con Granularidad 30-min

```
Cron: 0 1 * * * (1 ejecución al día)
API retorna: 48 candles de 30 minutos (cuando days=1)
```

**Desperdicio:** Fetching 47 candles extra que serán descartados (solo se usará el último).

---

## 🎯 Opciones Estratégicas

### Opción 1: Usar `days=7` para Granularidad 4-Horas ✅ RECOMENDADA

**Configuración:**
```python
# workers/fetch_price/main.py
prices = await fetch_prices(days=7)  # 42 candles de 4 horas

# Cron: 0 1 * * * (diario)
# Inserción esperada: ~6 candles nuevos/día
```

**Ventajas:**
- ✅ Granularidad consistente: 4 horas (6 candles/día)
- ✅ Permite agregación diaria con `DATE_TRUNC('day')`
- ✅ Datos suficientemente granulares para análisis diario
- ✅ Compatible con plan gratuito
- ✅ ~180 candles en 30 días (dataset sólido para ML)

**Desventajas:**
- ⚠️ No es estrictamente "1 registro/día"
- ⚠️ Requiere agregación (ya implementada con DATE_TRUNC)

**Implementación:**
1. Cambiar `fetch_price/main.py`: `days=1` → `days=7`
2. Mantener cron diario `0 1 * * *`
3. Mantener lógica de `DATE_TRUNC` en daily worker ✅ (ya implementado)
4. Limpiar backfill de 365 días (datos inconsistentes)
5. Ejecutar nuevo backfill con estrategia incremental

---

### Opción 2: Pagar Plan Analyst ($129/mes) para `interval=daily`

**Configuración:**
```python
prices = await fetch_prices(days=90, interval='daily')  # 90 días diarios
```

**Ventajas:**
- ✅ Datos estrictamente diarios (1 registro/día)
- ✅ Sin necesidad de agregación
- ✅ Hasta 90 días de datos diarios por request
- ✅ Rate limit más alto (500 calls/min)

**Desventajas:**
- ❌ Costo mensual: $129 USD
- ❌ No funciona con `days=365` (limitado a 180 días max)
- ❌ Overhead financiero para proyecto de prueba

---

### Opción 3: Migrar a Binance API (Alternativa)

**Binance ofrece:**
- ✅ Datos diarios gratuitos con endpoint `/klines`
- ✅ Granularidad configurable: 1m, 5m, 1h, 1d, 1w, 1M
- ✅ Hasta 1000 candles por request
- ✅ Sin restricciones geográficas (con IP correcta)

**Desventajas:**
- ⚠️ Ya experimentamos bloqueo HTTP 451 en Railway
- ⚠️ Requiere reescribir cliente completo
- ⚠️ Mayor complejidad de integración

---

## 📋 Decisión Requerida

### Preguntas para el Usuario

1. **¿Cuál es la granularidad mínima aceptable para el proyecto?**
   - Estrictamente 1 registro/día (requiere plan pagado)
   - 4-6 registros/día agregados a diario (plan gratuito)

2. **¿Presupuesto disponible para API de datos?**
   - $0 (continuar con plan gratuito)
   - $129/mes (upgrade a CoinGecko Analyst)

3. **¿Prioridad: consistencia de datos o costo?**
   - Consistencia máxima (pagar o migrar API)
   - Costo mínimo (adaptar a limitaciones gratuitas)

---

## 🚀 Recomendación Final

**Para continuar con plan gratuito de CoinGecko:**

### Implementación Sugerida: `days=7` con Agregación Diaria

```python
# 1. Actualizar fetch_price/main.py
prices = await fetch_prices(days=7)  # 4-hour candles

# 2. Mantener cron diario
# Railway: 0 1 * * *

# 3. Daily worker ya implementa DATE_TRUNC ✅
# workers/daily/trainer.py (línea ~70-85)
latest_per_day = (
    select(
        func.date_trunc("day", BtcPrice.timestamp).label("day"),
        func.max(BtcPrice.timestamp).label("latest_timestamp"),
    )
    .group_by("day")
    ...
)

# 4. Limpiar y re-backfill
# Eliminar 92 registros del backfill de 365 días
# Ejecutar backfills incrementales con days=7, days=14, days=30
```

### Datos Esperados en DB

| Período | Configuración | Candles | Granularidad | Registros/día |
|---------|---------------|---------|--------------|---------------|
| Backfill 30 días | `days=30` | 180 | 4 horas | ~6 |
| Daily fetch | `days=7` | 42 | 4 horas | ~6 |
| **Agregado diario** | `DATE_TRUNC` | 30 | **1 día** | **1** |

**Resultado final después de agregación:**
- ✅ 30 días × 1 registro/día = 30 puntos de datos diarios
- ✅ 60 días × 1 registro/día = 60 puntos de datos diarios (suficiente para entrenar)

---

## 📚 Fuentes Consultadas

### Documentación Oficial
- [CoinGecko API - Coin OHLC Chart by ID](https://docs.coingecko.com/reference/coins-id-ohlc)
- [CoinGecko Support - Historical Data Granularity](https://support.coingecko.com/hc/en-us/articles/4538747001881-What-granularity-do-you-support-for-historical-data)
- [CoinGecko API Pricing](https://www.coingecko.com/en/api/pricing)

### Análisis y Guías
- [How to Fetch Crypto Data Using Python (CoinGecko API)](https://www.coingecko.com/learn/python-query-coingecko-api)
- [CoinGecko API Troubleshooting Guide](https://www.coingecko.com/learn/coingecko-api-troubleshooting-guide-and-solutions)
- [Best Historical Crypto Data APIs (2026)](https://www.coingecko.com/learn/best-historical-crypto-data-apis)

---

## ✅ Próximos Pasos (Después de Decisión)

1. **Usuario decide** opción estratégica
2. **Actualizar** `fetch_price/main.py` según decisión
3. **Limpiar** datos del backfill de 365 días (DELETE FROM btc_prices WHERE ...)
4. **Ejecutar** nuevo backfill con estrategia correcta
5. **Verificar** que daily worker entrena correctamente
6. **Documentar** decisión en CLAUDE.md

---

**Estado:** ⏸️ **BLOQUEADO** - Esperando decisión estratégica del usuario
