# Plataforma de Mantención

Plataforma web **mobile-first** para el registro de mantención de equipos industriales. Reemplaza el llenado manual de planillas de Google Sheets con un formulario guiado (wizard) intuitivo, manteniendo la sincronización automática hacia Google Sheets como destino de datos.

> **Importante:** El proyecto **no reemplaza Google Sheets**. Google Sheets sigue siendo la fuente hacia donde se escriben los registros, pero los trabajadores ya no llenan la planilla a mano: usan esta plataforma.

---

## 1. Qué hace el proyecto

- **Autenticación** de usuarios (roles: ADMIN, SUPERVISOR, WORKER).
- **Registro de mantenciones** mediante un wizard de 5 pasos (ubicación, trabajo, participantes, detalles, confirmación).
- **Dictado por voz** (Web Speech API) para describir el trabajo realizado.
- **Selectores dependientes** Área → Sección → Equipo (datos desde backend, no hardcodeados).
- **Selección múltiple de participantes** (relación many-to-many).
- **Cálculo automático de duración** y tipo preventivo/correctivo.
- **Auditoría** de quién crea o modifica cada registro (backend siempre).
- **Sincronización a Google Sheets** con estados (PENDING / SYNCED / FAILED) y reintento manual.
- **Historial con filtros** (fecha, área, tipo).

## 2. Arquitectura

```
maintenance-platform/
├── frontend/          # Next.js + TypeScript + Tailwind (SPA, mobile-first)
├── backend/           # FastAPI + SQLAlchemy 2.x + Alembic + Pydantic
├── docker-compose.yml # PostgreSQL de desarrollo
├── README.md
└── .gitignore
```

- **Frontend (Next.js):** App Router, componentes pequeños, lógica de negocio en `lib/`.
- **Backend (FastAPI):** routers delgados → services con la lógica de negocio → repositorios/modelos.
- **Integración Google:** **exclusivamente desde FastAPI** (`backend/app/services/google_sheets.py`). Nunca se exponen credenciales en Next.js.
- **Base de datos:** PostgreSQL. Los `JSONB` se usan en `audit_logs`.

## 3. Requisitos

- Python 3.11+
- Node.js 18+ (Next.js 15 requiere Node 18.18+)
- Docker (para PostgreSQL de desarrollo)
- (Opcional) una Service Account de Google Cloud para la sincronización a Sheets

## 4. Instalación

Clona o copia el proyecto y sigue los pasos por componente:

### 4.1 Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -e ".[dev]"
```

### 4.2 Frontend

```bash
cd frontend
npm install
```

## 5. Frontend

### 5.1 Variables de entorno

```bash
cd frontend
cp .env.example .env.local
```

Contenido:

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 5.2 Iniciar frontend

```bash
cd frontend
npm run dev
```

Disponible en `http://localhost:3000`.

## 6. Backend

### 6.1 Variables de entorno

```bash
cd backend
cp .env.example .env
```

Ajusta `DATABASE_URL`, `SECRET_KEY` (usa una clave fuerte en producción) y `CORS_ORIGINS`.

### 6.2 Iniciar backend

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Documentación interactiva de la API: `http://localhost:8000/docs`.

## 7. PostgreSQL

Levanta la base de datos de desarrollo con Docker:

```bash
docker compose up -d postgres
```

- Host: `localhost`
- Puerto: `5433` (se usa `5433` para evitar conflicto con el PostgreSQL nativo de tu equipo en el `5432`)
- Usuario: `maintenance_user`
- Password: `maintenance_pass`
- Base: `maintenance_db`

## 8. Migraciones (Alembic)

```bash
cd backend
# Aplicar migraciones a la base
alembic upgrade head

# (Para futuros cambios de esquema)
alembic revision --autogenerate -m "descripcion"
alembic upgrade head
```

## 9. Seed de desarrollo

Crea el admin, supervisor, trabajadores de ejemplo, el área Malta / Germinación / Cajón N°1 y N°2, y un registro de ejemplo.

```bash
cd backend
python seed.py
```

**Credenciales de desarrollo (NO usar en producción):**

| Rol        | Nombre       | Email                         | Contraseña   |
|------------|-------------|-------------------------------|--------------|
| ADMIN      | Administrador | admin@mantencion.com          | Admin123!    |
| SUPERVISOR | Supervisor   | supervisor@mantencion.com     | Super123!    |
| WORKER     | Ortiz        | ortiz@mantencion.com          | Worker123!   |
| WORKER     | Valdés       | valdes@mantencion.com         | Worker123!   |
| WORKER     | Fabres       | fabres@mantencion.com         | Worker123!   |
| WORKER     | Jara         | jara@mantencion.com           | Worker123!   |
| WORKER     | Salazar      | salazar@mantencion.com        | Worker123!   |
| WORKER     | Millar       | millar@mantencion.com         | Worker123!   |
| WORKER     | Juan Silva   | juansilva@mantencion.com      | Worker123!   |
| WORKER     | Inostroza    | inostroza@mantencion.com      | Worker123!   |
| WORKER     | Caniullan    | caniullan@mantencion.com      | Worker123!   |
| WORKER     | Contreras    | contreras@mantencion.com      | Worker123!   |

## 10. Variables de entorno (Backend)

| Variable                       | Descripción                                                       |
|--------------------------------|-------------------------------------------------------------------|
| `DATABASE_URL`                 | Cadena de conexión asyncpg de PostgreSQL                          |
| `SECRET_KEY`                   | Clave secreta para firmar JWT (usa valor fuerte)                  |
| `ALGORITHM`                    | Algoritmo JWT (HS256)                                             |
| `ACCESS_TOKEN_EXPIRE_MINUTES`  | Tiempo de vida del token (480 = 8 h)                              |
| `CORS_ORIGINS`                 | JSON array de orígenes permitidos                                 |
| `GOOGLE_SERVICE_ACCOUNT_FILE`  | Ruta (relativa a `backend/`) al JSON de la Service Account (preferida) |
| `GOOGLE_SERVICE_ACCOUNT_JSON`  | El JSON de la Service Account inline como string (fallback)      |
| `GOOGLE_SPREADSHEET_ID`        | ID del Spreadsheet destino                                        |
| `GOOGLE_SHEET_NAME`            | Nombre de la hoja dentro del spreadsheet (ej: `ENERO 2026`)       |
| `GOOGLE_SIGNATURES_FOLDER_ID`  | ID de la carpeta Drive para firmas manuscritas (requiere OAuth)  |
| `GOOGLE_SIGNATURES_APPS_SCRIPT_URL` | URL del Web App que inserta la firma como imagen real         |
| `GOOGLE_SIGNATURES_APPS_SCRIPT_SECRET` | Clave compartida del Web App, almacenada en Script Properties |

> La plataforma **funciona sin Google configurado**: los registros se guardan localmente con estado `PENDING`. Activa Google solo cuando tengas las credenciales.

Para activar firmas, crea una carpeta exclusiva en Google Drive, comparte su ID en
`GOOGLE_SIGNATURES_FOLDER_ID` dentro de `backend/.env` y asegúrate de que las
credenciales OAuth tengan permiso de escritura. Cada persona carga su imagen en
**Mi firma** antes de emitir o aprobar una OT.

### Firma insertada como imagen real

Para que la OT contenga una imagen real (sin `IMAGE()` ni permisos por cada
planilla), despliega una sola vez el proyecto de
`backend/apps_script/` en la misma cuenta que posee las OTs:

1. Abre [Apps Script](https://script.google.com), crea un proyecto y pega
   `Code.gs` y `appsscript.json` desde esa carpeta.
2. En **Project Settings â†’ Script properties**, crea
   `SIGNATURE_WEBHOOK_SECRET` con una clave aleatoria larga.
3. En **Deploy â†’ New deployment â†’ Web app**, selecciona **Execute as: Me**
   y acceso **Anyone**. El endpoint no queda abierto funcionalmente: rechaza
   toda solicitud que no incluya la clave guardada en Script Properties.
4. Copia la URL de despliegue y registra en `backend/.env` la URL y la misma
   clave con `GOOGLE_SIGNATURES_APPS_SCRIPT_URL` y
   `GOOGLE_SIGNATURES_APPS_SCRIPT_SECRET`.

El script lee el archivo de firma de Drive como blob y lo inserta sobre la
grilla en B31 o E31. Al re-sincronizar, reemplaza únicamente la imagen de ese
rol, sin dejar fórmulas ni enlaces visibles.

## 11. Cómo iniciar (todo junto)

```bash
# Terminal 1: PostgreSQL
docker compose up -d postgres

# Terminal 2: backend
cd backend
.venv\Scripts\activate        # (Windows)
alembic upgrade head
python seed.py
uvicorn app.main:app --reload --port 8000

# Terminal 3: frontend
cd frontend
npm run dev
```

Abre `http://localhost:3000`, inicia sesión con un WORKER (ver seed) y registra una mantención.

## 12. Tests

```bash
cd backend
pytest -v
```

Los tests cubren: login, usuario inactivo, permisos WORKER/SUPERVISOR, creación de mantenimiento, jerarquía área/sección/equipo, tipos preventivo/correctivo, duración, participantes, auditoría, mapping de Google Sheets, y que un fallo de Google **no** elimina el registro local. **Google Sheets está mockeado** — no se hacen llamadas reales.

## 13. Google Cloud

Para habilitar la sincronización automática a Google Sheets:

### 13.1 Habilitar Google Sheets API

1. Ve a [Google Cloud Console](https://console.cloud.google.com).
2. Crea o selecciona un proyecto.
3. Ve a **APIs & Services → Library**.
4. Busca **Google Sheets API** y haz clic en **Enable**.
   - (Opcional, para listar/leer el archivo: habilita también **Google Drive API**).

### 13.2 Crear Service Account

1. Ve a **APIs & Services → Credentials → Create Credentials → Service Account**.
2. Ponle un nombre (ej: `mantencion-sync`), asigna un rol (puede ser básico) y crea.
3. En la lista de Service Accounts, selecciona la creada.

### 13.3 Generar credenciales (JSON)

1. Dentro de la Service Account, ve a la pestaña **Keys → Add Key → Create new key**.
2. Elige formato **JSON** y descarga el archivo.
3. Guarda el archivo en `backend/credentials/google-service-account.json` (el directorio `backend/credentials/` está excluido por `.gitignore`, así **no** se sube al repo) y apunta `GOOGLE_SERVICE_ACCOUNT_FILE=credentials/google-service-account.json`.
   - Alternativa: copia el contenido como string en `GOOGLE_SERVICE_ACCOUNT_JSON`. Se prefiere el archivo; el JSON inline es el fallback. El `private_key` con saltos de línea reales se maneja automáticamente.

### 13.4 Compartir Google Sheet con la Service Account

1. Copia el **email** de la Service Account (termina en `@PROJECT_ID.iam.gserviceaccount.com`).
2. Abre tu Google Sheet (el destino).
3. Botón **Compartir / Share** → agrega el email de la Service Account con permiso de **Editor**.
4. Los empleados **no** necesitan acceso directo: solo la Service Account edita.

### 13.5 Obtener Spreadsheet ID

El Spreadsheet ID está en la URL del documento:

```
https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit
```

Copia `<SPREADSHEET_ID>` en `GOOGLE_SPREADSHEET_ID`.

### 13.6 Configurar Sheet Name

Verifica el **nombre exacto** de la hoja (pestaña inferior del spreadsheet, ej: `ENERO 2026`) y ajústalo en `GOOGLE_SHEET_NAME`. El nombre debe coincidir al pie de la letra.

> Asegúrate de que la hoja tenga las columnas del mapping (`FECHA`, `AREA`, `SECCION`, `EQUIPO`, `TRABAJO`, `ORTIZ`, `VALDES`, `FABRES`, `SALAZAR`, `MILLAR`, `JUAN SILVA`, `INOSTROZA`, `CANIULLAN`, `CONTRERAS`, `PREVENTIVO`, `CORRECTIVO`, `HORAS`). El mapping está centralizado en `backend/app/services/google_sheets.py`.

### 13.6.1 Verificar la integración (ADMIN)

Hay un endpoint **de solo lectura** (solo ADMIN) que comprueba: configuración cargada, credenciales válidas, acceso al spreadsheet y existencia de la hoja — sin escribir nada ni exponer credenciales:

```bash
curl -H "Authorization: Bearer <token-admin>" \
  http://localhost:8000/api/admin/integrations/google-sheets/status
# => {"configured":true,"credentials_valid":true,"spreadsheet_access":true,"sheet_found":true,"error":null}
```

### 13.7 Cómo verificar la sincronización

1. Crea una mantención desde la app.
2. En el dashboard/historial observa el estado de sincronización:
   - `✓ Sincronizado` → se escribió en Google Sheets.
   - `⏳ Pendiente` → no configurado o aún no procesado.
   - `⚠ Error` → falló; revisa los logs y `sheet_sync_error`.
3. Como SUPERVISOR/ADMIN, en la página de detalle puedes **Reintentar** la sincronización de un registro fallido.
4. Abre el Google Sheet y verifica que la fila con la fecha/equipo/trabajo fue agregada.

---

## Roles y permisos (SIEMPRE validados en backend)

| Acción                      | WORKER | SUPERVISOR | ADMIN |
|-----------------------------|--------|------------|-------|
| Registrar mantención        | ✅     | ✅         | ✅    |
| Ver sus propios registros   | ✅     | ✅         | ✅    |
| Ver todos los registros     | ❌     | ✅         | ✅    |
| Editar registros            | ❌     | ✅         | ✅    |
| Consultar auditoría         | ❌     | ✅         | ✅    |
| Reintentar sincronización   | ❌     | ✅         | ✅    |
| Administrar usuarios        | ❌     | ❌         | ✅    |
| Administrar áreas/secciones/equipos | ❌    | ❌         | ✅    |

El rol se lee del token JWT en el backend; el frontend **nunca** envía el rol como fuente de verdad.

## Modelo de datos (resumen)

- **User** (id, full_name, email, password_hash, role, is_active, ...)
- **Area** → **Section** → **Equipment** (jerarquía)
- **MaintenanceRecord** (date, area, section, equipment, description, maintenance_type, start_time, end_time, duration_minutes, created_by, sheet_sync_status/error/at)
- **maintenance_participants** (many-to-many Maintenance ⇄ User)
- **AuditLog** (user, action, entity_type, entity_id, previous_data JSONB, new_data JSONB, created_at)

## Notas de seguridad

- Contraseñas con **bcrypt** (nunca texto plano).
- Autenticación con **JWT** (firma HMAC).
- **RBAC** aplicado en cada endpoint.
- **CORS** configurable (no `*`).
- **Secrets** solo en variables de entorno.
- **Nunca** se exponen credenciales de Google al frontend.
- La identidad de quien crea/modifica viene del **token autenticado**, nunca de campos del frontend.
