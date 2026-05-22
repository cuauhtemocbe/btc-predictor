# US-025: Análisis de Tests - ¿Qué es necesario?

## Resumen Ejecutivo

**Implementación:** ✅ COMPLETA (predictor y evaluator ya soportan multi-modelo)
**Tests:** ⚠️ INCOMPLETOS (39 tests existen, pero NO cubren escenarios multi-modelo)

---

## Estado Actual del Código

### ✅ Predictor (`workers/daily/predictor.py`)
- [x] Flag `--multi-model` implementado (línea 46-61)
- [x] `get_active_models()` carga todos los modelos activos (línea 96-149)
- [x] Loop sobre múltiples modelos (línea 334-383)
- [x] Manejo de fallos individuales (línea 375-383)
- [x] Idempotencia por modelo (línea 338-346)
- [x] Soporte para diferentes `window_days` (línea 349)
- [x] Logging de resumen (línea 386-399)

### ✅ Evaluator (`workers/daily/evaluator.py`)
- [x] `find_unevaluated_predictions()` busca TODAS las predicciones (línea 41-71)
- [x] Loop sobre múltiples predicciones (línea 333-351)
- [x] Manejo de fallos individuales (línea 345-351)

---

## Escenarios Gherkin de US-025 (11 total)

### CRÍTICOS (deben tener tests) ⚠️

#### 1. ❌ **Predictor generates predictions from all active models**
**Por qué es crítico:** Core feature de US-025. Sin este test, no garantizamos que multi-modelo funcione.

**Test necesario:**
```python
def test_multi_model_generates_multiple_predictions():
    # Given: 3 active models (linear, lstm, xgboost)
    # When: predictor runs with --multi-model
    # Then: 3 predictions are created (one per model)
```

**Severidad:** 🔴 BLOCKER

---

#### 2. ❌ **CLI flag to enable/disable multi-model mode**
**Por qué es crítico:** Define el comportamiento por defecto. Sin este test, podríamos romper backward compatibility.

**Test necesario:**
```python
def test_multi_model_flag_disabled_uses_single_model():
    # Given: 3 active models
    # When: predictor runs WITHOUT --multi-model flag
    # Then: Only 1 prediction is created

def test_multi_model_flag_enabled_uses_all_models():
    # Given: 3 active models
    # When: predictor runs WITH --multi-model flag
    # Then: 3 predictions are created
```

**Severidad:** 🔴 BLOCKER (backward compatibility)

---

#### 3. ❌ **Handle prediction failure for one model**
**Por qué es crítico:** Resilience. Si LSTM falla, queremos que Linear y XGBoost sigan funcionando.

**Test necesario:**
```python
def test_multi_model_handles_individual_failure():
    # Given: 3 active models, LSTM deserialization fails
    # When: predictor runs in multi-model mode
    # Then: 2 predictions created (linear, xgboost)
    # And: Job exits with code 0 (success)
```

**Severidad:** 🟠 MAJOR (afecta producción si un modelo falla)

---

#### 4. ✅ **Single-model mode uses only the "best" active model**
**Estado:** YA CUBIERTO por `test_scenario_1_predict_next_day_price` (modo default).

**Severidad:** ✅ CUBIERTO

---

#### 5. ❌ **Evaluator evaluates predictions for all models**
**Por qué es crítico:** Sin esto, el evaluator solo evaluaría 1 predicción de las 3.

**Test necesario:**
```python
def test_evaluator_evaluates_all_models_predictions():
    # Given: 3 unevaluated predictions from 3 models for today
    # When: evaluator runs
    # Then: All 3 predictions are evaluated (actual_price != NULL)
```

**Severidad:** 🔴 BLOCKER

---

#### 6. ⚠️ **Idempotency: re-running predictor doesn't duplicate predictions**
**Estado:** Parcialmente cubierto (`test_scenario_4`) pero solo para single-model.

**Test necesario:**
```python
def test_multi_model_idempotency():
    # Given: 3 predictions already exist for tomorrow (3 models)
    # When: predictor runs again with --multi-model
    # Then: 0 new predictions created (all skipped)
    # And: Job exits with code 0
```

**Severidad:** 🟠 MAJOR (evita duplicados en retries)

---

### NO CRÍTICOS (nice-to-have, pero NO bloqueantes) ✅

#### 7. ⚪ **Skip inactive models in multi-model mode**
**Por qué NO es crítico:** Ya está implícitamente cubierto por el query SQL `WHERE is_active = TRUE` (línea 112).

**Test existente similar:** `test_inactive_model_not_loaded` ya verifica que inactivos no se cargan.

**Recomendación:** ⚪ SKIP (redundante con tests existentes)

---

#### 8. ⚪ **Each model uses the same input features**
**Por qué NO es crítico:** Es una consecuencia natural del diseño. El código obtiene `current_price` una vez (línea 322-326) y reutiliza.

**Recomendación:** ⚪ SKIP (no aporta valor, es diseño obvio)

---

#### 9. ⚪ **Predictions table supports multiple predictions per date**
**Por qué NO es crítico:** Es una propiedad del esquema de base de datos, no del código. Ya está validado por migration.

**Recomendación:** ⚪ SKIP (es esquema DB, no lógica)

---

#### 10. ⚪ **Log prediction summary for all models**
**Por qué NO es crítico:** Es observabilidad, no funcionalidad. El logging ya existe (línea 386-399).

**Recomendación:** ⚪ SKIP (logs no son críticos para tests automatizados)

---

#### 11. ⚪ **Different models can have different window_days**
**Por qué NO es crítico:** Ya está implementado (línea 349: `window_days = model_record.params.get("window_days", 30)`).

**Test existente similar:** `test_success_30_days` ya verifica que `get_recent_prices` respeta `window_days`.

**Recomendación:** ⚪ OPCIONAL (si querés agregar, es un test simple, pero NO bloqueante)

---

## Resumen de Tests Necesarios

### BLOQUEANTES (3 tests obligatorios) 🔴
1. ❌ `test_multi_model_generates_all_predictions` (escenario 1)
2. ❌ `test_cli_flag_multi_model` (escenario 9)
3. ❌ `test_evaluator_multi_model` (escenario 4)

### IMPORTANTES (3 tests recomendados) 🟠
4. ❌ `test_multi_model_failure_handling` (escenario 5)
5. ❌ `test_multi_model_idempotency` (escenario 6)
6. ⚪ `test_different_window_days` (escenario 11 - opcional)

### NO NECESARIOS (5 escenarios ya cubiertos o no críticos) ⚪
- ✅ Escenario 3: single-model mode (cubierto por test_scenario_1)
- ⚪ Escenario 2: skip inactive (redundante)
- ⚪ Escenario 7: same input features (diseño obvio)
- ⚪ Escenario 8: DB schema (no es test de código)
- ⚪ Escenario 10: logging (observabilidad)

---

## Recomendación Final

**Mínimo para cerrar US-025 (Definition of Done):** **6 tests nuevos**

### Obligatorios (3):
1. `test_multi_model_mode_generates_predictions_for_all_active_models`
2. `test_single_model_mode_uses_only_first_active_model`
3. `test_evaluator_evaluates_all_model_predictions`

### Recomendados (3):
4. `test_multi_model_mode_handles_individual_model_failure`
5. `test_multi_model_idempotency_skips_existing_predictions`
6. `test_models_with_different_window_days` (opcional)

**Total:** 6 tests = ~2-3 horas de trabajo.

---

## ¿Querés que escriba estos tests?

Si decís que sí, voy a:
1. Crear archivo `workers/daily/tests/test_us025_multi_model.py`
2. Implementar los 6 tests con fixtures
3. Verificar que todos pasen
4. Cerrar US-025

¿Dale?

---

## ACTUALIZACIÓN: Tests Implementados ✅

**Fecha:** 2026-05-22
**Estado:** COMPLETO

### Tests Creados

Archivo: `workers/daily/tests/test_us025_multi_model.py`

**6 tests implementados:**

1. ✅ `test_multi_model_mode_generates_predictions_for_all_active_models`
   - Verifica que con `--multi-model` se generen 3 predicciones (una por modelo activo)
   - **BLOCKER** - Escenario 1

2. ✅ `test_single_model_mode_uses_only_first_active_model`
   - Verifica que sin flag se genere solo 1 predicción (modo default)
   - **BLOCKER** - Escenario 3

3. ✅ `test_multi_model_flag_enabled_uses_all_active_models`
   - Verifica que el flag `--multi-model` active el modo correcto
   - **BLOCKER** - Escenario 9

4. ✅ `test_evaluator_evaluates_all_model_predictions`
   - Verifica que el evaluator evalúe las 3 predicciones (no solo 1)
   - **BLOCKER** - Escenario 4

5. ✅ `test_multi_model_handles_individual_model_failure`
   - Verifica que si LSTM falla, linear y xgboost continúan
   - **IMPORTANTE** - Escenario 5

6. ✅ `test_multi_model_idempotency_per_model`
   - Verifica que re-ejecutar no duplique las 3 predicciones
   - **IMPORTANTE** - Escenario 6

### Resultados

```bash
$ pytest workers/daily/tests/test_us025_multi_model.py -v
============================== 6 passed in 35.22s ===============================
```

**Cobertura de Escenarios Gherkin:** 6/11 (54.5%)

**Por qué no 11/11:**
- 5 escenarios NO necesitan tests (redundantes, DB schema, logging, diseño obvio)

### Impacto en Suite de Tests

**Antes de US-025:**
- Total tests proyecto: 400 tests
- Tests workers/daily: 185 tests

**Después de US-025:**
- Total tests proyecto: **406 tests** (+6)
- Tests workers/daily: **191 tests** (+6)
- Tests US-025 específicos: **6 tests**

**Estado del Proyecto:**
- ✅ 405 tests passing
- ❌ 1 test failing (pre-existente en `test_trainer.py::test_train_all_models_activates_best`)
- ⚠️ 11 warnings (esperados, statsmodels convergence)

### Conclusión

✅ **US-025 está lista para cerrar** con 6 tests nuevos que cubren todos los escenarios críticos:
- 3 tests BLOQUEANTES (obligatorios)
- 2 tests IMPORTANTES (resilience)
- 1 test BLOQUEANTE adicional (evaluator multi-model)

**Definition of Done cumplido:**
- ✅ Todos los escenarios Gherkin críticos tienen tests automatizados
- ✅ Tests pasan (6/6 = 100%)
- ✅ No se rompieron tests existentes (39 tests predictor/evaluator siguen pasando)
- ✅ Cobertura de casos edge: failure handling, idempotency, mode switching
