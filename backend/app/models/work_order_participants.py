"""Association table for WorkOrder <-> User (participants).

Separates the M2M relationship from the legacy comma-separated participant_names
TEXT column which is kept for Google Sheets sync compatibility.
"""

from sqlalchemy import Column, ForeignKey, Table

from app.db.base import Base

work_order_participants = Table(
    "work_order_participants",
    Base.metadata,
    Column(
        "work_order_id",
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "user_id",
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)
