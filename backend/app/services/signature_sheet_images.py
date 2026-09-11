"""Insert saved signatures as real images in Google Sheets via Apps Script."""

from __future__ import annotations

import re

import httpx

from app.core.config import settings


def _file_id_from_signature_url(signature_url: str) -> str:
    match = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", signature_url or "")
    if not match:
        raise ValueError("La URL de firma no contiene un identificador de Drive válido.")
    return match.group(1)


def insert_signature_image(
    spreadsheet_id: str,
    sheet_name: str,
    field: str,
    signature_url: str,
) -> None:
    """Ask Apps Script to insert a Drive blob as an actual spreadsheet image."""
    if not settings.GOOGLE_SIGNATURES_APPS_SCRIPT_URL:
        raise RuntimeError(
            "Falta configurar GOOGLE_SIGNATURES_APPS_SCRIPT_URL para insertar firmas como imágenes."
        )
    if not settings.GOOGLE_SIGNATURES_APPS_SCRIPT_SECRET:
        raise RuntimeError(
            "Falta configurar GOOGLE_SIGNATURES_APPS_SCRIPT_SECRET para insertar firmas como imágenes."
        )
    # approved_by is kept as the Apps Script wire identifier for backwards
    # compatibility. It targets the visual REALIZADO POR block.
    if field not in {"requested_by", "approved_by", "performed_by"}:
        raise ValueError(f"Campo de firma no admitido: {field}")

    payload = {
        "secret": settings.GOOGLE_SIGNATURES_APPS_SCRIPT_SECRET,
        "spreadsheetId": spreadsheet_id,
        "sheetName": sheet_name,
        "field": field,
        "signatureFileId": _file_id_from_signature_url(signature_url),
    }
    try:
        # Do not inherit a workstation proxy: local development proxies often
        # reject the Apps Script redirect to script.googleusercontent.com.
        # Apps Script can take tens of seconds on a cold start. Keep the OT
        # sync open long enough instead of recording a false failure.
        with httpx.Client(timeout=60.0, follow_redirects=True, trust_env=False) as client:
            response = client.post(
                settings.GOOGLE_SIGNATURES_APPS_SCRIPT_URL,
                json=payload,
            )
        response.raise_for_status()
        try:
            result = response.json()
        except ValueError as exc:
            detail = response.text[:500].replace("\n", " ")
            raise RuntimeError(
                f"Apps Script no devolvió JSON (HTTP {response.status_code}): {detail}"
            ) from exc
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500].replace("\n", " ")
        raise RuntimeError(
            f"Apps Script respondió HTTP {exc.response.status_code}: {detail}"
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"No se pudo conectar con Apps Script: {type(exc).__name__}"
        ) from exc

    if not isinstance(result, dict) or result.get("ok") is not True:
        detail = result.get("error") if isinstance(result, dict) else None
        suffix = f": {detail}" if detail else "."
        raise RuntimeError(f"Apps Script rechazó la imagen de firma{suffix}")
