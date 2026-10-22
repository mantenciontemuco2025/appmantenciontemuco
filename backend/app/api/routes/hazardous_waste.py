"""Admin-only hazardous waste register with durable Google Sheets sync."""

import asyncio
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_roles
from app.core.config import settings
from app.db.session import async_session, get_db
from app.models.hazardous_waste import HazardousWasteRecord, HazardousWasteSettings
from app.models.user import User, UserRole
from app.schemas.hazardous_waste import (
    HazardousWasteDisposalInput, HazardousWasteInput, HazardousWasteRecordResponse,
    HazardousWasteSetupResponse,
)
from app.services.hazardous_waste_sheet import (
    parse_spreadsheet_id, read_annual_tabs, stamp_import_keys, write_record,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/hazardous-waste", tags=["hazardous-waste"])
admin_only = require_roles(UserRole.ADMIN)


def _norm(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    return "".join(c for c in text if not unicodedata.combining(c)).strip().casefold()


def _identity(record: HazardousWasteRecord) -> tuple[str, str, str]:
    code = _norm(record.respel_code)
    # The register tracks counts of containers/items, not kilograms or liters.
    # Ignore legacy unit labels so corrected records reconcile with the annual history.
    return ("code" if code else "name", code or _norm(record.waste_name), "")


def _payload(record: HazardousWasteRecord) -> dict:
    return {
        "id": record.id, "entry_date": record.entry_date, "respel_code": record.respel_code,
        "waste_name": record.waste_name, "hazard": record.hazard, "origin": record.origin,
        "quantity": record.quantity, "unit": record.unit,
        "accumulated_quantity": record.accumulated_quantity, "delivered_by": record.delivered_by,
        "disposal_date": record.disposal_date, "manager": record.manager,
        "source_sheet": record.source_sheet, "sheet_row": record.sheet_row,
    }


def _environment_sheet_id() -> str | None:
    configured = settings.GOOGLE_HAZARDOUS_WASTE_SPREADSHEET_ID.strip()
    if not configured:
        return None
    try:
        return parse_spreadsheet_id(configured)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail="GOOGLE_HAZARDOUS_WASTE_SPREADSHEET_ID debe contener un ID válido de Google Sheets.",
        ) from exc


async def _recalculate(db: AsyncSession, identities: set[tuple[str, str, str]] | None = None) -> None:
    stmt = select(HazardousWasteRecord).order_by(HazardousWasteRecord.entry_date, HazardousWasteRecord.id)
    records = (await db.scalars(stmt)).all()
    groups: dict[tuple[str, str, str], list[HazardousWasteRecord]] = {}
    for record in records:
        key = _identity(record)
        if identities is None or key in identities:
            groups.setdefault(key, []).append(record)
    for group in groups.values():
        for record in group:
            active = [item for item in group
                      if item.entry_date <= record.entry_date
                      and (item.disposal_date is None or item.disposal_date > record.entry_date)]
            total = (
                None
                if any(item.quantity is None for item in active)
                else sum((Decimal(item.quantity) for item in active), Decimal("0"))
            )
            if record.accumulated_quantity != total:
                record.accumulated_quantity = total
                if record.sync_status == "SYNCED":
                    record.sync_status = "PENDING"
                record.sync_version += 1
                record.sync_error = None
                record.sync_next_attempt_at = None


@router.get("/status")
async def status(_user: User = Depends(admin_only), db: AsyncSession = Depends(get_db)):
    config = await db.get(HazardousWasteSettings, 1)
    environment_id = _environment_sheet_id()
    if config and environment_id and config.spreadsheet_id != environment_id:
        count = int(await db.scalar(select(func.count(HazardousWasteRecord.id))) or 0)
        return {
            "configured": False,
            "environment_configured": True,
            "configuration_error": "El ID de Render no coincide con la planilla conectada en la base de datos. Se bloqueó la sincronización para evitar escribir en un archivo equivocado.",
            "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{environment_id}/edit",
            "records": count,
        }
    if config is None:
        return {
            "configured": False,
            "environment_configured": environment_id is not None,
            "configuration_error": None,
            "spreadsheet_url": (
                f"https://docs.google.com/spreadsheets/d/{environment_id}/edit"
                if environment_id else None
            ),
            "records": 0,
        }
    count = int(await db.scalar(select(func.count(HazardousWasteRecord.id))) or 0)
    return {
        "configured": True,
        "environment_configured": environment_id is not None,
        "configuration_error": None,
        "spreadsheet_url": config.spreadsheet_url,
        "records": count,
    }


@router.post("/setup", response_model=HazardousWasteSetupResponse)
async def setup(
    body: dict,
    current_user: User = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
):
    link = str(body.get("spreadsheet_url") or "").strip()
    try:
        environment_id = _environment_sheet_id()
        if environment_id:
            if link and parse_spreadsheet_id(link) != environment_id:
                raise HTTPException(
                    status_code=409,
                    detail="El enlace no coincide con GOOGLE_HAZARDOUS_WASTE_SPREADSHEET_ID configurado para este entorno.",
                )
            spreadsheet_id = environment_id
            link = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        else:
            spreadsheet_id = parse_spreadsheet_id(link)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    existing_config = await db.get(HazardousWasteSettings, 1)
    if existing_config and existing_config.spreadsheet_id != spreadsheet_id:
        raise HTTPException(status_code=409, detail="La planilla ya conectada tiene otro ID. No se cambió para proteger los registros existentes.")
    if existing_config:
        raise HTTPException(status_code=409, detail="La planilla ya está conectada. Usa la opción de actualizar/importar si necesitas otra.")
    try:
        rows = await asyncio.to_thread(read_annual_tabs, spreadsheet_id)
    except Exception as exc:
        logger.exception("No se pudo leer la planilla de residuos peligrosos")
        raise HTTPException(status_code=502, detail=f"No se pudo leer Google Sheets: {str(exc)[:300]}") from exc
    if not rows:
        raise HTTPException(status_code=422, detail="La planilla no contiene registros anuales que se puedan importar.")
    now = datetime.now(timezone.utc)
    config = HazardousWasteSettings(
        id=1, spreadsheet_id=spreadsheet_id, spreadsheet_url=link,
        configured_by_user_id=current_user.id, configured_at=now,
    )
    db.add(config)
    imported: list[HazardousWasteRecord] = []
    for item in rows:
        code = item.get("respel_code")
        name = item["waste_name"]
        record = HazardousWasteRecord(
            **{k: v for k, v in item.items() if k != "external_key"},
            normalized_code=_norm(code), normalized_name=_norm(name),
            accumulated_quantity=Decimal("0"), created_by_user_id=current_user.id,
            updated_by_user_id=current_user.id, sync_status="SYNCED",
            sync_version=1, synced_version=1, sheet_synced_at=now,
        )
        db.add(record)
        imported.append(record)
    await db.flush()
    await _recalculate(db)
    await db.commit()
    key_rows = [{"id": record.id, "source_sheet": record.source_sheet, "sheet_row": record.sheet_row} for record in imported]
    try:
        await asyncio.to_thread(stamp_import_keys, spreadsheet_id, key_rows)
    except Exception as exc:
        logger.warning("No se pudieron escribir claves internas iniciales en la planilla de residuos: %s", exc)
        async with async_session() as retry_db:
            for record_id in [record.id for record in imported]:
                record = await retry_db.get(HazardousWasteRecord, record_id)
                if record:
                    record.sync_status = "PENDING"
                    record.sync_version += 1
                    record.sync_error = str(exc)[:1000]
            await retry_db.commit()
    return HazardousWasteSetupResponse(
        spreadsheet_id=spreadsheet_id, spreadsheet_url=link, imported=len(imported),
        message="Planilla conectada e historial anual importado. La pestaña de stock no se duplicó.",
    )


@router.get("", response_model=list[HazardousWasteRecordResponse])
async def list_records(
    year: int | None = None,
    search: str | None = None,
    stored_only: bool = False,
    _user: User = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(HazardousWasteRecord).order_by(HazardousWasteRecord.entry_date.desc(), HazardousWasteRecord.id.desc()).limit(2000)
    if year:
        from sqlalchemy import extract
        stmt = stmt.where(extract("year", HazardousWasteRecord.entry_date) == year)
    if stored_only:
        stmt = stmt.where(HazardousWasteRecord.disposal_date.is_(None))
    if search:
        needle = f"%{search.strip()}%"
        stmt = stmt.where(or_(HazardousWasteRecord.waste_name.ilike(needle), HazardousWasteRecord.respel_code.ilike(needle), HazardousWasteRecord.origin.ilike(needle)))
    return (await db.scalars(stmt)).all()


@router.post("", response_model=HazardousWasteRecordResponse)
async def create_record(body: HazardousWasteInput, current_user: User = Depends(admin_only), db: AsyncSession = Depends(get_db)):
    if not await db.get(HazardousWasteSettings, 1):
        raise HTTPException(status_code=409, detail="Primero conecta la planilla de Google Sheets.")
    if body.disposal_date and body.disposal_date < body.entry_date:
        raise HTTPException(status_code=422, detail="La fecha de disposición no puede ser anterior al ingreso.")
    record = HazardousWasteRecord(
        **{**body.model_dump(), "unit": ""}, normalized_code=_norm(body.respel_code), normalized_name=_norm(body.waste_name),
        accumulated_quantity=Decimal("0"), created_by_user_id=current_user.id,
        updated_by_user_id=current_user.id, sync_status="PENDING", sync_version=1, synced_version=0,
    )
    db.add(record)
    await db.flush()
    await _recalculate(db, {_identity(record)})
    await db.commit()
    await db.refresh(record)
    return record


@router.put("/{record_id}", response_model=HazardousWasteRecordResponse)
async def update_record(record_id: int, body: HazardousWasteInput, current_user: User = Depends(admin_only), db: AsyncSession = Depends(get_db)):
    record = await db.get(HazardousWasteRecord, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No se encontró el ingreso.")
    if body.disposal_date and body.disposal_date < body.entry_date:
        raise HTTPException(status_code=422, detail="La fecha de disposición no puede ser anterior al ingreso.")
    identities = {_identity(record), ("code" if _norm(body.respel_code) else "name", _norm(body.respel_code) or _norm(body.waste_name), "")}
    for field, value in {**body.model_dump(), "unit": ""}.items():
        setattr(record, field, value)
    record.normalized_code = _norm(body.respel_code)
    record.normalized_name = _norm(body.waste_name)
    record.updated_by_user_id = current_user.id
    record.sync_status = "PENDING"
    record.sync_version += 1
    record.sync_error = None
    record.sync_next_attempt_at = None
    await _recalculate(db, identities)
    await db.commit()
    await db.refresh(record)
    return record


@router.post("/{record_id}/dispose")
async def dispose_stock(
    record_id: int,
    body: HazardousWasteDisposalInput,
    current_user: User = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
):
    selected = await db.get(HazardousWasteRecord, record_id)
    if selected is None:
        raise HTTPException(status_code=404, detail="No se encontró el ingreso.")
    if body.disposal_date < selected.entry_date:
        raise HTTPException(status_code=422, detail="La fecha de retiro no puede ser anterior al ingreso.")

    identity = _identity(selected)
    records = (await db.scalars(select(HazardousWasteRecord))).all()
    to_dispose = [
        record for record in records
        if _identity(record) == identity
        and record.disposal_date is None
        and record.entry_date <= body.disposal_date
    ]
    if not to_dispose:
        raise HTTPException(status_code=409, detail="No hay unidades almacenadas de este residuo para retirar en esa fecha.")

    for record in to_dispose:
        record.disposal_date = body.disposal_date
        record.manager = body.manager.strip().upper()
        record.updated_by_user_id = current_user.id
        record.sync_status = "PENDING"
        record.sync_version += 1
        record.sync_error = None
        record.sync_next_attempt_at = None
    await _recalculate(db, {identity})
    await db.commit()
    return {
        "updated": len(to_dispose),
        "disposal_date": body.disposal_date,
        "manager": body.manager.strip().upper(),
        "message": "Retiro registrado; el acumulado comienza nuevamente después de la fecha de disposición.",
    }


@router.post("/{record_id}/retry", response_model=HazardousWasteRecordResponse)
async def retry_sync(record_id: int, _user: User = Depends(admin_only), db: AsyncSession = Depends(get_db)):
    record = await db.get(HazardousWasteRecord, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No se encontró el ingreso.")
    record.sync_status = "PENDING"
    record.sync_error = None
    record.sync_next_attempt_at = None
    record.sync_version += 1
    await db.commit()
    await db.refresh(record)
    return record


async def hazardous_waste_sync_worker() -> None:
    """Synchronize one queued row at a time, releasing DB connections during Google calls."""
    while True:
        try:
            async with async_session() as db:
                now = datetime.now(timezone.utc)
                await db.execute(update(HazardousWasteRecord).where(
                    HazardousWasteRecord.sync_status == "SYNCING",
                    HazardousWasteRecord.updated_at < now - timedelta(minutes=5),
                ).values(sync_status="PENDING", sync_next_attempt_at=None))
                await db.commit()
                record = (await db.scalars(
                    select(HazardousWasteRecord)
                    .where(HazardousWasteRecord.sync_status.in_(("PENDING", "FAILED")),
                           (HazardousWasteRecord.sync_next_attempt_at.is_(None)) | (HazardousWasteRecord.sync_next_attempt_at <= now))
                    .order_by(HazardousWasteRecord.entry_date, HazardousWasteRecord.id)
                    .with_for_update(skip_locked=True).limit(1)
                )).first()
                if not record:
                    await db.rollback()
                    await asyncio.sleep(3)
                    continue
                config = await db.get(HazardousWasteSettings, 1)
                if not config:
                    record.sync_status = "FAILED"
                    record.sync_error = "No se ha conectado la planilla de Google Sheets."
                    await db.commit()
                    await asyncio.sleep(5)
                    continue
                environment_id = settings.GOOGLE_HAZARDOUS_WASTE_SPREADSHEET_ID.strip()
                if environment_id:
                    try:
                        environment_id = parse_spreadsheet_id(environment_id)
                    except ValueError:
                        environment_id = "__invalid_environment_sheet_id__"
                    if environment_id != config.spreadsheet_id:
                        record.sync_status = "FAILED"
                        record.sync_error = "El ID de la planilla configurado en el entorno no coincide con el de la base. Se bloqueó la escritura."
                        record.sync_next_attempt_at = datetime.now(timezone.utc) + timedelta(hours=1)
                        await db.commit()
                        await asyncio.sleep(10)
                        continue
                snapshot = _payload(record)
                version = record.sync_version
                record_id = record.id
                record.sync_status = "SYNCING"
                record.sync_attempts += 1
                attempt = record.sync_attempts
                await db.commit()
            try:
                row = await asyncio.wait_for(asyncio.to_thread(write_record, config.spreadsheet_id, snapshot), timeout=90)
                error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error = str(exc)[:1000]
                row = None
                logger.warning("Error sincronizando registro de residuo %s: %s", record_id, error)
            async with async_session() as result_db:
                fresh = await result_db.get(HazardousWasteRecord, record_id)
                if fresh:
                    if fresh.sync_version != version:
                        fresh.sync_status = "PENDING"
                        fresh.sync_next_attempt_at = None
                    elif error is None:
                        fresh.sync_status = "SYNCED"
                        fresh.sync_error = None
                        fresh.sheet_row = row
                        fresh.synced_version = version
                        fresh.sheet_synced_at = datetime.now(timezone.utc)
                        fresh.sync_next_attempt_at = None
                    else:
                        fresh.sync_status = "FAILED"
                        fresh.sync_error = error
                        fresh.sync_next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=min(60 * 2 ** min(attempt - 1, 6), 3600))
                    await result_db.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error en ciclo de sincronización de residuos peligrosos")
            await asyncio.sleep(5)
