from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MaterialCatalog(Base):
    """Searchable catalog of material codes used on work orders.

    This is a catalog only: it does not track quantities or stock levels.
    Work orders continue to keep their selected codes in ``material_codes``
    for compatibility with the Google Drive template.
    """

    __tablename__ = "material_catalog"
    __table_args__ = (
        UniqueConstraint("code", name="uq_material_catalog_code"),
        Index("ix_material_catalog_active_code", "active", "code"),
        Index("ix_material_catalog_family", "family"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    family: Mapped[str] = mapped_column(String(180), nullable=False, default="Sin familia")
    source_sheet: Mapped[str | None] = mapped_column(String(180), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
