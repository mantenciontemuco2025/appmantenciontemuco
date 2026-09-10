# Guia de instalacion para el cliente

Este documento explica como dejar la Plataforma de Mantencion funcionando con
la cuenta Google, el Drive y los usuarios del cliente.

La cuenta del cliente debe ser la propietaria del proyecto de Google Cloud,
las carpetas, las plantillas, los registros y el proyecto de Apps Script. No
se deben usar credenciales personales del desarrollador en produccion.

## 1. Lo que debe tener el cliente

- Una cuenta Google corporativa con Drive, Sheets y Apps Script.
- Un servidor o equipo que permanezca encendido para el backend y PostgreSQL,
  o un servicio de hosting/VPS.
- Un dominio para la aplicacion.
- HTTPS activo en el dominio de la aplicacion y en el backend.
- Los nombres reales de las areas, equipos y personas de la planta.
- Una persona ADMIN responsable de usuarios, areas y OTs.

La integracion de escritura usa OAuth con la cuenta Google del cliente. Una
Service Account por si sola no permite las operaciones de escritura usadas por
esta version: copiar plantillas, crear carpetas y actualizar Sheets.

## 2. Estructura de Google Drive

En el Drive de la cuenta del cliente crea esta estructura:

```text
MANTENCION/
├── PLANTILLAS/
│   ├── PLANTILLA_OT                 # Google Sheets de una OT
│   └── REGISTRO_MENSUAL_PLANTILLA   # plantilla anual con 12 pestanas
├── ORDENES DE TRABAJO/              # destino de Anio/MES/OT
├── REGISTRO MENSUAL/                # destino de los registros anuales
└── FIRMAS/                          # imagenes de firma de usuarios
```

La cuenta que autorice OAuth debe ser propietaria o tener permiso **Editor**
en todos estos elementos.

Para obtener un ID, abre el archivo o carpeta y copia el valor de la URL:

```text
https://drive.google.com/drive/folders/ABC123
ID = ABC123
```

### Si la cuenta del cliente es personal (`@gmail.com`)

Tambien funciona con una cuenta Gmail personal. En ese caso:

1. En la pantalla de consentimiento OAuth selecciona **Externo**. Una cuenta
   personal no puede usar la opcion **Interno** de Google Workspace.
2. Agrega la cuenta Gmail del cliente en **Usuarios de prueba**.
3. Autoriza OAuth iniciando sesion exactamente con esa cuenta.
4. Usa esa misma cuenta como propietaria o editora de las carpetas, plantillas
   y registros de Drive.

Mientras la aplicacion OAuth permanezca en estado **Testing**, Google limita el
acceso a los usuarios de prueba y el `refresh_token` emitido para los permisos
de Drive/Sheets puede vencer despues de 7 dias. Para una instalacion que debe
funcionar permanentemente, publica la pantalla de consentimiento en **Production**
y completa la verificacion que Google solicite para esos permisos. Si el token
vence, hay que volver a ejecutar `python scripts/google_oauth_setup.py` y
reemplazar `GOOGLE_OAUTH_REFRESH_TOKEN`.

Para una prueba local o una demostracion, el modo **Testing** es suficiente.
Para uso diario del cliente, se recomienda publicar la aplicacion OAuth antes
de la entrega.

### Costos

La configuracion OAuth, la publicacion de la pantalla de consentimiento y el
uso normal de Google Sheets API no tienen un cobro por cada OT. Google aplica
cuotas de uso y Apps Script tiene limites diarios; para el volumen normal de
esta plataforma no deberian ser un problema.

Los costos que si deben considerarse son:

- Hosting o VPS donde se ejecuten frontend, backend y PostgreSQL.
- Dominio y, si corresponde, el servicio de correo del dominio.
- Almacenamiento adicional de Google Drive si la cuenta Gmail supera sus 15 GB
  gratuitos compartidos entre Drive, Gmail y Google Fotos.
- Cualquier servicio externo contratado por el cliente.

En una prueba local se puede trabajar sin pagar hosting, usando Docker y el
computador local. En produccion el servidor debe permanecer encendido. Si
Google solicita asociar una cuenta de facturacion al proyecto Cloud, no se
deben habilitar servicios adicionales sin necesitarlos y se deben configurar
presupuestos y alertas.

## 3. Plantilla individual de OT

1. Copia la plantilla de OT al Drive del cliente.
2. Conserva la pestana esperada por la integracion: `PLANTILLA_OT`.
3. No insertes ni elimines filas o columnas sin actualizar el mapping del
   proyecto.
4. La plantilla auditada usa estas posiciones principales:

| Dato | Posicion |
|---|---|
| Numero OT | `G2` |
| Area | `C6` |
| Seccion | `C7` |
| Equipo | `C8` |
| Solicitado por y firma | `B31:D33` |
| Realizado por y firma | `E31:G33` |
| Estado operativo | `B36:G36` |

La aplicacion conserva el formato de la plantilla y escribe los datos en esas
posiciones. El estado de una OT se registra asi:

- `PENDING`: `PENDIENTE`.
- `IN_PROGRESS`: `EN PROCESO`.
- `COMPLETED`: `FINALIZADO`.
- `APPROVED`: `ESTADO: APROBADA`.
- `CANCELLED`: `ESTADO: CANCELADA`.

## 4. Registro mensual

La plantilla anual debe contener las 12 pestanas mensuales y una fila de
encabezados con los nombres reales de las columnas. Mantener especialmente:

- `FECHA`.
- `N° OT`.
- `AREA`.
- `SECCION`.
- `EQUIPO`.
- `TRABAJO`.
- Las columnas con nombres de los trabajadores.
- `HORAS`.
- `ESTADO` despues de `HORAS`.

La aplicacion busca las columnas por el texto del encabezado, no solo por una
letra fija. En el registro mensual los estados se escriben como:

| Estado interno | Texto en registro mensual |
|---|---|
| `PENDING` | `PENDIENTE` |
| `IN_PROGRESS` | `EN PROCESO` |
| `COMPLETED` | `FINALIZADO` |
| `APPROVED` | `APROBADA` |
| `CANCELLED` | `CANCELADA` |

Los borradores (`DRAFT`) no se agregan al registro mensual hasta que el ADMIN
los emite.

## 5. Crear el proyecto de Google Cloud

En [Google Cloud Console](https://console.cloud.google.com/):

1. Crea un proyecto exclusivo del cliente, por ejemplo
   `mantencion-cliente`.
2. En **APIs y servicios > Biblioteca**, habilita:
   - Google Drive API.
   - Google Sheets API.
3. En **Pantalla de consentimiento OAuth**, configura:
   - Nombre visible de la aplicacion.
   - Correo de soporte.
   - Correo de contacto del desarrollador o administrador.
4. Si usan Google Workspace y todos pertenecen al mismo dominio, seleccionar
   **Interno**. Si se selecciona **Externo**, agregar la cuenta del cliente
   como usuario de prueba mientras la aplicacion no este publicada.
5. En **Credenciales > Crear credenciales > ID de cliente OAuth**, crear un
   cliente de tipo **Aplicacion de escritorio**.
6. Descargar el JSON y guardarlo en:

   `backend/credentials/google-oauth-client.json`

Ese archivo es secreto y no debe subirse al repositorio.

## 6. Autorizar Drive y Sheets con la cuenta del cliente

Desde una terminal, dentro de la carpeta `backend`:

```bash
python scripts/google_oauth_setup.py
```

El script abrira un navegador. Iniciar sesion con la cuenta Google del cliente
y aceptar los permisos de Drive y Sheets. Al terminar imprimira tres valores.

Pegarlos en `backend/.env`:

```env
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_CLIENT_SECRET=...
GOOGLE_OAUTH_REFRESH_TOKEN=...
```

El `refresh_token` representa la cuenta del cliente. Si se revoca el permiso,
se cambia la politica de seguridad o se elimina la credencial OAuth, repetir
este paso y reiniciar el backend.

## 7. Configurar los ID de Drive en `backend/.env`

Completar estas variables con los ID del Drive del cliente:

```env
GOOGLE_OT_TEMPLATE_FILE_ID=ID_DE_PLANTILLA_OT
GOOGLE_OT_ROOT_FOLDER_ID=ID_DE_ORDENES_DE_TRABAJO
GOOGLE_SIGNATURES_FOLDER_ID=ID_DE_FIRMAS

GOOGLE_MONTHLY_TEMPLATE_FILE_ID=ID_DE_PLANTILLA_MENSUAL
GOOGLE_MONTHLY_ROOT_FOLDER_ID=ID_DE_REGISTRO_MENSUAL
GOOGLE_MONTHLY_SPREADSHEET_ID=
```

La aplicacion creara automaticamente las carpetas de ano y mes dentro de
`GOOGLE_OT_ROOT_FOLDER_ID` y los registros anuales dentro de
`GOOGLE_MONTHLY_ROOT_FOLDER_ID`.

Las variables antiguas `GOOGLE_SPREADSHEET_ID` y `GOOGLE_SHEET_NAME` se pueden
mantener por compatibilidad, pero la configuracion anual recomendada usa las
variables `GOOGLE_MONTHLY_*`.

## 8. Configurar Apps Script para las firmas

Apps Script inserta las firmas como imagen dentro del documento de cada OT.

1. Abrir [Apps Script](https://script.google.com/) con la cuenta del cliente.
2. Crear un proyecto nuevo.
3. Copiar el contenido de `backend/apps_script/Code.gs`.
4. En **Configuracion del proyecto > Propiedades del script**, crear:

   ```text
   SIGNATURE_WEBHOOK_SECRET = una-clave-aleatoria-larga
   ```

5. Ir a **Implementar > Nueva implementacion > Aplicacion web**.
6. Configurar:
   - Ejecutar como: **Yo**, la cuenta del cliente.
   - Quien tiene acceso: **Cualquiera**.
7. Copiar la URL terminada en `/exec`.
8. Registrar en `backend/.env`:

```env
GOOGLE_SIGNATURES_APPS_SCRIPT_URL=https://script.google.com/macros/s/ID/exec
GOOGLE_SIGNATURES_APPS_SCRIPT_SECRET=la-misma-clave-del-script
```

El endpoint puede ser accesible para recibir la llamada del backend, pero sin
el secreto correcto rechaza la solicitud. No publicar el secreto.

## 9. Variables completas del backend

Crear `backend/.env` usando `backend/.env.example` como base:

```env
# PostgreSQL
DATABASE_URL=postgresql+asyncpg://USUARIO:CLAVE@HOST:5432/maintenance_db

# Seguridad de sesiones
SECRET_KEY=GENERAR_UNA_CLAVE_LARGA_Y_ALEATORIA
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
REFRESH_TOKEN_EXPIRE_DAYS=30
CORS_ORIGINS=["https://app.cliente.cl"]

# OAuth Google de la cuenta del cliente
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_CLIENT_SECRET=...
GOOGLE_OAUTH_REFRESH_TOKEN=...

# OT individual
GOOGLE_OT_TEMPLATE_FILE_ID=...
GOOGLE_OT_ROOT_FOLDER_ID=...

# Firmas
GOOGLE_SIGNATURES_FOLDER_ID=...
GOOGLE_SIGNATURES_APPS_SCRIPT_URL=...
GOOGLE_SIGNATURES_APPS_SCRIPT_SECRET=...

# Registro mensual anual
GOOGLE_MONTHLY_TEMPLATE_FILE_ID=...
GOOGLE_MONTHLY_ROOT_FOLDER_ID=...
GOOGLE_MONTHLY_SPREADSHEET_ID=

# Notificaciones push
VAPID_PUBLIC_KEY=...
VAPID_PRIVATE_KEY=...
VAPID_SUBJECT=mailto:soporte@cliente.cl

APP_ENV=production
```

No guardar contrasenas, tokens ni claves reales en este README.

## 10. Configurar notificaciones push

Generar una pareja VAPID para este cliente:

```bash
npx web-push generate-vapid-keys
```

Copiar la clave publica en `VAPID_PUBLIC_KEY` y la privada en
`VAPID_PRIVATE_KEY`. La clave privada solo debe existir en el backend.

Para que funcione en los telefonos:

1. La app debe abrirse por HTTPS.
2. Cada usuario debe iniciar sesion al menos una vez en su telefono.
3. Cada usuario debe aceptar el permiso de notificaciones.
4. En iPhone/iPad, instalar la PWA en la pantalla de inicio si el navegador
   lo solicita para las notificaciones web.
5. No borrar los datos del navegador ni revocar el permiso.

La sesion se mantiene por varios dias mediante refresh token. La notificacion
puede llegar con la app cerrada si el sistema operativo conserva la suscripcion
push y el permiso.

## 11. Instalacion local de prueba

Requisitos: Python 3.11 o superior, Node.js 18.18 o superior, Docker y acceso
a Internet desde el backend.

```bash
# Terminal 1: base de datos de desarrollo
docker compose up -d postgres

# Terminal 2: backend
cd backend
python -m venv .venv

# Windows
.venv\\Scripts\\activate

# macOS/Linux
# source .venv/bin/activate

pip install -e ".[dev]"
alembic upgrade head
python seed.py                 # solo desarrollo
uvicorn app.main:app --reload --port 8000

# Terminal 3: frontend
cd frontend
npm install
copy .env.example .env.local   # Windows
# cp .env.example .env.local   # macOS/Linux
npm run dev
```

En `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Abrir `http://localhost:3000`.

`seed.py` crea usuarios de prueba y no debe ejecutarse en produccion.

## 12. Instalacion en produccion

1. Crear una base PostgreSQL independiente y con respaldos automaticos.
2. Instalar el proyecto en un servidor o servicio de hosting.
3. Configurar todos los valores de `backend/.env` en el servidor.
4. Ejecutar las migraciones:

   ```bash
   cd backend
   alembic upgrade head
   ```

5. No ejecutar `seed.py` en produccion.
6. Crear usuarios reales desde el panel ADMIN.
7. Compilar y ejecutar el frontend:

   ```bash
   cd frontend
   npm install
   npm run build
   npm start
   ```

8. Ejecutar el backend como servicio administrado, contenedor o supervisor de
   procesos. No depender de una terminal abierta.
9. Publicar frontend y backend detras de HTTPS.
10. Configurar el frontend con:

    ```env
    NEXT_PUBLIC_API_URL=https://api.cliente.cl
    ```

11. Configurar el backend con el origen exacto:

    ```env
    CORS_ORIGINS=["https://app.cliente.cl"]
    ```

12. Comprobar:

    ```text
    https://api.cliente.cl/health
    ```

    Debe responder `{"status":"ok"}`.

13. Desde una cuenta ADMIN comprobar el diagnostico Google:

    ```text
    GET /api/admin/integrations/google-sheets/status
    ```

El servidor debe tener salida a Internet para acceder a Google y enviar las
notificaciones push.

## 13. Configuracion inicial dentro de la app

Desde el usuario ADMIN:

1. Cambiar la contrasena inicial.
2. Crear las areas reales de la planta.
3. Crear las secciones y equipos de cada area.
4. Crear los trabajadores y actualizar sus nombres.
5. Crear los supervisores.
6. Asignar una o mas areas a cada supervisor.
7. Cada trabajador, supervisor y administrador debe cargar su firma en
   **Mi perfil > Mi firma**.
8. Confirmar que cada telefono permita notificaciones.
9. Desactivar o eliminar los usuarios de ejemplo.

## 14. Flujo que debe probar el cliente

1. El supervisor crea y envia una solicitud desde un area asignada.
2. La solicitud queda como borrador pendiente de revision del ADMIN.
3. El ADMIN recibe la notificacion, revisa y asigna responsable y
   participantes.
4. El ADMIN acepta/emite la OT.
5. El responsable recibe la notificacion, inicia la OT y completa los detalles.
6. El responsable inicia y finaliza el trabajo; su nombre y firma quedan en
   `REALIZADO POR`.
7. El ADMIN recibe la notificacion de OT finalizada y aprueba el cierre.
8. El nombre y firma del supervisor permanecen en `SOLICITADO POR`.
9. La OT aparece en la carpeta de Drive y en el registro mensual.
10. El estado de la OT se actualiza en la aplicacion, documento individual y
    registro mensual.

## 15. Checklist de entrega

- [ ] El cliente es propietario del proyecto Google Cloud.
- [ ] El cliente es propietario o editor de las carpetas y plantillas.
- [ ] Drive API y Sheets API estan habilitadas.
- [ ] OAuth fue autorizado con la cuenta del cliente.
- [ ] Los cinco ID de Drive fueron configurados.
- [ ] Apps Script esta desplegado como aplicacion web.
- [ ] El secreto de Apps Script coincide con `backend/.env`.
- [ ] La plantilla individual conserva sus posiciones y pestana.
- [ ] El registro mensual tiene las 12 pestanas y `ESTADO`.
- [ ] VAPID esta configurado y las claves no estan expuestas.
- [ ] La aplicacion abre por HTTPS.
- [ ] `CORS_ORIGINS` contiene solo el dominio real.
- [ ] PostgreSQL tiene respaldo y procedimiento de restauracion.
- [ ] Se cambiaron las contrasenas de prueba.
- [ ] Se probaron los tres roles: ADMIN, SUPERVISOR y WORKER.
- [ ] Se probo una notificacion en telefono.
- [ ] Se probo una falla de Google y luego el boton **Reintentar**.

## 16. Seguridad y mantenimiento

- No subir `backend/.env` al repositorio.
- No subir `backend/credentials/` al repositorio.
- No enviar el JSON OAuth, el refresh token ni la clave VAPID por chat.
- Usar una `SECRET_KEY` distinta para desarrollo y produccion.
- Limitar PostgreSQL al servidor de la aplicacion.
- Mantener HTTPS vigente.
- Revisar periodicamente los logs del backend y la cola de sincronizacion.
- Respaldar PostgreSQL diariamente.
- Probar la restauracion del respaldo periodicamente.
- Si Google falla, la OT queda guardada localmente y su sincronizacion queda
  marcada como fallida para poder reintentarse.
- Si se revoca OAuth, volver a autorizar con la cuenta del cliente y reiniciar
  el backend.

## 17. Informacion que debe conservar el cliente

El cliente debe guardar en un lugar seguro:

- Acceso de administrador de Google Cloud.
- Acceso de propietario de Drive.
- URL y proyecto de Apps Script.
- El secreto de Apps Script.
- El `refresh_token` OAuth.
- La clave privada VAPID.
- La contrasena de PostgreSQL o acceso al servicio administrado.
- El dominio y la cuenta del proveedor de hosting.

El desarrollador puede ayudar a instalar y mantener el sistema, pero el
cliente debe conservar el control de las cuentas y secretos principales.

## 18. Despliegue recomendado: OpenCloud + Vercel

La arquitectura recomendada es:

```text
Telefono/PC
    |
    v
Vercel: frontend Next.js (https://app.cliente.cl)
    |
    v
OpenCloud VPS: FastAPI + PostgreSQL + workers (https://api.cliente.cl)
    |
    v
Google Drive / Sheets / Apps Script
```

### 18.1 Contratar y preparar OpenCloud

OpenCloud ofrece VPS Linux con acceso por consola, IP publica, panel y
escalamiento. Para esta aplicacion:

- 2 GB RAM / 1 vCPU: minimo razonable para una prueba o pocos usuarios.
- 4 GB RAM / 2 vCPU: recomendado para produccion con PostgreSQL, backend y
  sincronizaciones trabajando al mismo tiempo.
- Elegir Ubuntu LTS o Debian estable.
- Contratar backup del VPS o implementar un backup externo de PostgreSQL.

El VPS de OpenCloud es no administrado: la instalacion, actualizaciones,
firewall, Docker y respaldos quedan a cargo del cliente o del administrador
tecnico.

Al contratar solicitar o confirmar:

- IP publica fija.
- Usuario SSH y acceso root/sudo.
- Sistema operativo Linux.
- Puertos 22, 80 y 443 disponibles.
- Posibilidad de configurar DNS y certificados HTTPS.

### 18.2 Preparar el VPS

En el VPS se debe instalar y configurar:

1. Docker y Docker Compose.
2. Git.
3. Un reverse proxy como Caddy o Nginx.
4. Firewall: permitir solo SSH, HTTP y HTTPS; PostgreSQL no debe quedar
   expuesto publicamente.
5. El codigo de la aplicacion.
6. PostgreSQL persistente y respaldos.

El `docker-compose.yml` incluido actualmente es solo para PostgreSQL de
desarrollo. Antes de produccion hay que agregar una composicion de produccion
con backend, PostgreSQL, volumen persistente, variables desde `.env` y
reinicio automatico. Tambien se debe crear el `Dockerfile` del backend o
instalarlo mediante un servicio Python administrado.

### 18.3 Dominios y DNS

Usar, por ejemplo:

```text
app.cliente.cl  -> frontend en Vercel
api.cliente.cl  -> IP publica del VPS OpenCloud
```

En el proveedor del dominio:

- Crear un registro `A` para `api` apuntando a la IP del VPS.
- Configurar el dominio `app` en Vercel y crear el `CNAME` que Vercel indique.
- No cambiar registros MX si el dominio usa correo.

El backend debe quedar publicado por `https://api.cliente.cl`, nunca por una
IP sin HTTPS. El frontend debe usar `https://app.cliente.cl`.

### 18.4 Configurar HTTPS en el backend

El reverse proxy recibe HTTPS y deriva internamente hacia FastAPI, por ejemplo:

```text
https://api.cliente.cl  ->  http://127.0.0.1:8000
```

El certificado debe renovarse automaticamente. Probar:

```text
https://api.cliente.cl/health
```

Debe responder:

```json
{"status":"ok"}
```

### 18.5 Publicar el frontend en Vercel

1. Subir el repositorio a GitHub, GitLab o Bitbucket sin secretos.
2. En Vercel seleccionar **Add New Project** e importar el repositorio.
3. Configurar como directorio raiz: `frontend`.
4. Usar framework: **Next.js**.
5. Usar build command: `npm run build`.
6. En **Settings > Environment Variables**, agregar para Production:

   ```env
   NEXT_PUBLIC_API_URL=https://api.cliente.cl
   ```

7. Agregar `app.cliente.cl` en **Settings > Domains**.
8. Crear en el proveedor DNS el registro que Vercel indique.
9. Esperar la validacion DNS y el certificado HTTPS.
10. Ejecutar un nuevo deploy despues de guardar la variable de entorno.

Vercel crea el certificado HTTPS automaticamente despues de que el DNS queda
validado. Los valores de `NEXT_PUBLIC_*` quedan incluidos en el frontend, por
lo que solo debe contener la URL publica de la API; nunca poner secretos ahi.

### 18.6 Conectar Vercel con el backend

En el `.env` del backend del VPS configurar el origen exacto de Vercel:

```env
CORS_ORIGINS=["https://app.cliente.cl"]
```

No dejar `http://localhost:3000` en produccion. Si se usa un ambiente Preview,
se puede agregar temporalmente su URL de Vercel, pero no se deben aceptar
origenes abiertos como `*`.

La autorizacion OAuth de Google se realiza inicialmente con
`python scripts/google_oauth_setup.py` usando la cuenta del cliente. Luego se
copian los valores OAuth al `.env` del VPS. El frontend en Vercel nunca recibe
el `refresh_token` ni las credenciales de Google.

### 18.7 Variables por ambiente

**Vercel - Production**:

```env
NEXT_PUBLIC_API_URL=https://api.cliente.cl
```

**VPS OpenCloud - Production**: todas las variables de `backend/.env`,
incluyendo `DATABASE_URL`, `SECRET_KEY`, OAuth, IDs de Drive, Apps Script y
VAPID. Ese archivo debe permanecer solo en el servidor.

**Local**:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
CORS_ORIGINS=["http://localhost:3000"]
APP_ENV=development
```

No reutilizar por accidente la base, Drive o credenciales de desarrollo en
produccion.

### 18.8 Costos orientativos

OpenCloud publica VPS SSD desde $2.500 mensuales mas IVA para 1 GB, $6.000 mas
IVA para 2 GB y $12.000 mas IVA para 4 GB; confirmar precio y condiciones al
contratar. El servicio de backup adicional publicado por OpenCloud equivale al
20% del costo del VPS. [Planes VPS OpenCloud](https://www.opencloud.cl/vps/precios/)

Vercel puede usarse con un plan inicial para proyectos pequenos, sujeto a sus
limites y condiciones vigentes. Revisar el plan antes de entregar el sistema.
El dominio, el almacenamiento adicional de Google y cualquier servicio de
correo son costos separados.

### 18.9 Orden de puesta en marcha

1. Contratar OpenCloud y obtener IP/SSH.
2. Preparar Docker, PostgreSQL, firewall y backup.
3. Agregar los archivos de produccion del backend.
4. Configurar `.env` del cliente y ejecutar `alembic upgrade head`.
5. Autorizar OAuth Google con la cuenta del cliente.
6. Configurar Drive, Apps Script, firmas y VAPID.
7. Publicar el backend en `api.cliente.cl` con HTTPS.
8. Comprobar `/health` y el diagnostico de Google.
9. Publicar `frontend` en Vercel.
10. Configurar `NEXT_PUBLIC_API_URL` y el dominio `app.cliente.cl`.
11. Ajustar `CORS_ORIGINS` y volver a desplegar.
12. Ejecutar el checklist de aceptacion de este documento.

## 19. Como mantener el VPS siempre encendido

Un VPS no depende de que el usuario mantenga abierta una ventana. El servidor
permanece encendido en el centro de datos de OpenCloud aunque se cierre la
conexion SSH o el Escritorio remoto. Lo que debe configurarse como servicio es
la aplicacion.

### Opcion recomendada: Ubuntu o Debian

Para este proyecto se recomienda elegir Linux en OpenCloud porque FastAPI,
PostgreSQL, Docker, Caddy/Nginx y los workers de sincronizacion se administran
con menos componentes que en Windows.

En Linux se debe:

1. Instalar Docker y Docker Compose.
2. Ejecutar PostgreSQL con una politica de reinicio `unless-stopped`.
3. Ejecutar el backend como contenedor con `restart: unless-stopped`, o como
   servicio `systemd`.
4. Configurar Caddy o Nginx como reverse proxy HTTPS.
5. Comprobar que el backend vuelva a levantarse despues de reiniciar el VPS.

Cerrar SSH no detiene estos servicios. Solo se detienen si se apaga o reinicia
el VPS, si se detiene manualmente el servicio o si OpenCloud suspende el
servicio por falta de pago.

### Si se elige Windows Server

Tambien es posible, pero no se debe ejecutar la aplicacion dejando abiertas
dos ventanas de PowerShell. Se debe instalar:

1. Python 3.11+ y Node.js.
2. PostgreSQL como servicio de Windows, o Docker con una politica de reinicio.
3. El proyecto y su entorno virtual Python.
4. IIS como reverse proxy HTTPS si ya existe una pagina web en el servidor;
   Caddy solo se debe usar si no hay otro servicio ocupando los puertos 80/443.
5. NSSM, WinSW o el Programador de tareas para convertir el backend en un
   servicio de inicio automatico.

Con NSSM, el backend se registra conceptualmente asi (ajustar las rutas):

```powershell
nssm install MantencionBackend C:\Mantencion\backend\.venv\Scripts\uvicorn.exe
nssm set MantencionBackend AppDirectory C:\Mantencion\backend
nssm set MantencionBackend AppParameters "app.main:app --host 127.0.0.1 --port 8000"
nssm set MantencionBackend Start SERVICE_AUTO_START
nssm start MantencionBackend
```

El frontend no necesita instalarse en Windows si esta publicado en Vercel. En
el VPS solo quedan el backend, PostgreSQL, el worker de sincronizacion y el
reverse proxy. El backend inicia sus workers al arrancar FastAPI.

### Si ya existe una pagina web en el VPS

Antes de instalar o configurar un reverse proxy hay que identificar quien usa
los puertos 80 y 443. No se debe detener ni reemplazar la pagina existente.

La configuracion recomendada es:

- La pagina actual conserva sus bindings y sus puertos.
- El backend escucha solamente en `127.0.0.1:8000`.
- Se crea el DNS `api.cliente.cl` apuntando a la IP del VPS.
- En IIS se instala URL Rewrite y Application Request Routing (ARR), se
  habilita el proxy y se crea un sitio o binding para `api.cliente.cl`.
- Ese binding redirige internamente las solicitudes a
  `http://127.0.0.1:8000`.
- Se asigna al subdominio un certificado HTTPS propio o un certificado que
  incluya ese subdominio.

La prueba de puertos en PowerShell es:

```powershell
Get-Service W3SVC
Get-NetTCPConnection -State Listen | Sort-Object LocalPort | Select-Object LocalAddress,LocalPort,OwningProcess
```

Solo despues de confirmar el servidor web se debe elegir entre IIS, Caddy o
Nginx. Si IIS ya atiende 80/443, Caddy no debe iniciarse en esos mismos
puertos.

### HTTPS en Windows con Caddy cuando no hay otro servicio en 80/443

Con el DNS `api.cliente.cl` apuntando a la IP del VPS, Caddy puede usar una
configuracion como esta:

```text
api.cliente.cl {
    reverse_proxy 127.0.0.1:8000
}
```

Caddy debe ejecutarse como servicio de Windows. El puerto 8000 debe quedar
cerrado hacia Internet; solo deben estar publicados 80 y 443. PostgreSQL
tambien debe aceptar conexiones solo locales o desde la red privada.

### Reinicios, actualizaciones y respaldos

- Activar inicio automatico y reinicio ante error para PostgreSQL, backend y
  Caddy.
- Probar un reinicio del VPS y confirmar que `/health` responde sin abrir
  manualmente PowerShell.
- Actualizar Windows/Linux y las dependencias de forma planificada.
- Respaldar PostgreSQL en un almacenamiento separado; un snapshot del VPS no
  reemplaza un backup de base de datos.
- Revisar el estado de la cola de sincronizacion despues de cada reinicio.

El backup adicional publicado por OpenCloud crea respaldos semanales y
mensuales, pero el servicio del VPS es no administrado; el cliente debe
confirmar la retencion y probar la restauracion. [Backup de OpenCloud](https://www.opencloud.cl/vps/adicionales/)
