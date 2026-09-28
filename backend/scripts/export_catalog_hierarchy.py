"""Export the current plant-area/section/equipment catalog for review.

Read-only utility. It does not insert, update, or delete anything.
Run from backend/ with the project's virtual environment so the normal .env
and database configuration are used.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.db.session import async_session, engine
from app.models.area import Area
from app.models.equipment import Equipment
from app.models.plant_area import PlantArea, plant_area_sections


def clean(value: object | None) -> str:
    return " ".join(str(value or "").strip().split())


def key(value: object | None) -> str:
    text = clean(value)
    return "".join(
        char
        for char in unicodedata.normalize("NFD", text).casefold()
        if unicodedata.category(char) != "Mn"
    )


async def export_catalog(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    async with async_session() as db:
        equipment_rows = (
            await db.execute(
                select(Equipment, Area, PlantArea)
                .join(Area, Equipment.area_id == Area.id)
                .outerjoin(PlantArea, Equipment.plant_area_id == PlantArea.id)
                .order_by(PlantArea.name, Area.name, Equipment.name, Equipment.id)
            )
        ).all()
        section_rows = (
            await db.execute(
                select(PlantArea, Area)
                .join(
                    plant_area_sections,
                    plant_area_sections.c.plant_area_id == PlantArea.id,
                )
                .join(Area, plant_area_sections.c.section_id == Area.id)
                .order_by(PlantArea.name, Area.name)
            )
        ).all()

    catalog_rows: list[dict[str, str | int]] = []
    for equipment, section, plant_area in equipment_rows:
        catalog_rows.append(
            {
                "db_equipment_id": equipment.id,
                "inventory_code": clean(equipment.inventory_code),
                "plant_area": clean(plant_area.name if plant_area else ""),
                "section": clean(section.name),
                "equipment": clean(equipment.name),
                "category": clean(equipment.category),
                "location": clean(equipment.location),
                "operational_status": clean(equipment.operational_status),
            }
        )

    section_catalog = [
        {
            "plant_area_id": plant_area.id,
            "plant_area": clean(plant_area.name),
            "section_id": section.id,
            "section": clean(section.name),
        }
        for plant_area, section in section_rows
    ]

    equipment_csv = output_dir / "catalogo_equipos.csv"
    with equipment_csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(catalog_rows[0]) if catalog_rows else [
            "db_equipment_id", "inventory_code", "plant_area", "section", "equipment",
            "category", "location", "operational_status",
        ])
        writer.writeheader()
        writer.writerows(catalog_rows)

    sections_csv = output_dir / "catalogo_secciones.csv"
    with sections_csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["plant_area_id", "plant_area", "section_id", "section"],
        )
        writer.writeheader()
        writer.writerows(section_catalog)

    def grouped(field_names: tuple[str, ...]) -> dict[tuple[str, ...], list[dict[str, str | int]]]:
        groups: dict[tuple[str, ...], list[dict[str, str | int]]] = defaultdict(list)
        for row in catalog_rows:
            groups[tuple(key(row[field]) for field in field_names)].append(row)
        return groups

    duplicate_codes = {
        code: rows
        for code, rows in grouped(("inventory_code",)).items()
        if code[0] and len(rows) > 1
    }
    duplicate_same_location = {
        group: rows
        for group, rows in grouped(("plant_area", "section", "equipment")).items()
        if all(group) and len(rows) > 1
    }
    repeated_across_plant_areas: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in catalog_rows:
        section_equipment = (key(row["section"]), key(row["equipment"]))
        repeated_across_plant_areas[section_equipment].add(key(row["plant_area"]))
    repeated_across_plant_areas = {
        group: areas
        for group, areas in repeated_across_plant_areas.items()
        if all(group) and len({area for area in areas if area}) > 1
    }

    incomplete = [
        row
        for row in catalog_rows
        if not key(row["plant_area"])
        or not key(row["section"])
        or not key(row["equipment"])
    ]
    missing_inventory_code = [row for row in catalog_rows if not key(row["inventory_code"])]

    summary = output_dir / "catalogo_resumen.txt"
    with summary.open("w", encoding="utf-8") as handle:
        handle.write("EXPORTACIÓN DE CATÁLOGO DE ÁREA, SECCIÓN Y EQUIPO\n")
        handle.write(f"Generado: {datetime.now().isoformat(timespec='seconds')}\n")
        handle.write("Modo: solo lectura; no se modificó la base de datos.\n\n")
        handle.write(f"Equipos registrados: {len(catalog_rows)}\n")
        handle.write(f"Relaciones área-sección: {len(section_catalog)}\n")
        handle.write(f"Códigos de inventario repetidos: {len(duplicate_codes)}\n")
        handle.write(f"Duplicados exactos en misma área/sección: {len(duplicate_same_location)}\n")
        handle.write(
            "Mismo equipo en más de un área de planta: "
            f"{len(repeated_across_plant_areas)}\n"
        )
        handle.write(f"Registros incompletos: {len(incomplete)}\n")
        handle.write(f"Equipos sin código de inventario: {len(missing_inventory_code)}\n\n")

        if duplicate_codes:
            handle.write("CÓDIGOS REPETIDOS\n")
            for code, rows in sorted(duplicate_codes.items()):
                handle.write(
                    f"- {code}: "
                    + " | ".join(
                        f"{row['plant_area']} / {row['section']} / {row['equipment']} "
                        f"(db_id {row['db_equipment_id']})"
                        for row in rows
                    )
                    + "\n"
                )

        if duplicate_same_location:
            handle.write("\nDUPLICADOS EN LA MISMA ÁREA Y SECCIÓN\n")
            for _, rows in sorted(duplicate_same_location.items()):
                row = rows[0]
                handle.write(
                    f"- {row['plant_area']} / {row['section']} / {row['equipment']}: "
                    + ", ".join(str(item["inventory_code"] or f"db_id {item['db_equipment_id']}") for item in rows)
                    + "\n"
                )

        if repeated_across_plant_areas:
            handle.write("\nMISMO EQUIPO Y SECCIÓN EN DISTINTAS ÁREAS\n")
            for (section_name, equipment_name), areas in sorted(repeated_across_plant_areas.items()):
                handle.write(
                    f"- {section_name} / {equipment_name}: "
                    + ", ".join(sorted(area for area in areas if area))
                    + "\n"
                )

        if incomplete:
            handle.write("\nREGISTROS INCOMPLETOS\n")
            for row in incomplete:
                handle.write(
                    f"- db_id {row['db_equipment_id']}: "
                    f"área={row['plant_area']!r}, sección={row['section']!r}, "
                    f"equipo={row['equipment']!r}\n"
                )

    print(f"Exportación lista: {output_dir.resolve()}")
    print(f"- {equipment_csv.name}: {len(catalog_rows)} equipos")
    print(f"- {sections_csv.name}: {len(section_catalog)} relaciones área-sección")
    print(f"- {summary.name}: resumen y posibles problemas")


def main() -> None:
    parser = argparse.ArgumentParser(description="Exporta el catálogo jerárquico sin modificar la BD")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("catalog_export_" + datetime.now().strftime("%Y%m%d_%H%M%S")),
        help="Carpeta de salida; por defecto se crea una carpeta con fecha y hora",
    )
    args = parser.parse_args()
    async def run() -> None:
        try:
            await export_catalog(args.output)
        finally:
            await engine.dispose()

    asyncio.run(run())


if __name__ == "__main__":
    main()
