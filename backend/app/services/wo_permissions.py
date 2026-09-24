"""Permission functions for Work Order operations.

Centralizes the authorization logic so routes stay thin and permissions are
tested in one place.  Every function takes a WorkOrder instance and the
current User; it returns True/False without raising.

Design rule (approved 2026-09-04):
  Permissions answer ONLY "who can do this?" (role + identity).
  The state machine answers "when can this happen?" (status transitions).
  This separation ensures 403 = wrong person, 400 = wrong status.
"""

from app.models.user import User, UserRole
from app.models.work_order import WorkOrder, WorkOrderStatus


def can_create(user: User) -> bool:
    """ADMIN and SUPERVISOR can create OTs."""
    return user.role in (UserRole.ADMIN, UserRole.SUPERVISOR)


def _is_in_supervisor_area(wo: WorkOrder, user: User) -> bool:
    """An assigned supervisor may only manage OTs from their area."""
    if user.role != UserRole.SUPERVISOR:
        return True
    area_ids = getattr(user, "area_ids", None)
    if area_ids is None:
        legacy_area_id = getattr(user, "area_id", None)
        area_ids = [legacy_area_id] if legacy_area_id is not None else []
    # Legacy users without configured scope are handled by the API gate; keep
    # the pure permission matrix backward-compatible for older callers/tests.
    return not area_ids or wo.area_id in area_ids


def can_edit(wo: WorkOrder, user: User) -> bool:
    """ADMIN/SUPERVISOR can edit every non-terminal OT, including completed OTs.

    This is needed so the administrator can correct worker-entered details
    before approving a completed OT. APPROVED and CANCELLED remain locked.
    """
    if wo.status in (WorkOrderStatus.APPROVED, WorkOrderStatus.CANCELLED):
        return False
    return user.role in (UserRole.ADMIN, UserRole.SUPERVISOR) and _is_in_supervisor_area(wo, user)


def can_issue(wo: WorkOrder, user: User) -> bool:
    """Emitir OT. ADMIN and SUPERVISOR only.

    Status is NOT checked — the state machine handles that.
    """
    return user.role in (UserRole.ADMIN, UserRole.SUPERVISOR) and _is_in_supervisor_area(wo, user)


def can_fulfill(wo: WorkOrder, user: User) -> bool:
    """The responsible worker completes the remaining detail fields of an OT.

    Allowed for ADMIN/SUPERVISOR always, and the responsible worker while the
    OT is DRAFT or PENDING (before work starts). The worker fills the details
    (type, loto, hours, resources, risks, participants, etc.) that the admin
    left empty at creation.
    """
    if wo.status in (WorkOrderStatus.APPROVED, WorkOrderStatus.CANCELLED):
        return False
    if user.role == UserRole.ADMIN:
        return True
    if user.role == UserRole.SUPERVISOR and _is_in_supervisor_area(wo, user):
        return True
    # Responsible worker can fulfill while it's still pending work
    if wo.status in (WorkOrderStatus.DRAFT, WorkOrderStatus.PENDING, WorkOrderStatus.IN_PROGRESS):
        return wo.responsible_user_id == user.id
    return False


def can_start(wo: WorkOrder, user: User) -> bool:
    """Start work (PENDING → IN_PROGRESS). ADMIN or the responsible user."""
    if user.role == UserRole.ADMIN:
        return True
    return wo.responsible_user_id == user.id


def can_complete(wo: WorkOrder, user: User) -> bool:
    """Complete work (IN_PROGRESS → COMPLETED). ADMIN or the responsible user.

    Status is NOT checked here — the state machine handles that.
    This ensures 403 = wrong person, 400 = wrong status.
    """
    if user.role == UserRole.ADMIN:
        return True
    return wo.responsible_user_id == user.id


def can_return_(wo: WorkOrder, user: User) -> bool:
    """Return OT to worker (COMPLETED → IN_PROGRESS). ADMIN only."""
    return user.role == UserRole.ADMIN


def can_approve(wo: WorkOrder, user: User) -> bool:
    """Approve/sign OT (COMPLETED → APPROVED). ADMIN only."""
    return user.role == UserRole.ADMIN


def can_review_supervisor(wo: WorkOrder, user: User) -> bool:
    """A supervisor from the OT area may review a supervisor-created OT."""
    if user.role != UserRole.SUPERVISOR or not wo.requires_supervisor_validation:
        return False
    if wo.status != WorkOrderStatus.COMPLETED.value:
        return False
    area_ids = getattr(user, "area_ids", None)
    if area_ids is None:
        legacy_area_id = getattr(user, "area_id", None)
        area_ids = [legacy_area_id] if legacy_area_id is not None else []
    # Review is intentionally strict: a supervisor must have an explicit
    # area assignment to validate work from that area.
    return bool(area_ids) and wo.area_id in area_ids


def can_cancel(wo: WorkOrder, user: User) -> bool:
    """Cancel OT. Only ADMIN can cancel, and not already-closed orders."""
    if wo.status in (WorkOrderStatus.APPROVED, WorkOrderStatus.CANCELLED):
        return False
    return user.role == UserRole.ADMIN


def can_view(wo: WorkOrder, user: User) -> bool:
    """ADMIN/SUPERVISOR see all.  WORKER sees only OTs where they are
    responsible or a participant."""
    if user.role == UserRole.ADMIN:
        return True
    if getattr(wo, "is_hallazgo_report", False) and wo.hallazgo_status != "CONVERTED":
        return user.role == UserRole.WORKER and wo.created_by_user_id == user.id
    if user.role == UserRole.SUPERVISOR and _is_in_supervisor_area(wo, user):
        return True
    if wo.responsible_user_id == user.id:
        return True
    try:
        participant_ids = [p.id for p in (wo.participants or [])]
        return user.id in participant_ids
    except Exception:
        return False


def can_reopen(wo: WorkOrder, user: User) -> bool:
    """Reopen a closed OT (APPROVED → IN_PROGRESS, CANCELLED → DRAFT). ADMIN only.

    Status is NOT checked here — the state machine handles that.
    """
    return user.role == UserRole.ADMIN


def can_sync_google(wo: WorkOrder, user: User) -> bool:
    """Re-sincronizar Google. ADMIN and SUPERVISOR."""
    return user.role in (UserRole.ADMIN, UserRole.SUPERVISOR) and _is_in_supervisor_area(wo, user)
