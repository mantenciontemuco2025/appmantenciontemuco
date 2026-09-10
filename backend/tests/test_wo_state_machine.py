"""Unit tests for the centralized Work Order state machine + permission matrix."""

import pytest

from app.services.wo_state_machine import (
    validate_transition,
    InvalidTransitionError,
    allowed_transitions,
    VALID_TRANSITIONS,
)
from app.models.user import User, UserRole
from app.services import wo_permissions as perms
from app.models.work_order import WorkOrderStatus


# ── State machine ───────────────────────────────────────────────────────────

class TestStateMachine:
    def test_valid_transitions(self):
        assert VALID_TRANSITIONS[WorkOrderStatus.DRAFT] == [
            WorkOrderStatus.PENDING, WorkOrderStatus.CANCELLED,
        ]
        assert VALID_TRANSITIONS[WorkOrderStatus.PENDING] == [
            WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.CANCELLED,
        ]
        assert VALID_TRANSITIONS[WorkOrderStatus.IN_PROGRESS] == [
            WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED,
        ]
        assert WorkOrderStatus.APPROVED in VALID_TRANSITIONS[WorkOrderStatus.COMPLETED]
        assert WorkOrderStatus.IN_PROGRESS in VALID_TRANSITIONS[WorkOrderStatus.COMPLETED]

    def test_closed_states_can_be_reopened(self):
        # APPROVED reopens to IN_PROGRESS (back to the worker)
        assert VALID_TRANSITIONS[WorkOrderStatus.APPROVED] == [WorkOrderStatus.IN_PROGRESS]
        # CANCELLED reopens to DRAFT (re-plan and re-issue)
        assert VALID_TRANSITIONS[WorkOrderStatus.CANCELLED] == [WorkOrderStatus.DRAFT]

    def test_validate_accepts_valid(self):
        assert validate_transition(WorkOrderStatus.DRAFT, WorkOrderStatus.PENDING) is True
        assert validate_transition(WorkOrderStatus.PENDING, WorkOrderStatus.IN_PROGRESS) is True
        assert validate_transition(WorkOrderStatus.COMPLETED, WorkOrderStatus.APPROVED) is True
        assert validate_transition(WorkOrderStatus.COMPLETED, WorkOrderStatus.IN_PROGRESS) is True
        # Reopen transitions
        assert validate_transition(WorkOrderStatus.APPROVED, WorkOrderStatus.IN_PROGRESS) is True
        assert validate_transition(WorkOrderStatus.CANCELLED, WorkOrderStatus.DRAFT) is True

    @pytest.mark.parametrize("current,target", [
        ("PENDING", "APPROVED"),          # must be IN_PROGRESS→COMPLETED first
        ("DRAFT", "IN_PROGRESS"),         # skip emission
        ("IN_PROGRESS", "APPROVED"),      # skip completion
        ("APPROVED", "COMPLETED"),        # closed state cannot be advanced directly
        ("CANCELLED", "PENDING"),         # cancelled reopens only to DRAFT
        ("COMPLETED", "COMPLETED"),       # no self-transition
    ])
    def test_validate_rejects_invalid(self, current, target):
        with pytest.raises(InvalidTransitionError) as exc_info:
            validate_transition(current, target)
        assert str(exc_info.value)

    def test_allowed_transitions(self):
        assert allowed_transitions("PENDING") == ["IN_PROGRESS", "CANCELLED"]
        assert allowed_transitions("APPROVED") == ["IN_PROGRESS"]
        assert allowed_transitions("CANCELLED") == ["DRAFT"]
        assert allowed_transitions("UNKNOWN") == []


# ── Permission matrix ──────────────────────────────────────────────────────

def _user(role: UserRole, uid: int = 1) -> User:
    return User(id=uid, full_name="X", email="x@test.com", role=role)


class _Stub:
    """Generic attribute holder for test doubles."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class _WOStub:
    """Lightweight stand-in for WorkOrder carrying just the fields the
    permission functions read."""
    def __init__(self, status, responsible_user_id=None, participants=None):
        self.status = status
        self.responsible_user_id = responsible_user_id
        # can_view accesses p.id on each participant
        self.participants = [_Stub(id=uid) for uid in (participants or [])]


def _wo(status: str, responsible_user_id: int | None = None, participants: list[int] | None = None):
    return _WOStub(status, responsible_user_id, participants)


class TestPermissionMatrix:
    def test_can_create(self):
        assert perms.can_create(_user(UserRole.ADMIN)) is True
        assert perms.can_create(_user(UserRole.SUPERVISOR)) is True
        assert perms.can_create(_user(UserRole.WORKER)) is False

    def test_can_issue(self):
        wo = _wo("DRAFT")
        assert perms.can_issue(wo, _user(UserRole.ADMIN)) is True
        assert perms.can_issue(wo, _user(UserRole.SUPERVISOR)) is True
        assert perms.can_issue(wo, _user(UserRole.WORKER)) is False
        # Status check removed from permission (state machine handles it)
        assert perms.can_issue(_wo("PENDING"), _user(UserRole.ADMIN)) is True

    def test_can_fulfill(self):
        # Responsible worker can fulfill details while DRAFT/PENDING/IN_PROGRESS
        wo = _wo("PENDING", responsible_user_id=5)
        assert perms.can_fulfill(wo, _user(UserRole.ADMIN)) is True
        assert perms.can_fulfill(wo, _user(UserRole.SUPERVISOR)) is True
        assert perms.can_fulfill(wo, _user(UserRole.WORKER, uid=5)) is True    # responsible
        assert perms.can_fulfill(wo, _user(UserRole.WORKER, uid=6)) is False   # other worker
        # Terminal states are locked
        assert perms.can_fulfill(_wo("APPROVED", 5), _user(UserRole.WORKER, uid=5)) is False
        assert perms.can_fulfill(_wo("CANCELLED", 5), _user(UserRole.ADMIN)) is False

    def test_can_start_admin_and_responsible(self):
        wo = _wo("PENDING", responsible_user_id=5)
        assert perms.can_start(wo, _user(UserRole.ADMIN)) is True
        assert perms.can_start(wo, _user(UserRole.WORKER, uid=5)) is True          # responsible
        assert perms.can_start(wo, _user(UserRole.WORKER, uid=6)) is False          # other worker
        # Status removed from permission (state machine handles it)
        assert perms.can_start(_wo("IN_PROGRESS", 5), _user(UserRole.ADMIN)) is True

    def test_can_approve_admin_only(self):
        wo = _wo("COMPLETED")
        assert perms.can_approve(wo, _user(UserRole.ADMIN)) is True
        assert perms.can_approve(wo, _user(UserRole.SUPERVISOR)) is False
        assert perms.can_approve(wo, _user(UserRole.WORKER)) is False
        # Status removed from permission (state machine handles it)
        assert perms.can_approve(_wo("IN_PROGRESS"), _user(UserRole.ADMIN)) is True

    def test_can_return_admin_only(self):
        wo = _wo("COMPLETED")
        assert perms.can_return_(wo, _user(UserRole.ADMIN)) is True
        assert perms.can_return_(wo, _user(UserRole.WORKER)) is False

    def test_can_cancel(self):
        assert perms.can_cancel(_wo("PENDING"), _user(UserRole.ADMIN)) is True
        assert perms.can_cancel(_wo("PENDING"), _user(UserRole.SUPERVISOR)) is True
        assert perms.can_cancel(_wo("PENDING"), _user(UserRole.WORKER)) is False
        # Cannot cancel terminal
        assert perms.can_cancel(_wo("APPROVED"), _user(UserRole.ADMIN)) is False
        assert perms.can_cancel(_wo("CANCELLED"), _user(UserRole.ADMIN)) is False

    def test_can_reopen_admin_only(self):
        # ADMIN can reopen; status is handled by the state machine
        assert perms.can_reopen(_wo("APPROVED"), _user(UserRole.ADMIN)) is True
        assert perms.can_reopen(_wo("CANCELLED"), _user(UserRole.ADMIN)) is True
        assert perms.can_reopen(_wo("APPROVED"), _user(UserRole.SUPERVISOR)) is False
        assert perms.can_reopen(_wo("APPROVED"), _user(UserRole.WORKER)) is False

    def test_can_view(self):
        wo = _wo("PENDING", responsible_user_id=5, participants=[7, 8])
        assert perms.can_view(wo, _user(UserRole.ADMIN)) is True
        assert perms.can_view(wo, _user(UserRole.SUPERVISOR)) is True
        assert perms.can_view(wo, _user(UserRole.WORKER, uid=5)) is True   # responsible
        assert perms.can_view(wo, _user(UserRole.WORKER, uid=7)) is True   # participant
        assert perms.can_view(wo, _user(UserRole.WORKER, uid=9)) is False  # not assigned