"""Add view/edit permissions for the water register module."""

from alembic import op
import sqlalchemy as sa


revision = "0028_water_register_permissions"
down_revision = "0027_user_water_register_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "water_register_access",
            sa.String(length=10),
            nullable=False,
            server_default=sa.text("'NONE'"),
        ),
    )
    # Los supervisores existentes ya utilizaban el mÃ³dulo; se conserva su
    # comportamiento actual. TambiÃ©n se conservan los trabajadores marcados
    # con el permiso booleano anterior.
    op.execute(
        sa.text(
            """
            UPDATE users
            SET water_register_access = 'EDIT'
            WHERE role::text IN ('ADMIN', 'SUPERVISOR')
               OR can_manage_water_register = TRUE
            """
        )
    )


def downgrade() -> None:
    op.drop_column("users", "water_register_access")
