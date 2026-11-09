"""Assign supervisors by plant area while preserving existing section scopes."""

from alembic import op
import sqlalchemy as sa


revision = "0046_supervisor_plant_area_scope"
down_revision = "0045_plant_area_active"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "supervisor_plant_areas",
        sa.Column("supervisor_id", sa.Integer(), nullable=False),
        sa.Column("plant_area_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["supervisor_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plant_area_id"], ["plant_areas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("supervisor_id", "plant_area_id"),
    )
    op.create_table(
        "supervisor_area_section_exclusions",
        sa.Column("supervisor_id", sa.Integer(), nullable=False),
        sa.Column("section_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["supervisor_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["areas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("supervisor_id", "section_id"),
    )

    connection = op.get_bind()
    supervisors = connection.execute(
        sa.text("SELECT id, area_id FROM users WHERE role = 'SUPERVISOR'")
    ).mappings()
    existing_assignments = connection.execute(
        sa.text("SELECT supervisor_id, area_id FROM supervisor_areas")
    ).all()
    linked_sections = connection.execute(
        sa.text("SELECT plant_area_id, section_id FROM plant_area_sections")
    ).all()

    links_by_area: dict[int, set[int]] = {}
    areas_by_section: dict[int, set[int]] = {}
    for plant_area_id, section_id in linked_sections:
        links_by_area.setdefault(plant_area_id, set()).add(section_id)
        areas_by_section.setdefault(section_id, set()).add(plant_area_id)

    assignments_by_user: dict[int, set[int]] = {}
    for supervisor_id, section_id in existing_assignments:
        assignments_by_user.setdefault(supervisor_id, set()).add(section_id)

    insert_area = sa.text(
        "INSERT INTO supervisor_plant_areas (supervisor_id, plant_area_id) VALUES (:user_id, :area_id)"
    )
    insert_exclusion = sa.text(
        "INSERT INTO supervisor_area_section_exclusions (supervisor_id, section_id) VALUES (:user_id, :section_id)"
    )
    delete_mapped = sa.text(
        "DELETE FROM supervisor_areas WHERE supervisor_id = :user_id AND area_id = :section_id"
    )
    insert_legacy = sa.text(
        "INSERT INTO supervisor_areas (supervisor_id, area_id) VALUES (:user_id, :section_id) ON CONFLICT DO NOTHING"
    )

    for supervisor in supervisors:
        user_id = supervisor["id"]
        assigned_sections = assignments_by_user.setdefault(user_id, set())
        if supervisor["area_id"] is not None:
            assigned_sections.add(supervisor["area_id"])

        selected_parent_areas = {
            plant_area_id
            for section_id in assigned_sections
            for plant_area_id in areas_by_section.get(section_id, set())
        }
        mapped_sections: set[int] = set()
        for plant_area_id in selected_parent_areas:
            connection.execute(insert_area, {"user_id": user_id, "area_id": plant_area_id})
            allowed_in_area = links_by_area[plant_area_id] & assigned_sections
            mapped_sections.update(allowed_in_area)
            for section_id in links_by_area[plant_area_id] - allowed_in_area:
                connection.execute(insert_exclusion, {"user_id": user_id, "section_id": section_id})

        # Sections without a parent area remain explicitly assigned as before.
        # Linked sections are represented by parent grants plus exclusions,
        # keeping each supervisor's effective scope unchanged.
        for section_id in assigned_sections - mapped_sections:
            connection.execute(insert_legacy, {"user_id": user_id, "section_id": section_id})
        for section_id in mapped_sections:
            connection.execute(delete_mapped, {"user_id": user_id, "section_id": section_id})

    connection.execute(
        sa.text("UPDATE users SET area_id = NULL WHERE role = 'SUPERVISOR'")
    )


def downgrade() -> None:
    connection = op.get_bind()
    grant_rows = connection.execute(
        sa.text("SELECT supervisor_id, plant_area_id FROM supervisor_plant_areas")
    ).all()
    excluded_rows = connection.execute(
        sa.text("SELECT supervisor_id, section_id FROM supervisor_area_section_exclusions")
    ).all()
    links = connection.execute(
        sa.text("SELECT plant_area_id, section_id FROM plant_area_sections")
    ).all()
    sections_by_area: dict[int, set[int]] = {}
    for plant_area_id, section_id in links:
        sections_by_area.setdefault(plant_area_id, set()).add(section_id)
    excluded_by_user: dict[int, set[int]] = {}
    for supervisor_id, section_id in excluded_rows:
        excluded_by_user.setdefault(supervisor_id, set()).add(section_id)

    insert_legacy = sa.text(
        "INSERT INTO supervisor_areas (supervisor_id, area_id) VALUES (:user_id, :section_id) ON CONFLICT DO NOTHING"
    )
    for supervisor_id, plant_area_id in grant_rows:
        allowed = sections_by_area.get(plant_area_id, set()) - excluded_by_user.get(supervisor_id, set())
        for section_id in allowed:
            connection.execute(insert_legacy, {"user_id": supervisor_id, "section_id": section_id})

    connection.execute(
        sa.text(
            "UPDATE users SET area_id = (SELECT min(area_id) FROM supervisor_areas WHERE supervisor_id = users.id) WHERE role = 'SUPERVISOR'"
        )
    )

    op.drop_table("supervisor_area_section_exclusions")
    op.drop_table("supervisor_plant_areas")
