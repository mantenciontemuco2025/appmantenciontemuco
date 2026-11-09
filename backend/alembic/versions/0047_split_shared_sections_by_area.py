"""Give each linked plant area its own section row.

Historical work orders keep their original section IDs. Equipment already
assigned to a plant area moves to that area's new row; equipment without an
area stays on the original unassigned section for deliberate reassignment.
"""

from alembic import op
import sqlalchemy as sa


revision = "0047_split_sections"
down_revision = "0046_supervisor_plant_area_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("areas_name_key", "areas", type_="unique")
    op.create_table(
        "area_section_split_map",
        sa.Column("split_section_id", sa.Integer(), nullable=False),
        sa.Column("source_section_id", sa.Integer(), nullable=False),
        sa.Column("plant_area_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["split_section_id"], ["areas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_section_id"], ["areas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plant_area_id"], ["plant_areas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("split_section_id"),
    )

    connection = op.get_bind()
    links = connection.execute(
        sa.text(
            """
            SELECT pas.section_id, pas.plant_area_id, a.name
            FROM plant_area_sections AS pas
            JOIN areas AS a ON a.id = pas.section_id
            ORDER BY pas.section_id, pas.plant_area_id
            """
        )
    ).all()
    links_by_section: dict[int, list[tuple[int, str]]] = {}
    for section_id, plant_area_id, section_name in links:
        links_by_section.setdefault(section_id, []).append((plant_area_id, section_name))

    for source_section_id, parent_areas in links_by_section.items():
        if len(parent_areas) < 2:
            continue

        source_name = parent_areas[0][1]
        connection.execute(
            sa.text("DELETE FROM plant_area_sections WHERE section_id = :section_id"),
            {"section_id": source_section_id},
        )
        for plant_area_id, _ in parent_areas:
            split_section_id = connection.execute(
                sa.text(
                    """
                    INSERT INTO areas (name, created_at, updated_at)
                    VALUES (:name, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    RETURNING id
                    """
                ),
                {"name": source_name},
            ).scalar_one()
            connection.execute(
                sa.text(
                    "INSERT INTO plant_area_sections (plant_area_id, section_id) VALUES (:plant_area_id, :section_id)"
                ),
                {"plant_area_id": plant_area_id, "section_id": split_section_id},
            )
            connection.execute(
                sa.text(
                    """
                    UPDATE equipment
                    SET area_id = :split_section_id, updated_at = CURRENT_TIMESTAMP
                    WHERE area_id = :source_section_id
                      AND plant_area_id = :plant_area_id
                    """
                ),
                {
                    "split_section_id": split_section_id,
                    "source_section_id": source_section_id,
                    "plant_area_id": plant_area_id,
                },
            )
            # Preserve explicit legacy section grants and per-section
            # exclusions when an old shared section receives new IDs.
            connection.execute(
                sa.text(
                    """
                    INSERT INTO supervisor_areas (supervisor_id, area_id)
                    SELECT supervisor_id, :split_section_id
                    FROM supervisor_areas
                    WHERE area_id = :source_section_id
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"split_section_id": split_section_id, "source_section_id": source_section_id},
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO supervisor_area_section_exclusions (supervisor_id, section_id)
                    SELECT supervisor_id, :split_section_id
                    FROM supervisor_area_section_exclusions
                    WHERE section_id = :source_section_id
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"split_section_id": split_section_id, "source_section_id": source_section_id},
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO area_section_split_map
                        (split_section_id, source_section_id, plant_area_id)
                    VALUES (:split_section_id, :source_section_id, :plant_area_id)
                    """
                ),
                {
                    "split_section_id": split_section_id,
                    "source_section_id": source_section_id,
                    "plant_area_id": plant_area_id,
                },
            )


def downgrade() -> None:
    connection = op.get_bind()
    mappings = connection.execute(
        sa.text(
            "SELECT split_section_id, source_section_id, plant_area_id FROM area_section_split_map"
        )
    ).all()
    for split_section_id, source_section_id, plant_area_id in mappings:
        connection.execute(
            sa.text(
                "UPDATE equipment SET area_id = :source_section_id, updated_at = CURRENT_TIMESTAMP WHERE area_id = :split_section_id"
            ),
            {"source_section_id": source_section_id, "split_section_id": split_section_id},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO plant_area_sections (plant_area_id, section_id)
                VALUES (:plant_area_id, :source_section_id)
                ON CONFLICT DO NOTHING
                """
            ),
            {"plant_area_id": plant_area_id, "source_section_id": source_section_id},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO supervisor_areas (supervisor_id, area_id)
                SELECT supervisor_id, :source_section_id
                FROM supervisor_areas
                WHERE area_id = :split_section_id
                ON CONFLICT DO NOTHING
                """
            ),
            {"source_section_id": source_section_id, "split_section_id": split_section_id},
        )
        connection.execute(
            sa.text(
                "DELETE FROM supervisor_areas WHERE area_id = :split_section_id"
            ),
            {"split_section_id": split_section_id},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO supervisor_area_section_exclusions (supervisor_id, section_id)
                SELECT supervisor_id, :source_section_id
                FROM supervisor_area_section_exclusions
                WHERE section_id = :split_section_id
                ON CONFLICT DO NOTHING
                """
            ),
            {"source_section_id": source_section_id, "split_section_id": split_section_id},
        )
        connection.execute(
            sa.text(
                "DELETE FROM supervisor_area_section_exclusions WHERE section_id = :split_section_id"
            ),
            {"split_section_id": split_section_id},
        )
        connection.execute(
            sa.text("DELETE FROM areas WHERE id = :section_id"),
            {"section_id": split_section_id},
        )
    op.drop_table("area_section_split_map")
    op.create_unique_constraint("areas_name_key", "areas", ["name"])
