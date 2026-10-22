from datetime import date
from decimal import Decimal

import pytest

from app.services.hazardous_waste_sheet import _find_insert_row, _quantity_text, parse_spreadsheet_id
from tests.conftest import auth_headers, get_token


def test_parse_google_sheet_url():
    assert parse_spreadsheet_id("https://docs.google.com/spreadsheets/d/1XksaPDWi--vnvervuwG0w0wEAH5kogUT4_NA8VAkSXY/edit") == "1XksaPDWi--vnvervuwG0w0wEAH5kogUT4_NA8VAkSXY"


def test_reject_invalid_google_sheet_link():
    with pytest.raises(ValueError):
        parse_spreadsheet_id("https://example.com/not-a-sheet")


@pytest.mark.parametrize(
    ("quantity", "expected"),
    [
        (Decimal("25.000"), "25 UNIDADES"),
        (Decimal("2.500"), "2,5 UNIDADES"),
        (Decimal("1234.560"), "1.234,56 UNIDADES"),
        (Decimal("0.005"), "0,005 UNIDADES"),
        (Decimal("25000"), "25.000 UNIDADES"),
    ],
)
def test_quantity_format_removes_only_insignificant_zeroes(quantity, expected):
    assert _quantity_text(quantity, "unidades") == expected


def test_missing_quantity_remains_blank():
    assert _quantity_text(None, "unidades") == ""


def test_quantity_without_legacy_unit_is_written_as_units():
    assert _quantity_text(Decimal("4.000"), "") == "4 UNIDADES"


def test_historical_record_is_inserted_before_the_first_later_date():
    values = [
        ["PLANILLA RESPEL"],
        ["FECHA INGRESO", "N° RESPEL", "NOMBRE RESPEL"],
        ["01/01/2026", "R-1", "ACEITE"],
        ["01/03/2026", "R-2", "BATERÍAS"],
    ]

    assert _find_insert_row(values, date(2026, 2, 1), first_data_row=3) == (4, True)


def test_historical_record_reuses_an_existing_blank_row():
    values = [
        ["PLANILLA RESPEL"],
        ["FECHA INGRESO", "N° RESPEL", "NOMBRE RESPEL"],
        ["01/01/2026", "R-1", "ACEITE"],
        [],
        ["01/03/2026", "R-2", "BATERÍAS"],
    ]

    assert _find_insert_row(values, date(2026, 2, 1), first_data_row=3) == (4, False)


async def test_hazardous_waste_register_is_admin_only(client, seed_data):
    worker = auth_headers(await get_token(client, "ortiz@test.com"))
    response = await client.get("/api/hazardous-waste/status", headers=worker)
    assert response.status_code == 403


async def test_environment_sheet_id_is_used_as_the_only_setup_target(client, seed_data, monkeypatch):
    from app.core.config import settings

    sheet_id = "1XksaPDWi--vnvervuwG0w0wEAH5kogUT4_NA8VAkSXY"
    monkeypatch.setattr(settings, "GOOGLE_HAZARDOUS_WASTE_SPREADSHEET_ID", sheet_id)
    admin = auth_headers(await get_token(client, "admin@test.com"))

    status = await client.get("/api/hazardous-waste/status", headers=admin)
    assert status.status_code == 200
    assert status.json()["environment_configured"] is True
    assert status.json()["spreadsheet_url"].endswith(f"/d/{sheet_id}/edit")

    wrong_link = await client.post(
        "/api/hazardous-waste/setup",
        json={"spreadsheet_url": "https://docs.google.com/spreadsheets/d/1AAAAAAAAAAAAAAAAAAA/edit"},
        headers=admin,
    )
    assert wrong_link.status_code == 409


async def test_setup_imports_annual_records_and_new_entries_accumulate_after_disposal(
    client, seed_data, monkeypatch
):
    from app.api.routes import hazardous_waste

    imported_rows = [
        {
            "entry_date": date(2026, 4, 1), "respel_code": "R-01", "waste_name": "Aceite usado",
            "hazard": "Inflamable", "origin": "Taller", "quantity": Decimal("2"), "unit": "kg",
            "delivered_by": "Ana", "disposal_date": date(2026, 4, 5), "manager": "Gestor A",
            "source_sheet": "Lista  control de ingreso 2026", "sheet_row": 3, "external_key": None,
        },
        {
            "entry_date": date(2026, 4, 10), "respel_code": "R-01", "waste_name": "Aceite usado",
            "hazard": "Inflamable", "origin": "Taller", "quantity": Decimal("3"), "unit": "kg",
            "delivered_by": "Luis", "disposal_date": None, "manager": None,
            "source_sheet": "Lista  control de ingreso 2026", "sheet_row": 4, "external_key": None,
        },
        {
            "entry_date": date(2026, 4, 5), "respel_code": "R-01", "waste_name": "Aceite usado",
            "hazard": "Inflamable", "origin": "Taller", "quantity": Decimal("1"), "unit": "kg",
            "delivered_by": "Ana", "disposal_date": None, "manager": None,
            "source_sheet": "Lista  control de ingreso 2026", "sheet_row": 5, "external_key": None,
        },
    ]
    monkeypatch.setattr(hazardous_waste, "read_annual_tabs", lambda _sheet_id: imported_rows)
    monkeypatch.setattr(hazardous_waste, "stamp_import_keys", lambda *_args: None)
    admin = auth_headers(await get_token(client, "admin@test.com"))
    setup = await client.post(
        "/api/hazardous-waste/setup",
        json={"spreadsheet_url": "https://docs.google.com/spreadsheets/d/1XksaPDWi--vnvervuwG0w0wEAH5kogUT4_NA8VAkSXY/edit"},
        headers=admin,
    )
    assert setup.status_code == 200, setup.text
    assert setup.json()["imported"] == 3
    history = await client.get("/api/hazardous-waste", headers=admin)
    same_day_entry = next(row for row in history.json() if row["entry_date"] == "2026-04-05")
    assert same_day_entry["accumulated_quantity"] == "1.000"

    created = await client.post(
        "/api/hazardous-waste",
        json={
            "entry_date": "2026-04-20", "respel_code": "R-01", "waste_name": "Aceite usado",
            "hazard": "Inflamable", "origin": "Taller", "quantity": "4", "unit": "kg",
        },
        headers=admin,
    )
    assert created.status_code == 200, created.text
    assert created.json()["accumulated_quantity"] == "8.000"
    assert created.json()["unit"] == ""

    fractional_quantity = await client.post(
        "/api/hazardous-waste",
        json={
            "entry_date": "2026-04-20", "respel_code": "R-01", "waste_name": "Aceite usado",
            "quantity": "2.5",
        },
        headers=admin,
    )
    assert fractional_quantity.status_code == 422

    unknown_quantity = await client.post(
        "/api/hazardous-waste",
        json={
            "entry_date": "2026-04-21", "respel_code": "R-01", "waste_name": "Aceite usado",
            "unit": "kg",
        },
        headers=admin,
    )
    assert unknown_quantity.status_code == 200, unknown_quantity.text
    assert unknown_quantity.json()["quantity"] is None
    # Do not report a misleading accumulated total while an active entry has
    # no measured quantity.
    assert unknown_quantity.json()["accumulated_quantity"] is None

    disposed = await client.post(
        f"/api/hazardous-waste/{created.json()['id']}/dispose",
        json={"disposal_date": "2026-04-21", "manager": "Logisamb"},
        headers=admin,
    )
    assert disposed.status_code == 200, disposed.text
    assert disposed.json()["updated"] == 4
    assert disposed.json()["manager"] == "LOGISAMB"

    after_disposal = await client.post(
        "/api/hazardous-waste",
        json={
            "entry_date": "2026-04-22", "respel_code": "R-01", "waste_name": "Aceite usado",
            "hazard": "Inflamable", "origin": "Taller", "quantity": "2", "unit": "kg",
        },
        headers=admin,
    )
    assert after_disposal.status_code == 200, after_disposal.text
    assert after_disposal.json()["accumulated_quantity"] == "2.000"
