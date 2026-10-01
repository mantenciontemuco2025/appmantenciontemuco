from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.api.routes import auth, users, catalogs, maintenance, audit, admin, materials, work_orders, notifications, push_subscriptions, kpis, water_register, equipment_life
from app.services import email_service, push_service

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    sync_worker = asyncio.create_task(work_orders.external_sync_worker())
    push_worker = asyncio.create_task(push_service.worker())
    email_worker = asyncio.create_task(email_service.worker())
    water_register_worker = asyncio.create_task(water_register.water_register_sync_worker())
    try:
        yield
    finally:
        sync_worker.cancel()
        push_worker.cancel()
        email_worker.cancel()
        water_register_worker.cancel()
        await asyncio.gather(
            sync_worker, push_worker, email_worker, water_register_worker, return_exceptions=True
        )


app = FastAPI(
    title="Plataforma de Mantención",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Return JSON for unexpected errors so CORS can expose the response."""
    logger.exception("Error no controlado en %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Error interno del servidor. Revisa los logs del backend."},
    )

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(catalogs.router)
app.include_router(materials.router)
app.include_router(materials.admin_router)
app.include_router(maintenance.router)
app.include_router(work_orders.router)
app.include_router(notifications.router)
app.include_router(push_subscriptions.router)
app.include_router(audit.router)
app.include_router(admin.router)
app.include_router(kpis.router)
app.include_router(water_register.router)
app.include_router(equipment_life.router)

@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}


# Wrap the whole application so even unhandled 500 responses include CORS
# headers. This prevents the browser from hiding the real backend error as
# "Failed to fetch".
_fastapi_app = app
app = CORSMiddleware(
    app=app,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Keep the FastAPI override hook available to the test suite and local tools.
app.dependency_overrides = _fastapi_app.dependency_overrides
