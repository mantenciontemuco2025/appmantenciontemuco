from types import SimpleNamespace

from app.models.user import UserRole
from app.services.wo_permissions import can_review_supervisor


def _order(**overrides):
    values = {
        "requires_supervisor_validation": True,
        "status": "COMPLETED",
        "area_id": 10,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _user(**overrides):
    values = {"role": UserRole.SUPERVISOR, "area_ids": [10]}
    values.update(overrides)
    return SimpleNamespace(**values)


def test_area_supervisor_can_review_completed_supervisor_order():
    assert can_review_supervisor(_order(), _user()) is True


def test_supervisor_from_another_area_cannot_review():
    assert can_review_supervisor(_order(), _user(area_ids=[11])) is False


def test_regular_order_and_admin_do_not_use_supervisor_review():
    assert can_review_supervisor(_order(requires_supervisor_validation=False), _user()) is False
    assert can_review_supervisor(_order(), _user(role=UserRole.ADMIN)) is False
