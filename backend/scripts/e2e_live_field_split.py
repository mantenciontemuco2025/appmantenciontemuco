"""E2E live test: new field-ownership model.

Admin: área, equipo, fecha solicitud, descripción, solicitado por, responsable,
participantes (quiénes entran).
Worker (responsable): fecha de ejecución, sección, hora inicio/fin, horas
manuales, tipo, LOTO, recursos, riesgos, obs, folio, vale.
Then start -> complete -> approve.
"""
import requests

BASE = "http://localhost:8000"

ADMIN = ("admin@mantencion.com", "Admin123!")
# worker ids from backend/seed.py: Ortiz=3, Valdes=4, Fabres=5, Jara=6
ORTIZ = ("ortiz@mantencion.com", "Worker123!")


T = 90


def token(email, password):
    r = requests.post(
        f"{BASE}/api/auth/login",
        data={"username": email, "password": password},
        timeout=T,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def hdr(t):
    return {"Authorization": f"Bearer {t}"}


admin_t = token(*ADMIN)
worker_t = token(*ORTIZ)

# ── 1. Admin gets catalogs ───────────────────────────────────────────────
tree = requests.get(f"{BASE}/api/catalogs/tree", headers=hdr(admin_t), timeout=T).json()
area = tree[0]
equip = area["equipment"][0]
print(f"Área={area['name']} (id {area['id']}), Equipo={equip['name']} (id {equip['id']})")

# ── 2. Admin creates DRAFT with fecha solicitud + responsable + participantes ──
create = requests.post(
    f"{BASE}/api/work-orders",
    headers=hdr(admin_t),
    json={
        "title": "E2E nuevo modelo campos",
        "description": "Cambiar sello bomba y lubricar rodamientos",
        "area_id": area["id"],
        "equipment_id": equip["id"],
        "maintenance_type": "PREVENTIVE",
        "loto_status": "NOT_APPLICABLE",
        "request_date": "2026-09-04",
        "requested_by": "Jefe Planta",
        "responsible_user_id": 3,  # Ortiz
        "participant_user_ids": [3, 4, 5],  # Ortiz, Valdés, Fabres
        "emit": False,
    },
    timeout=T,
)
create.raise_for_status()
wo = create.json()
wo_id = wo["id"]
print(f"\nDRAFT creada: {wo['ot_number']} (id {wo_id})")
print(f"  request_date={wo['request_date']}  responsible={wo['responsible_user_name']}")
print(f"  participantes={wo['participant_user_ids']}  sync={wo['ot_sheet_sync_status']}")

# ── 3. Admin issues (DRAFT -> PENDING) ─────────────────────────────────────
issue = requests.post(
    f"{BASE}/api/work-orders/{wo_id}/issue", headers=hdr(admin_t), timeout=T
)
assert issue.status_code == 200, issue.text
issue_data = issue.json()
print(f"\nIssued -> {issue_data['status']} | google={issue_data['google_ot_file_id']}")

# ── 4. Worker (responsable) fulfills: fecha ejecución + sección + horas + resto ──
print("\nAdmin intenta emitir OT sin participantes -> debe 400 (participante)")
# create OT draft sin participantes, luego issue
c2 = requests.post(
    f"{BASE}/api/work-orders",
    headers=hdr(admin_t),
    json={
        "title": "sin participantes",
        "description": "Debe fallar en issue",
        "area_id": area["id"],
        "equipment_id": equip["id"],
        "maintenance_type": "PREVENTIVE",
        "emit": False,
    },
    timeout=T,
)
c2.raise_for_status()
r2 = requests.post(
    f"{BASE}/api/work-orders/{c2.json()['id']}/issue", headers=hdr(admin_t), timeout=T
)
print(f"  issue sin participantes -> {r2.status_code}: {r2.json().get('detail','')}")
assert r2.status_code == 400 and "participante" in r2.json()["detail"].lower()

# ── 5. Worker not responsible cannot fulfill (403) ────────────────────────
valdes_t = token("valdes@mantencion.com", "Worker123!")
forb = requests.patch(
    f"{BASE}/api/work-orders/{wo_id}/fulfill",
    headers=hdr(valdes_t),
    json={"execution_date": "2026-09-15"},
    timeout=T,
)
assert forb.status_code == 403, forb.text
print(f"\nValdés (no responsable) intenta fulfill -> {forb.status_code} (esperado 403)")

# ── 6. Ortiz fills execution details ──────────────────────────────────────
fulfill = requests.patch(
    f"{BASE}/api/work-orders/{wo_id}/fulfill",
    headers=hdr(worker_t),
    json={
        "maintenance_type": "CORRECTIVE",
        "loto_status": "YES",
        "execution_date": "2026-09-15",
        "section_name": "Sala de bombas",
        "start_time": "08:00",
        "end_time": "10:00",
        "estimated_time": "2 h 30 min",  # manual horas
        "resources_required": "Sello SKF, llave 24mm, grasa EP2",
        "risks": "Desenergizar equipo, EPP",
        "observations": "Sello muy desgastado",
        "folio": "PERM-2026-42",
        "voucher_number": "V-889",
        "approved_by": "Supervisor Planta",
    },
    timeout=T,
)
assert fulfill.status_code == 200, fulfill.text
fd = fulfill.json()
print(f"\nFulfill OK: type={fd['maintenance_type']} exec={fd['execution_date']} "
      f"seccion={fd['section_name']} horas={fd['estimated_time']}")
print(f"  participantes siguen = {fd['participant_user_ids']} (admin los eligió)")

# ── 7. Start ──────────────────────────────────────────────────────────────
start = requests.post(
    f"{BASE}/api/work-orders/{wo_id}/start", headers=hdr(worker_t), timeout=T
)
assert start.status_code == 200, start.text
print(f"\nStart -> {start.json()['status']} started_by={start.json()['started_by_name']}")

# ── 8. Complete ───────────────────────────────────────────────────────────
comp = requests.patch(
    f"{BASE}/api/work-orders/{wo_id}/complete",
    headers=hdr(worker_t),
    json={"completion_notes": "Listo, cambio de sello realizado"},
    timeout=T,
)
assert comp.status_code == 200, comp.text
cdata = comp.json()
print(f"Complete -> {cdata['status']} duración real={cdata['actual_duration_minutes']} min")

# ── 9. Approve ────────────────────────────────────────────────────────────
appr = requests.post(
    f"{BASE}/api/work-orders/{wo_id}/approve",
    headers=hdr(admin_t),
    json={"approved_signature": "Admin Firma"},
    timeout=T,
)
assert appr.status_code == 200, appr.text
adata = appr.json()
print(f"Approve -> {adata['status']} approved_by={adata['approved_by_user_name']}")
print(f"  sync OT={adata['ot_sheet_sync_status']} sync mensual={adata['monthly_sheet_sync_status']}")

print("\nOK E2E live: nuevo modelo de campos verificado (fecha solicitud admin, "
      "fecha ejecución/sección/horas worker)")