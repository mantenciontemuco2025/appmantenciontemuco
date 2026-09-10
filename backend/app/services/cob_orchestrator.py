"""COB (Close of Business) Orchestrator — E2E workflow engine.

Modern Python patterns:
  - asynccontextmanager for resource lifecycle
  - TaskGroup for concurrent validation (ExceptionGroup propagation)
  - Streaming pipeline via async generator (yields structured COBEvents)
  - Structured dataclasses for events and errors

Usage:
    async with COBSession(db, user) as session:
        async for event in session.run():
            match event:
                case InitComplete(results=results):
                    ...
                case OrderProcessed(order_id=oid, success=True):
                    ...
                case PipelineComplete(stats=stats):
                    ...
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.work_order import WorkOrder, WorkOrderStatus
from app.models.user import User, UserRole
from app.services.wo_state_machine import validate_transition, InvalidTransitionError
from app.services import wo_permissions as perms


# ── Structured Events ──────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class InitComplete:
    """Phase 1 finished: context ready."""
    validated_orders: int
    eligible_orders: int
    duration_ms: float


@dataclass(frozen=True, slots=True)
class OrderProcessed:
    """One work order advanced through the pipeline."""
    order_id: int
    ot_number: str
    previous_status: str
    new_status: str
    success: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class PipelineComplete:
    """Entire pipeline finished."""
    total_orders: int
    processed: int
    succeeded: int
    failed: int
    skipped: int
    errors: list[COBError] = field(default_factory=list)
    duration_ms: float = 0.0


# ── Structured Errors ──────────────────────────────────────────────────────

class COBError(Exception):
    """Base error for COB pipeline failures.

    Uses __slots__ so subclasses can't accidentally inherit a __dict__.
    Each subclass sets a fixed `code` class attribute.
    """
    __slots__ = ("order_id", "ot_number")
    code: str = "COB_ERROR"

    def __init__(self, message: str, *, order_id: int | None = None, ot_number: str | None = None):
        super().__init__(message)
        self.order_id = order_id
        self.ot_number = ot_number

    @property
    def message(self) -> str:
        return super().__str__()


class ValidationError(COBError):
    """Validation failed (missing fields, bad state)."""
    __slots__ = ()
    code = "VALIDATION_ERROR"


class TransitionError(COBError):
    """State machine rejected the transition."""
    __slots__ = ("current_status", "target_status")
    code = "TRANSITION_ERROR"

    def __init__(self, message: str, *, current_status: str = "", target_status: str = "",
                 order_id: int | None = None, ot_number: str | None = None):
        super().__init__(message, order_id=order_id, ot_number=ot_number)
        self.current_status = current_status
        self.target_status = target_status


class PermissionError(COBError):
    """User lacks permission for the action."""
    __slots__ = ()
    code = "PERMISSION_ERROR"


class ConcurrencyError(COBError):
    """Another session already modified this order."""
    __slots__ = ()
    code = "CONCURRENCY_ERROR"


# ── COB Session (asynccontextmanager) ─────────────────────────────────────

class COBSession:
    """Managed COB session — use via create_cob_session().

    Lifecycle:
        __aenter__  → load eligible orders (SELECT FOR UPDATE)
        run()       → streaming pipeline (async generator)
        __aexit__   → rollback on error, commit on success
    """

    def __init__(self, db: AsyncSession, user: User) -> None:
        self._db = db
        self._user = user
        self._eligible: list[WorkOrder] = []
        self._started_at: float = 0.0
        self._errors: list[COBError] = []
        self._committed = False

    async def __aenter__(self) -> COBSession:
        self._started_at = time.monotonic()
        await self._load_eligible_orders()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> bool:
        if exc_val is None and not self._committed:
            await self._db.commit()
            self._committed = True
        elif exc_val is not None:
            await self._db.rollback()
        return False  # don't suppress exceptions

    # ── Resource Loading (concurrent via TaskGroup) ───────────────────────

    async def _load_eligible_orders(self) -> None:
        """Load work orders eligible for COB processing using TaskGroup
        for concurrent validation of business rules."""

        # Base query: orders not yet finalized
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        result = await self._db.execute(
            select(WorkOrder)
            .where(
                WorkOrder.status.in_([
                    WorkOrderStatus.PENDING.value,
                    WorkOrderStatus.IN_PROGRESS.value,
                ])
            )
            .options(
                selectinload(WorkOrder.area),
                selectinload(WorkOrder.equipment),
                selectinload(WorkOrder.responsible_user),
                selectinload(WorkOrder.participants),
            )
            .with_for_update()
        )
        candidates = list(result.scalars().all())

        # Concurrent validation using TaskGroup + ExceptionGroup
        validation_errors: list[COBError] = []

        async def _validate_one(wo: WorkOrder) -> None:
            """Validate a single order's eligibility."""
            if not wo.area:
                validation_errors.append(
                    ValidationError(
                        message=f"OT {wo.ot_number} no tiene área asignada",
                        order_id=wo.id,
                        ot_number=wo.ot_number,
                    )
                )
            if wo.status == WorkOrderStatus.PENDING.value and not wo.responsible_user_id:
                validation_errors.append(
                    ValidationError(
                        message=f"OT {wo.ot_number} (PENDING) no tiene responsable asignado",
                        order_id=wo.id,
                        ot_number=wo.ot_number,
                    )
                )

        try:
            async with asyncio.TaskGroup() as tg:
                for wo in candidates:
                    tg.create_task(_validate_one(wo))
        except* COBError as eg:
            # ExceptionGroup[COBError] — propagate structured errors
            for err in eg.exceptions:
                validation_errors.append(err)

        self._errors.extend(validation_errors)

        # Filter to only orders that passed validation
        error_ids = {e.order_id for e in validation_errors}
        self._eligible = [wo for wo in candidates if wo.id not in error_ids]

    # ── Streaming Pipeline ────────────────────────────────────────────────

    async def run(self) -> AsyncGenerator[InitComplete | OrderProcessed | PipelineComplete, None]:
        """Execute the COB pipeline, yielding structured events.

        Phases:
          1. InitComplete  — context loaded, validation done
          2. OrderProcessed × N — each order advances
          3. PipelineComplete — summary with stats
        """
        init_duration = (time.monotonic() - self._started_at) * 1000

        yield InitComplete(
            validated_orders=len(self._eligible) + len(self._errors),
            eligible_orders=len(self._eligible),
            duration_ms=round(init_duration, 2),
        )

        succeeded = 0
        failed = 0
        skipped = len(self._errors)  # validation failures from init

        for wo in self._eligible:
            event = await self._process_one(wo)
            yield event
            if event.success:
                succeeded += 1
            else:
                failed += 1

        total_duration = (time.monotonic() - self._started_at) * 1000

        yield PipelineComplete(
            total_orders=len(self._eligible) + skipped,
            processed=succeeded + failed,
            succeeded=succeeded,
            failed=failed,
            skipped=skipped,
            errors=list(self._errors),
            duration_ms=round(total_duration, 2),
        )

    async def _process_one(self, wo: WorkOrder) -> OrderProcessed:
        """Advance a single work order through its next valid transition."""
        previous_status = wo.status

        try:
            # Determine target based on current status
            if wo.status == WorkOrderStatus.PENDING.value:
                target = WorkOrderStatus.IN_PROGRESS.value
            elif wo.status == WorkOrderStatus.IN_PROGRESS.value:
                target = WorkOrderStatus.COMPLETED.value
            else:
                return OrderProcessed(
                    order_id=wo.id,
                    ot_number=wo.ot_number,
                    previous_status=previous_status,
                    new_status=wo.status,
                    success=False,
                    error=f"Estado {wo.status} no procesable en COB",
                )

            # State machine validation
            validate_transition(wo.status, target)

            # Permission check
            if not perms.can_start(wo, self._user) and not perms.can_complete(wo, self._user):
                err = PermissionError(
                    message=f"Sin permiso para transición {previous_status}→{target} en OT {wo.ot_number}",
                    order_id=wo.id,
                    ot_number=wo.ot_number,
                )
                self._errors.append(err)
                return OrderProcessed(
                    order_id=wo.id,
                    ot_number=wo.ot_number,
                    previous_status=previous_status,
                    new_status=previous_status,
                    success=False,
                    error=err.message,
                )

            # Apply transition
            now = datetime.now(timezone.utc)
            wo.status = target

            if target == WorkOrderStatus.IN_PROGRESS.value:
                wo.started_at = now
                wo.started_by_user_id = self._user.id
            elif target == WorkOrderStatus.COMPLETED.value:
                wo.completed_at = now
                wo.completed_by_user_id = self._user.id
                if wo.started_at:
                    delta = now - wo.started_at
                    wo.actual_duration_minutes = round(delta.total_seconds() / 60, 2)

            await self._db.flush()

            return OrderProcessed(
                order_id=wo.id,
                ot_number=wo.ot_number,
                previous_status=previous_status,
                new_status=target,
                success=True,
            )

        except InvalidTransitionError as e:
            err = TransitionError(
                message=str(e),
                order_id=wo.id,
                ot_number=wo.ot_number,
                current_status=previous_status,
                target_status=target if 'target' in dir() else "unknown",
            )
            self._errors.append(err)
            return OrderProcessed(
                order_id=wo.id,
                ot_number=wo.ot_number,
                previous_status=previous_status,
                new_status=previous_status,
                success=False,
                error=str(e),
            )

        except Exception as e:
            err = COBError(
                code="PROCESSING_ERROR",
                message=f"Error procesando OT {wo.ot_number}: {e}",
                order_id=wo.id,
                ot_number=wo.ot_number,
            )
            self._errors.append(err)
            return OrderProcessed(
                order_id=wo.id,
                ot_number=wo.ot_number,
                previous_status=previous_status,
                new_status=previous_status,
                success=False,
                error=str(e),
            )


# ── Public factory (asynccontextmanager) ───────────────────────────────────

@asynccontextmanager
async def create_cob_session(
    db: AsyncSession,
    user: User,
) -> AsyncGenerator[COBSession, None]:
    """Create a managed COB session with proper resource lifecycle.

    Usage:
        async with create_cob_session(db, user) as session:
            async for event in session.run():
                ...
    """
    async with COBSession(db, user) as session:
        yield session
