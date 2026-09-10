# Reporte: Flujo Funcional Completo del Módulo de Órdenes de Trabajo

**Fecha:** 2026-09-04 | **Estado:** ✅ COMPLETADO | **Tests:** 148/148 pasando

> **Actualización 2026-09-04 (misma fecha):** El usuario editó el template de Google
> (`Plantilla_Maestra` → tab `PLANTILLA_OT`). Se re-mapeó `ot_mapping.py` y
> `populate_ot_fields` al nuevo layout: campos desplazados una fila (descripción
> B11, responsables C14, tiempo C15), **Fecha Solicitud → C16** (nuevo), checkboxes
> de Tipo/LOTO por-celda (C8..G8 / C9..E9), status → B35, folio → G9, vale → C20,
> autorización con label+firma (B30/E30). Verificado en vivo: OT-2026-0015 completa.

> **Actualización 2026-09-04 (v2):** Se corrigió la carpeta destino de las OTs en
> Google Drive: `addParents`/`removeParents` iban en el body de `files().update()`
> (la API v3 solo los acepta como query params), por lo que la copia del template
> quedaba en `PLANTILLAS`. Verificado en vivo que ahora aterriza en
> `ÓRDENES DE TRABAJO/AÑO/MES`. Además se agregó: (1) **Contador de OTs** en `/admin`
> (totales por año y por mes del año actual + próximo N° OT), y (2) **Reapertura de
> OTs cerradas** por admin (`POST /reopen`): APPROVED → IN_PROGRESS, CANCELLED → DRAFT,
> con motivo obligatorio registrado en auditoría. Suite: **148/148**. `tsc` limpio.

> **Actualización 2026-09-04 (v3):** Se reordenaron los documentos OT que habían
> quedado en `PLANTILLAS` (por el bug de carpetas anterior): **9 OTs movidas** a
> `ÓRDENES DE TRABAJO/2026/SEPTIEMBRE` vía `scripts/relocate_ot_documents.py`
> (BD como fuente de verdad, idempotente, sin borrar nada, verificado con dry-run).
> Los 11 OTs con fecha de ejecución están ahora en su carpeta año/mes correcta.

---

## Resumen Ejecutivo

Se implementó el flujo funcional completo del módulo de Órdenes de Trabajo: modelo de 6 estados, state machine centralizada, matriz de permisos, 8 nuevos endpoints, sincronización Google durante todo el ciclo de vida, y framework de testing con 48 tests nuevos + 89 existentes sin regresiones.

**PostgreSQL es source of truth. Google Sheets es salida documental.**

---

## 1. MODELO DE DATOS

### 1.1 Estados (6 estados)

| Estado | Semántica | Acciones posibles |
|--------|-----------|-------------------|
| `DRAFT` | Borrador interno, no visible en mensual | Issue → PENDING, Cancel |
| `PENDING` | Emitida, esperando trabajo | Start → IN_PROGRESS, Cancel |
| `IN_PROGRESS` | Trabajo en ejecución | Complete → COMPLETED, Cancel |
| `COMPLETED` | Trabajo finalizado, pendiente revisión | Approve → APPROVED, Return → IN_PROGRESS, Cancel |
| `APPROVED` | Cerrada y aprobada | Terminal — sin transiciones |
| `CANCELLED` | Cancelada | Terminal — sin transiciones |

### 1.2 Campos nuevos en WorkOrder (15 columnas)

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `responsible_user_id` | FK → users | Responsable principal (NO se deriva de participantes) |
| `is_planned` | Boolean | OT planificada (para KPIs) |
| `scheduled_date` | Date | Fecha programada |
| `due_date` | Date | Fecha límite |
| `started_at` | DateTime(tz) | Timestamp de inicio de trabajo |
| `started_by_user_id` | FK → users | Quién inició |
| `completed_at` | DateTime(tz) | Timestamp de finalización |
| `completed_by_user_id` | FK → users | Quién finalizó |
| `actual_duration_minutes` | Float | Duración real en minutos |
| `completion_notes` | Text | Notas de finalización |
| `approved_at` | DateTime(tz) | Timestamp de aprobación |
| `approved_by_user_id` | FK → users | Quién aprobó |
| `cancellation_reason` | Text | Motivo de cancelación |
| `returned_at` | DateTime(tz) | Timestamp de devolución |
| `returned_by_user_id` | FK → users | Quién devolvió |
| `return_reason` | Text | Motivo de devolución |

### 1.3 Tabla M2M `work_order_participants`

Nueva tabla de asociación WorkOrder ↔ User. Se mantiene `participant_names` TEXT para compatibilidad con Google Sheets.

### 1.4 División de campos según quién los llena

| Campo | Quién lo llena |
|-------|----------------|
| Área, Equipo | Admin |
| Fecha de solicitud de la OT (`request_date`) | Admin (al solicitar la OT) |
| Descripción del trabajo | Admin |
| Solicitado por (firma) | Admin |
| Responsable principal | Admin (lo elige) |
| Participantes (quiénes entran en la OT) | Admin |
| Fecha de ejecución (`execution_date`) | Trabajador responsable |
| Sección (`section_name`) | Trabajador responsable |
| Hora inicio / Hora término | Trabajador responsable (auto → horas) |
| Horas manuales (`estimated_time`) | Trabajador responsable (puede escribir manualmente) |
| Tipo mantención, LOTO, recursos, riesgos, observaciones, folio, vale | Trabajador responsable |

### 1.5 Archivos

- [work_order.py](backend/app/models/work_order.py) — 6 estados, 16 campos nuevos, 3 relaciones de usuario
- [work_order_participants.py](backend/app/models/work_order_participants.py) — Tabla M2M
- [user.py](backend/app/models/user.py) — Relación `work_orders` M2M
- [0004_work_order_workflow.py](backend/alembic/versions/0004_work_order_workflow.py) — Migración (columnas + tabla + migración de datos)
- [0005_add_request_date.py](backend/alembic/versions/0005_add_request_date.py) — Migración (`request_date`)

---

## 2. STATE MACHINE CENTRALIZADA

### 2.1 Transiciones válidas

```python
VALID_TRANSITIONS = {
    "DRAFT":       ["PENDING", "CANCELLED"],
    "PENDING":     ["IN_PROGRESS", "CANCELLED"],
    "IN_PROGRESS": ["COMPLETED", "CANCELLED"],
    "COMPLETED":   ["APPROVED", "IN_PROGRESS", "CANCELLED"],
    "APPROVED":    [],   # terminal
    "CANCELLED":  [],   # terminal
}
```

### 2.2 Archivo

- [wo_state_machine.py](backend/app/services/wo_state_machine.py) — `validate_transition()`, `allowed_transitions()`, `InvalidTransitionError`

---

## 3. MATRIZ DE PERMISOS

**Regla de diseño:** Permisos = QUIÉN (rol + identidad). State machine = CUÁNDO (status). Separación estricta para que 403 = persona incorrecta, 400 = estado inválido.

| Acción | ADMIN | SUPERVISOR | RESPONSABLE | PARTICIPANTE |
|--------|:-----:|:----------:|:-----------:|:------------:|
| Crear OT | ✅ | ✅ | ❌ | ❌ |
| Editar OT | ✅ | ✅ | ❌ | ❌ |
| Emitir (DRAFT → PENDING) | ✅ | ✅ | ❌ | ❌ |
| Ver OT | Todas | Todas | Asignadas | Asignadas |
| Iniciar (PENDING → IN_PROGRESS) | ✅ | ❌ | ✅ (si es responsable) | ❌ |
| Finalizar (IN_PROGRESS → COMPLETED) | ✅ | ❌ | ✅ (si es responsable) | ❌ |
| Devolver (COMPLETED → IN_PROGRESS) | ✅ | ❌ | ❌ | ❌ |
| Aprobar (COMPLETED → APPROVED) | ✅ | ❌ | ❌ | ❌ |
| Cancelar | ✅ | ✅ | ❌ | ❌ |

### 3.1 Archivo

- [wo_permissions.py](backend/app/services/wo_permissions.py) — Funciones `can_create`, `can_edit`, `can_issue`, `can_start`, `can_complete`, `can_return_`, `can_approve`, `can_cancel`, `can_view`

---

## 4. ENDPOINTS NUEVOS (8)

| Método | Ruta | Acción |
|--------|------|--------|
| POST | `/api/work-orders` | Crear (DRAFT o PENDING según `emit`) |
| POST | `/api/work-orders/{id}/issue` | DRAFT → PENDING (emisión con validación de campos obligatorios) |
| POST | `/api/work-orders/{id}/start` | PENDING → IN_PROGRESS |
| PATCH | `/api/work-orders/{id}/complete` | IN_PROGRESS → COMPLETED (+ completion_notes, auto-calcula duración) |
| POST | `/api/work-orders/{id}/return` | COMPLETED → IN_PROGRESS (+ return_reason) |
| POST | `/api/work-orders/{id}/approve` | COMPLETED → APPROVED (+ approved_signature) |
| POST | `/api/work-orders/{id}/cancel` | Cualquier estado abierto → CANCELLED (+ cancellation_reason) |
| GET | `/api/work-orders/my` | OTs del trabajador actual (responsable o participante) |

### 4.1 Características de cada endpoint

- **issue**: Valida descripción, responsable y participantes (quiénes entran en la OT) antes de emitir. Los detalles de ejecución (fecha de ejecución, sección, horas, tipo) los completa la persona responsable después vía `/fulfill`.
- **fulfill** (PATCH `/{id}/fulfill`): La persona responsable completa los detalles restantes de la OT (fecha de ejecución, sección, hora inicio/término, horas manuales, tipo, LOTO, recursos, riesgos, observaciones, folio, vale, aprobado por). Re-popula el documento OT en Google con estos campos.
- **start**: Registra `started_at` y `started_by_user_id`
- **complete**: Registra `completed_at`, `completed_by_user_id`, calcula `actual_duration_minutes`
- **return**: Limpia snapshot de completado (evento preservado en audit log)
- **approve**: Registra `approved_at`, `approved_by_user_id`, `approved_signature`
- **cancel**: Requiere `cancellation_reason`
- **my**: Filtra por `responsible_user_id = user.id` O `user.id IN participants`

### 4.2 Concurrencia

Todos los endpoints de transición usan `SELECT ... FOR UPDATE` (`with_for_update()`) para prevenir condiciones de carrera.

### 4.3 Auditoría

Cada transición registra en `audit_log`: user_id, action, entity_type, entity_id, previous_data, new_data.

### 4.4 Archivo

- [work_orders.py](backend/app/api/routes/work_orders.py) — Rutas completas con state machine, permisos, sync Google, auditoría

---

## 5. SINCRONIZACIÓN GOOGLE

### 5.1 Mensual — cambios

- **APPROVED** → `"APROBADA"` en `MONTHLY_STATUS_MAP`
- **RESPONSABLE**: usa `responsible_user_id` → resuelve nombre. Si es NULL, celda vacía. NUNCA deriva de participants.
- **HORAS**: si `actual_duration_minutes` existe → usa `actual_duration_minutes / 60`; si no → `estimated_time` parseado.
- **DRAFT** no llega al mensual (`is_eligible_for_monthly`).

### 5.2 OT individual

- Se escribe en Google Drive al emitir (DRAFT → PENDING)
- Se actualiza en cada transición de estado

### 5.3 Archivos

- [monthly_mapping.py](backend/app/services/monthly_mapping.py) — `MONTHLY_STATUS_MAP` con APPROVED
- [google_drive.py](backend/app/services/google_drive.py) — `sync_to_monthly_sheet`, `populate_ot_fields`

---

## 6. ORQUESTACIÓN E2E

### 6.1 Patrones modernos implementados

| Patrón | Uso |
|--------|-----|
| `asynccontextmanager` | `create_cob_session()` — lifecycle de la sesión COB |
| `TaskGroup` | Validación concurrente de órdenes durante init |
| `ExceptionGroup` | Propagación de errores de validación (Python 3.11+) |
| Streaming pipeline | `async for event in session.run()` — eventos estructurados |
| `__slots__` + Exception hierarchy | `COBError → ValidationError, TransitionError, PermissionError` |

### 6.2 Eventos estructurados

```python
InitComplete(validated_orders=N, eligible_orders=M, duration_ms=X)
OrderProcessed(order_id, ot_number, previous_status, new_status, success, error)
PipelineComplete(total_orders, processed, succeeded, failed, skipped, errors, duration_ms)
```

### 6.3 Archivo

- [cob_orchestrator.py](backend/app/services/cob_orchestrator.py) — `COBSession`, `create_cob_session()`

---

## 7. MIGRACIÓN DE DATOS

### 7.1 Migración Alembic 0004

- Crea `work_order_participants` (M2M)
- Agrega 15 columnas nuevas a `work_orders` (todas nullable)
- Migra `participant_names` existentes a tabla M2M (mejor esfuerzo: parseo de nombres + match por `full_name`)
- Downgrade: elimina tabla y columnas

---

## 8. TESTS

### 8.1 Resumen

| Categoría | Tests | Estado |
|-----------|-------|--------|
| Auth | 7 | ✅ |
| Google sync failure | 2 | ✅ |
| Maintenance | 15 | ✅ |
| Work orders (CRUD) | 7 | ✅ |
| Monthly mapping | 8 | ✅ |
| State machine + Permisos | 20 | ✅ |
| Workflow (endpoints) | 23 | ✅ |
| COB Orchestrator | 8 | ✅ |
| OT fields write | 7 | ✅ |
| **TOTAL** | **137** | **✅ 137/137** |

### 8.2 Tests nuevos (48)

| Archivo | Tests | Cobre |
|---------|-------|-------|
| `test_wo_state_machine.py` | 20 | Transiciones, permisos矩阵, can_view con participants |
| `test_wo_workflow.py` | 23 | Issue, start, complete, return, approve, cancel, /my, monthly sync |
| `test_cob_orchestrator.py` | 8 | TaskGroup, asynccontextmanager, streaming, ExceptionGroup, rollback |

### 8.3 Archivos de test

- [test_wo_state_machine.py](backend/tests/test_wo_state_machine.py)
- [test_wo_workflow.py](backend/tests/test_wo_workflow.py)
- [test_cob_orchestrator.py](backend/tests/test_cob_orchestrator.py)

---

## 9. ARCHIVOS MODIFICADOS/CREADOS

### Modificados (9)
1. `backend/app/models/work_order.py` — 6 estados, 15 campos, 3 relaciones de usuario
2. `backend/app/models/user.py` — Relación `work_orders` M2M
3. `backend/app/models/audit_log.py` — 4 acciones nuevas
4. `backend/app/schemas/work_order.py` — Campos workflow en Create/Update/Response/List
5. `backend/app/api/routes/work_orders.py` — 8 endpoints nuevos + helpers
6. `backend/app/services/monthly_mapping.py` — APPROVED en status map
7. `backend/app/services/wo_permissions.py` — Matriz de permisos completa
8. `backend/tests/conftest.py` — `worker_jara` añadido
9. `backend/tests/test_work_orders.py` — Tests adaptados a permisos de ADMIN
10. `backend/tests/test_monthly_mapping.py` — APPROVED en status map test

### Creados (6)
1. `backend/app/models/work_order_participants.py` — Tabla M2M
2. `backend/app/services/wo_state_machine.py` — State machine centralizada
3. `backend/app/services/wo_permissions.py` — Funciones de permiso
4. `backend/app/services/cob_orchestrator.py` — Orquestación E2E
5. `backend/alembic/versions/0004_work_order_workflow.py` — Migración
6. `backend/tests/test_wo_state_machine.py` — Tests state machine + permisos
7. `backend/tests/test_wo_workflow.py` — Tests workflow endpoints
8. `backend/tests/test_cob_orchestrator.py` — Tests orquestador E2E

### NO modificados (respetados)
- `ot_mapping.py` — Sin cambios
- OAuth credentials — Sin cambios
- Datos existentes — Sin eliminación
- Git — Sin commit/push
- Producción — Sin despliegue

---

## 10. FLUJO COMPLETO (E2E)

```
1. Admin crea OT (emit=False)        → DRAFT
2. Admin edita campos obligatorios    → DRAFT (editado)
3. Admin emite (/issue)              → PENDING  + Google OT + mensual
4. Trabajador ve en /my              → PENDING (lectura)
5. Responsable inicia (/start)       → IN_PROGRESS + started_at
6. Responsable finaliza (/complete)  → COMPLETED + actual_duration + mensual FINALIZADO
7. Admin revisa
   → Aprueba (/approve)             → APPROVED + firma + mensual APROBADA
   → O Devuelve (/return)           → IN_PROGRESS + motivo
8. Flujo se repite hasta aprobación
```

---

## 11. KPIs PREPARADOS

- `is_planned` — % OTs planificadas vs reactivas
- `due_date` — % OTs entregadas a tiempo
- `actual_duration_minutes` — Tiempo real vs estimado
- `monthly_status_text("APPROVED")` → "APROBADA" para métricas de cierre

---

## 12. RESTRICCIONES CUMPLIDAS

| Restricción | Estado |
|-------------|--------|
| No romper nada existente | ✅ 89 tests existentes pasan |
| PostgreSQL source of truth | ✅ |
| Google Sheets = documentación | ✅ |
| No commit / push | ✅ |
| No desplegar a producción | ✅ |
| No cambiar OAuth | ✅ |
| No romper ot_mapping.py | ✅ |
| No borrar OT existentes | ✅ |
| No imprimir secretos | ✅ |
