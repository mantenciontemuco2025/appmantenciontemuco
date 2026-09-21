"""Daily water/discharge register, kept independent from work orders."""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_current_user, require_roles
from app.core.config import settings
from app.core.water_register import WATER_METERS, WATER_METER_BY_KEY
from app.db.session import async_session, get_db
from app.models.user import User, UserRole
from app.models.water_register import (
    WaterDqoSample,
    WaterMeterReading,
    WaterRegisterBaseline,
    WaterRegisterRecord,
)
from app.schemas.water_register import (
    WaterRegisterInput,
    WaterHistoricalResponse,
    WaterRegisterRecordResponse,
    WaterRegisterResponse,
)
from app.services.water_register_sheet import (
    read_historical_range,
    read_latest_meter_baselines,
    write_daily_record,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/water-register", tags=["water-register"])
manager_roles = require_roles(UserRole.ADMIN, UserRole.SUPERVISOR)
admin_only = require_roles(UserRole.ADMIN)


def _record_to_sheet(record: WaterRegisterRecord) -> dict:
    dqo_samples = [
        {
            "date": item.sample_date,
            "time": item.sample_time,
            "pool": item.pool,
            "mg_l": float(item.mg_l),
            "sheet_row": item.sheet_row,
        }
        for item in record.dqo_samples
    ]
    if not dqo_samples and record.dqo_mg_l is not None:
        dqo_samples = [{
            "date": record.dqo_date or record.record_date,
            "time": record.dqo_time,
            "pool": record.dqo_pool,
            "mg_l": float(record.dqo_mg_l),
            "sheet_row": record.sheet_row,
        }]
    readings = {
        item.meter_key: {
            "initial_reading": float(item.initial_reading),
            "final_reading": float(item.final_reading),
        }
        for item in record.meter_readings
    }
    return {
        "record_date": record.record_date,
        "discharge_flow_m3": float(record.discharge_flow_m3) if record.discharge_flow_m3 is not None else None,
        "ph_plc": float(record.ph_plc) if record.ph_plc is not None else None,
        "ph_discharge": float(record.ph_discharge) if record.ph_discharge is not None else None,
        "discharge_temp_c": float(record.discharge_temp_c) if record.discharge_temp_c is not None else None,
        "dqo_samples": dqo_samples,
        "dqo_rows_to_clear": list(record.dqo_rows_to_clear or []),
        "readings": readings,
    }


async def _loaded_record(db: AsyncSession, record_id: int) -> WaterRegisterRecord:
    result = await db.execute(
        select(WaterRegisterRecord)
        .options(
            selectinload(WaterRegisterRecord.meter_readings),
            selectinload(WaterRegisterRecord.dqo_samples),
        )
        .where(WaterRegisterRecord.id == record_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="No se encontró el registro.")
    return record


async def _opening_reading(db: AsyncSession, meter_key: str, record_date) -> Decimal:
    prior = await db.execute(
        select(WaterMeterReading.final_reading)
        .join(WaterRegisterRecord, WaterRegisterRecord.id == WaterMeterReading.record_id)
        .where(
            WaterMeterReading.meter_key == meter_key,
            WaterRegisterRecord.record_date < record_date,
        )
        .order_by(WaterRegisterRecord.record_date.desc())
        .limit(1)
    )
    value = prior.scalar_one_or_none()
    if value is not None:
        return Decimal(value)
    baseline = await db.get(WaterRegisterBaseline, meter_key)
    if baseline is None:
        raise HTTPException(
            status_code=409,
            detail="Primero inicializa las últimas lecturas desde la plantilla (solo administrador).",
        )
    if record_date <= baseline.reading_date:
        raise HTTPException(
            status_code=409,
            detail=f"La fecha debe ser posterior a la lectura inicial ({baseline.reading_date:%d-%m-%Y}).",
        )
    return Decimal(baseline.final_reading)


async def _recalculate_later_openings(db: AsyncSession, record_date) -> list[int]:
    """Rebuild later initial readings after a historical entry was edited."""
    result = await db.execute(
        select(WaterRegisterRecord)
        .options(selectinload(WaterRegisterRecord.meter_readings))
        .where(WaterRegisterRecord.record_date > record_date)
        .order_by(WaterRegisterRecord.record_date)
    )
    later_records = result.scalars().all()
    touched: list[int] = []
    for record in later_records:
        changed = False
        for reading in record.meter_readings:
            new_initial = await _opening_reading(db, reading.meter_key, record.record_date)
            if Decimal(reading.initial_reading) != new_initial:
                reading.initial_reading = new_initial
                changed = True
        if changed:
            record.sync_version += 1
            record.sync_status = "PENDING"
            record.sync_error = None
            record.sync_next_attempt_at = None
            touched.append(record.id)
    return touched


async def _upsert_record(
    payload: WaterRegisterInput,
    current_user: User,
    db: AsyncSession,
    record: WaterRegisterRecord | None,
) -> WaterRegisterRecord:
    unknown = set(payload.meter_final_readings) - set(WATER_METER_BY_KEY)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Medidor desconocido: {', '.join(sorted(unknown))}")
    baseline_keys = set((await db.scalars(select(WaterRegisterBaseline.meter_key))).all())
    if baseline_keys != set(WATER_METER_BY_KEY):
        raise HTTPException(status_code=409, detail="El administrador debe inicializar el registro primero.")

    if record is None:
        record = WaterRegisterRecord(
            record_date=payload.record_date,
            created_by_user_id=current_user.id,
            updated_by_user_id=current_user.id,
        )
        db.add(record)
        await db.flush()
    elif record.record_date != payload.record_date:
        raise HTTPException(status_code=400, detail="No se puede cambiar la fecha del registro existente.")

    record.discharge_flow_m3 = payload.discharge_flow_m3
    record.ph_plc = payload.ph_plc
    record.ph_discharge = payload.ph_discharge
    record.discharge_temp_c = payload.discharge_temp_c

    existing_result = await db.execute(
        select(WaterDqoSample)
        .where(WaterDqoSample.record_id == record.id)
        .order_by(WaterDqoSample.position, WaterDqoSample.id)
    )
    existing_samples = existing_result.scalars().all()
    existing_by_id = {sample.id: sample for sample in existing_samples}
    existing_by_position = {sample.position: sample for sample in existing_samples}
    retained_ids: set[int] = set()
    for position, item in enumerate(payload.dqo_samples):
        sample = existing_by_id.get(item.id) if item.id is not None else None
        if sample is None and item.id is None:
            sample = existing_by_position.get(position)
        if sample is not None and sample.id in retained_ids:
            sample = None
        if sample is None:
            sample = WaterDqoSample(record_id=record.id)
            db.add(sample)
        else:
            retained_ids.add(sample.id)
        sample.sample_date = item.date
        sample.sample_time = item.time.strftime("%H:%M")
        sample.pool = item.pool.strip()
        sample.mg_l = item.mg_l
        sample.position = position

    rows_to_clear = set(record.dqo_rows_to_clear or [])
    for sample in existing_samples:
        if sample.id in retained_ids:
            continue
        if sample.sheet_row is not None:
            rows_to_clear.add(sample.sheet_row)
        await db.delete(sample)
    record.dqo_rows_to_clear = sorted(rows_to_clear)

    first_dqo = payload.dqo_samples[0] if payload.dqo_samples else None
    record.dqo_date = first_dqo.date if first_dqo else None
    record.dqo_time = first_dqo.time.strftime("%H:%M") if first_dqo else None
    record.dqo_pool = first_dqo.pool.strip() if first_dqo else None
    record.dqo_mg_l = first_dqo.mg_l if first_dqo else None
    record.updated_by_user_id = current_user.id
    record.sync_version += 1
    record.sync_status = "PENDING"
    record.sync_error = None
    record.sync_next_attempt_at = None

    old = await db.execute(
        select(WaterMeterReading).where(WaterMeterReading.record_id == record.id)
    )
    old_rows = old.scalars().all()
    for reading in old_rows:
        await db.delete(reading)
    await db.flush()

    for meter_key, final_reading in payload.meter_final_readings.items():
        if final_reading is None:
            continue
        opening = await _opening_reading(db, meter_key, payload.record_date)
        db.add(WaterMeterReading(
            record_id=record.id,
            meter_key=meter_key,
            initial_reading=opening,
            final_reading=final_reading,
        ))
    await db.flush()
    await db.refresh(record)
    return record


@router.get("/history", response_model=WaterHistoricalResponse)
async def historical_water_register(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    current_user: User = Depends(get_current_user),
):
    del current_user
    if from_date > to_date:
        raise HTTPException(status_code=422, detail="La fecha desde no puede ser posterior a la fecha hasta.")
    if (to_date - from_date).days > 366:
        raise HTTPException(status_code=422, detail="El rango máximo de consulta es de 366 días.")
    try:
        rows = await asyncio.to_thread(read_historical_range, from_date, to_date)
    except Exception as exc:
        logger.exception("No se pudo consultar el histórico del registro de agua")
        raise HTTPException(status_code=502, detail=f"No se pudo consultar la planilla: {exc}") from exc
    return {"from_date": from_date, "to_date": to_date, "rows": rows}


@router.get("", response_model=WaterRegisterResponse)
async def list_water_register(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    records_result = await db.execute(
        select(WaterRegisterRecord)
        .options(
            selectinload(WaterRegisterRecord.meter_readings),
            selectinload(WaterRegisterRecord.dqo_samples),
        )
        .order_by(WaterRegisterRecord.record_date.desc())
        .limit(90)
    )
    baselines_result = await db.execute(
        select(WaterRegisterBaseline).order_by(WaterRegisterBaseline.meter_key)
    )
    latest_result = await db.execute(
        select(WaterMeterReading.meter_key, WaterMeterReading.final_reading)
        .join(WaterRegisterRecord, WaterRegisterRecord.id == WaterMeterReading.record_id)
        .order_by(WaterMeterReading.meter_key, WaterRegisterRecord.record_date.desc())
    )
    latest_readings = {}
    for meter_key, final_reading in latest_result.all():
        latest_readings.setdefault(meter_key, str(final_reading))
    baseline_rows = baselines_result.scalars().all()
    for baseline in baseline_rows:
        latest_readings.setdefault(baseline.meter_key, str(baseline.final_reading))
    return {
        "records": records_result.scalars().all(),
        "baselines": [
            {
                "meter_key": row.meter_key,
                "final_reading": row.final_reading,
                "reading_date": row.reading_date,
                "source_row": row.source_row,
            }
            for row in baseline_rows
        ],
        "meters": [{"key": meter.key, "label": meter.label} for meter in WATER_METERS],
        "latest_readings": latest_readings,
    }


@router.post("/initialize-from-sheet")
async def initialize_from_sheet(
    current_user: User = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
):
    try:
        baselines = await asyncio.to_thread(read_latest_meter_baselines)
    except Exception as exc:
        logger.exception("No se pudieron importar las lecturas iniciales del registro de agua")
        raise HTTPException(status_code=502, detail=f"No se pudo leer la plantilla: {exc}") from exc

    inserted = 0
    for item in baselines:
        existing = await db.get(WaterRegisterBaseline, item["meter_key"])
        if existing is None:
            db.add(WaterRegisterBaseline(
                **item,
                initialized_by_user_id=current_user.id,
                initialized_at=datetime.now(timezone.utc),
            ))
            inserted += 1
    await db.commit()
    return {"initialized": inserted, "baselines": len(baselines), "message": "Lecturas iniciales revisadas."}


async def _save_payload(
    payload: WaterRegisterInput,
    current_user: User,
    db: AsyncSession,
    record: WaterRegisterRecord | None,
):
    if record is None:
        duplicate = await db.scalar(
            select(WaterRegisterRecord.id).where(WaterRegisterRecord.record_date == payload.record_date)
        )
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="Ya existe un registro para ese día.")
    try:
        record = await _upsert_record(payload, current_user, db, record)
        record_id = record.id
        await _recalculate_later_openings(db, payload.record_date)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Ya existe un registro para ese día.",
        ) from exc
    result = await _loaded_record(db, record_id)
    return result


@router.post("", response_model=WaterRegisterRecordResponse, status_code=status.HTTP_201_CREATED)
async def create_water_record(
    payload: WaterRegisterInput,
    current_user: User = Depends(manager_roles),
    db: AsyncSession = Depends(get_db),
):
    return await _save_payload(payload, current_user, db, None)


@router.put("/{record_date}", response_model=WaterRegisterRecordResponse)
async def update_water_record(
    record_date: date,
    payload: WaterRegisterInput,
    current_user: User = Depends(manager_roles),
    db: AsyncSession = Depends(get_db),
):
    if record_date != payload.record_date:
        raise HTTPException(status_code=400, detail="La fecha de la URL y del formulario no coincide.")
    result = await db.execute(
        select(WaterRegisterRecord).where(WaterRegisterRecord.record_date == record_date)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="No se encontró el registro de esa fecha.")
    return await _save_payload(payload, current_user, db, record)


@router.post("/{record_id}/retry-sync")
async def retry_water_sync(
    record_id: int,
    current_user: User = Depends(manager_roles),
    db: AsyncSession = Depends(get_db),
):
    record = await _loaded_record(db, record_id)
    record.sync_status = "PENDING"
    record.sync_error = None
    record.sync_next_attempt_at = None
    record.sync_version += 1
    await db.commit()
    return {"status": "PENDING", "message": "El registro quedó en cola para sincronizar."}


async def water_register_sync_worker() -> None:
    """Persistently sync queued records without holding a DB connection on Google I/O."""
    while True:
        try:
            async with async_session() as db:
                now = datetime.now(timezone.utc)
                stale_cutoff = now - timedelta(minutes=5)
                stale = await db.execute(
                    update(WaterRegisterRecord)
                    .where(
                        WaterRegisterRecord.sync_status == "SYNCING",
                        WaterRegisterRecord.updated_at < stale_cutoff,
                    )
                    .values(
                        sync_status="PENDING",
                        sync_error="Se reanudó una sincronización interrumpida.",
                        sync_next_attempt_at=None,
                        updated_at=now,
                    )
                )
                if stale.rowcount:
                    logger.warning("Se reanudaron %s registros de agua interrumpidos", stale.rowcount)
                result = await db.execute(
                    select(WaterRegisterRecord)
                    .options(
                        selectinload(WaterRegisterRecord.meter_readings),
                        selectinload(WaterRegisterRecord.dqo_samples),
                    )
                    .where(
                        WaterRegisterRecord.sync_status.in_(("PENDING", "FAILED")),
                        (WaterRegisterRecord.sync_next_attempt_at.is_(None))
                        | (WaterRegisterRecord.sync_next_attempt_at <= now),
                    )
                    .order_by(WaterRegisterRecord.record_date)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                record = result.scalar_one_or_none()
                if record is None:
                    await db.rollback()
                    await asyncio.sleep(3)
                    continue
                snapshot = _record_to_sheet(record)
                record_id = record.id
                version = record.sync_version
                was_previously_synced = record.sheet_row is not None
                record.sync_status = "SYNCING"
                record.sync_attempts += 1
                attempt = record.sync_attempts
                await db.commit()

            try:
                sync_result = await asyncio.wait_for(
                    asyncio.to_thread(
                        write_daily_record,
                        snapshot,
                        allow_existing=was_previously_synced,
                    ),
                    timeout=90,
                )
                error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                sync_result = None
                error = str(exc)[:1000]
                logger.warning("Falló la sincronización del registro de agua %s: %s", record_id, error)

            async with async_session() as result_db:
                fresh = await result_db.get(WaterRegisterRecord, record_id)
                if fresh is None:
                    continue
                if fresh.sync_version != version:
                    # A manager changed the row while the old snapshot was in flight.
                    fresh.sync_status = "PENDING"
                    fresh.sync_next_attempt_at = None
                elif error is None:
                    fresh.sync_status = "SYNCED"
                    fresh.sync_error = None
                    fresh.sheet_row = sync_result["record_row"]
                    sample_result = await result_db.execute(
                        select(WaterDqoSample)
                        .where(WaterDqoSample.record_id == fresh.id)
                        .order_by(WaterDqoSample.position, WaterDqoSample.id)
                    )
                    for sample, sheet_row in zip(
                        sample_result.scalars().all(), sync_result["dqo_rows"]
                    ):
                        sample.sheet_row = sheet_row
                    fresh.dqo_rows_to_clear = []
                    fresh.sheet_synced_at = datetime.now(timezone.utc)
                    fresh.synced_version = version
                    fresh.sync_next_attempt_at = None
                else:
                    fresh.sync_status = "FAILED"
                    fresh.sync_error = error
                    fresh.sync_next_attempt_at = datetime.now(timezone.utc) + timedelta(
                        seconds=min(60 * (2 ** min(attempt - 1, 6)), 3600)
                    )
                await result_db.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error en ciclo de sincronización del registro de agua")
            await asyncio.sleep(5)
