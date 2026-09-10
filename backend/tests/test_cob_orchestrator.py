"""Tests for the COB (Close of Business) E2E orchestrator.

Covers the modern-Python orchestration layer:
  - asynccontextmanager lifecycle (commit on success, rollback on error)
  - TaskGroup concurrent validation with ExceptionGroup propagation
  - Streaming pipeline events (InitComplete → OrderProcessed × N → PipelineComplete)
  - Structured errors (ValidationError, TransitionError, PermissionError)
"""

import asyncio

import pytest

from sqlalchemy import select

from app.services.cob_orchestrator import (
    create_cob_session,
    COBSession,
    InitComplete,
    OrderProcessed,
    PipelineComplete,
    ValidationError,
    TransitionError,
    COBError,
)
from app.models.work_order import WorkOrder, WorkOrderStatus
from app.models.user import UserRole


def _user(role=UserRole.ADMIN, uid=1):
    from app.models.user import User
    return User(id=uid, full_name="Orch", email="orch@test.com", role=role)


_ot_seq = 0

async def _seed_wo(db, *, status, responsible_user_id=None, area_id=None, title="OT",
                    created_by_user_id=1):
    global _ot_seq
    _ot_seq += 1
    wo = WorkOrder(
        ot_number=f"ORCH-{_ot_seq:04d}",
        title=title,
        description="x",
        area_id=area_id or 1,
        maintenance_type="PREVENTIVE",
        status=status,
        responsible_user_id=responsible_user_id,
        created_by_user_id=created_by_user_id,
    )
    db.add(wo)
    await db.flush()
    return wo


# ── Unit tests (no DB) ──────────────────────────────────────────────────────

class TestStructuredErrors:
    def test_error_slots(self):
        err = ValidationError("bad", order_id=1, ot_number="OT-1")
        assert err.code == "VALIDATION_ERROR"
        assert err.order_id == 1
        assert err.message == "bad"
        assert str(err) == "bad"

    def test_transition_error_code(self):
        err = TransitionError(
            "x", current_status="PENDING", target_status="APPROVED"
        )
        assert err.code == "TRANSITION_ERROR"
        assert err.current_status == "PENDING"
        assert err.target_status == "APPROVED"

    def test_error_isinstance_cob(self):
        assert isinstance(ValidationError("m"), COBError)
        assert isinstance(ValidationError("m"), Exception)


# ── Integration tests (real DB session) ────────────────────────────────────

class TestCOBSession:
    @pytest.mark.asyncio
    async def test_init_loads_eligible_orders(self, db_session_factory, seed_data):
        async with db_session_factory() as db:
            await _seed_wo(db, status="PENDING", responsible_user_id=seed_data["worker"].id,
                           area_id=seed_data["area"].id, title="W1")
            await _seed_wo(db, status="IN_PROGRESS", responsible_user_id=seed_data["worker"].id,
                           area_id=seed_data["area"].id, title="W2")
            await _seed_wo(db, status="APPROVED", area_id=seed_data["area"].id, title="W3")
            await db.commit()

        async with db_session_factory() as db:
            async with create_cob_session(db, _user()) as session:
                assert session._eligible  # 2 eligible (PENDING, IN_PROGRESS)
                assert len(session._eligible) == 2

    @pytest.mark.asyncio
    async def test_streaming_pipeline_yields_events(self, db_session_factory, seed_data):
        """The pipeline yields InitComplete, two OrderProcessed, PipelineComplete."""
        async with db_session_factory() as db:
            await _seed_wo(db, status="PENDING", responsible_user_id=seed_data["worker"].id,
                           area_id=seed_data["area"].id, title="A")
            await _seed_wo(db, status="IN_PROGRESS", responsible_user_id=seed_data["worker"].id,
                           area_id=seed_data["area"].id, title="B")
            await db.commit()

        collected = []
        async with db_session_factory() as db:
            async with create_cob_session(db, _user(role=UserRole.ADMIN)) as session:
                async for event in session.run():
                    collected.append(event)

        assert isinstance(collected[0], InitComplete)
        assert collected[0].eligible_orders == 2
        processed = [e for e in collected if isinstance(e, OrderProcessed)]
        assert len(processed) == 2
        assert all(e.success for e in processed)
        assert all(e.new_status == e.new_status is not None for e in processed)
        final = collected[-1]
        assert isinstance(final, PipelineComplete)
        assert final.succeeded == 2
        assert final.failed == 0
        assert final.errors == []

    @pytest.mark.asyncio
    async def test_pipeline_applies_transitions_in_db(self, db_session_factory, seed_data):
        """After run(), PENDING order is now IN_PROGRESS, IN_PROGRESS is COMPLETED."""
        async with db_session_factory() as db:
            await _seed_wo(db, status="PENDING", responsible_user_id=seed_data["worker"].id,
                           area_id=seed_data["area"].id, title="P1")
            await _seed_wo(db, status="IN_PROGRESS", responsible_user_id=seed_data["worker"].id,
                           area_id=seed_data["area"].id, title="I1")
            await db.commit()

        async with db_session_factory() as db:
            async with create_cob_session(db, _user(role=UserRole.ADMIN)) as session:
                async for _ in session.run():
                    pass

        async with db_session_factory() as db:
            # Re-query to confirm committed state
            result = await db.execute(select(WorkOrder).where(WorkOrder.title.in_(["P1", "I1"])))
            rows = {wo.title: wo for wo in result.scalars().all()}
            assert rows["P1"].status == WorkOrderStatus.IN_PROGRESS.value
            assert rows["I1"].status == WorkOrderStatus.COMPLETED.value

    @pytest.mark.asyncio
    async def test_terminated_orders_skipped(self, db_session_factory, seed_data):
        """APPROVED/CANCELLED orders are not processed."""
        async with db_session_factory() as db:
            await _seed_wo(db, status="APPROVED", area_id=seed_data["area"].id, title="APP")
            await _seed_wo(db, status="CANCELLED", area_id=seed_data["area"].id, title="CAN")
            await db.commit()

        async with db_session_factory() as db:
            async with create_cob_session(db, _user(role=UserRole.ADMIN)) as session:
                assert session._eligible == []

    @pytest.mark.asyncio
    async def test_permission_denied_sets_error(self, db_session_factory, seed_data):
        """A WORKER (non-responsible) cannot run the COB pipeline."""
        async with db_session_factory() as db:
            await _seed_wo(db, status="PENDING", responsible_user_id=seed_data["worker"].id,
                           area_id=seed_data["area"].id, title="WO1")
            await db.commit()

        collected = []
        async with db_session_factory() as db:
            async with create_cob_session(db, _user(role=UserRole.WORKER, uid=9999)) as session:
                async for event in session.run():
                    collected.append(event)

        processed = [e for e in collected if isinstance(e, OrderProcessed)]
        assert processed and all(not e.success for e in processed)
        final = collected[-1]
        assert final.failed == 1
        assert any(e.code == "PERMISSION_ERROR" for e in final.errors)

    @pytest.mark.asyncio
    async def test_asynccontextmanager_rolls_back_on_error(self, db_session_factory, seed_data):
        """If the pipeline body raises, the session rolls back (no partial commit)."""
        async with db_session_factory() as db:
            await _seed_wo(db, status="PENDING", responsible_user_id=seed_data["worker"].id,
                           area_id=seed_data["area"].id, title="E1")
            await db.commit()

        with pytest.raises(RuntimeError, match="boom"):
            async with db_session_factory() as db:
                async with create_cob_session(db, _user(role=UserRole.ADMIN)) as session:
                    async for _ in session.run():
                        raise RuntimeError("boom")

        async with db_session_factory() as db:
            # Order must still be PENDING (rolled back)
            result = await db.execute(select(WorkOrder).where(WorkOrder.title == "E1"))
            wo = result.scalar_one()
            assert wo.status == WorkOrderStatus.PENDING.value
            assert wo.started_at is None