"""Centralized state machine for Work Order transitions.

All status transitions MUST go through validate_transition() so the business
rules are enforced in one place — never trusted from the frontend.
"""

from app.models.work_order import WorkOrderStatus

# Allowed transitions: current_status -> [allowed target statuses]
VALID_TRANSITIONS: dict[str, list[str]] = {
    WorkOrderStatus.DRAFT: [WorkOrderStatus.PENDING, WorkOrderStatus.CANCELLED],
    WorkOrderStatus.PENDING: [WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.CANCELLED],
    WorkOrderStatus.IN_PROGRESS: [WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED],
    WorkOrderStatus.COMPLETED: [
        WorkOrderStatus.APPROVED,   # admin approves
        WorkOrderStatus.IN_PROGRESS,  # admin returns to worker
        WorkOrderStatus.CANCELLED,
    ],
    # Closed states can be REOPENED by an admin (reason required). Reopening an
    # APPROVED OT sends it back to the worker (IN_PROGRESS); a CANCELLED OT
    # reopens as a DRAFT so it can be re-planned and re-issued.
    WorkOrderStatus.APPROVED: [WorkOrderStatus.IN_PROGRESS],  # admin reopens
    WorkOrderStatus.CANCELLED: [WorkOrderStatus.DRAFT],  # admin reopens
}


class InvalidTransitionError(Exception):
    """Raised when a status transition is not allowed."""

    def __init__(self, current: str, target: str):
        self.current = current
        self.target = target
        allowed = VALID_TRANSITIONS.get(current, [])
        allowed_str = ", ".join(allowed) if allowed else "ninguna"
        super().__init__(
            f"Transición no válida: {current} → {target}. "
            f"Transiciones permitidas desde {current}: {allowed_str}"
        )


def validate_transition(current: str, target: str) -> bool:
    """Raise InvalidTransitionError if the transition is not allowed."""
    allowed = VALID_TRANSITIONS.get(current, [])
    if target not in allowed:
        raise InvalidTransitionError(current, target)
    return True


def allowed_transitions(current: str) -> list[str]:
    """Return the list of statuses that `current` can transition to."""
    return VALID_TRANSITIONS.get(current, [])
