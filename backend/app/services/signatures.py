"""User signature images stored in Google Drive.

Each user's handwritten signature is uploaded once to a dedicated Drive folder
(GOOGLE_SIGNATURES_FOLDER_ID), one file per user, named `firma_<user_id>.<ext>`.
The file is made readable to "anyone with the link" — required so Google Sheets
can render it as an overlay image on the OT document (Sheets needs a URL it can
fetch on behalf of the requestor). The stored users.signature column holds a
download URL we can embed.

Only the exact signature file is shared publicly; nothing else is touched.
Writes use the OAuth-only write credentials (never the service account).
"""

from __future__ import annotations

import logging
import re
from io import BytesIO
from uuid import uuid4

from app.core.config import settings
from app.services.google_drive import _build_drive_write_service

logger = logging.getLogger(__name__)

# Resolved from the file id when we upload; used as the <img>/overlay URL.
_VIEW_URL = "https://drive.google.com/uc?export=view&id={file_id}"
_ALLOWED_SIGNATURE_MIMES = {"image/png", "image/jpeg", "image/webp"}


def _signature_name(user_id: int, mime: str) -> tuple[str, str]:
    """Return (filename, drive_mime) for a user's signature file."""
    ext = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
    }.get(mime, "png")
    # A signature URL is copied into a WorkOrder as an immutable audit
    # snapshot.  Do not reuse or replace the Drive file in-place: doing so
    # would silently change the signature displayed by historical OTs.
    return f"firma_{user_id}_{uuid4().hex}.{ext}", mime


def _file_id_from_url(signature_url: str) -> str | None:
    """Extract a Google Drive file id from one of our stored view URLs."""
    match = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", signature_url or "")
    return match.group(1) if match else None


def upload_signature(user_id: int, image_bytes: bytes, mime: str) -> str:
    """Upload a user's signature image to Drive.

    Returns the public download URL to embed in the OT document. Files are
    versioned instead of overwritten because WorkOrders retain the URL used at
    the moment they were issued or approved.
    """
    if not settings.GOOGLE_SIGNATURES_FOLDER_ID:
        raise RuntimeError("Falta configurar GOOGLE_SIGNATURES_FOLDER_ID.")
    if not settings.google_write_enabled:
        raise RuntimeError("Se requieren credenciales OAuth para subir la firma.")

    drive = _build_drive_write_service()
    folder_id = settings.GOOGLE_SIGNATURES_FOLDER_ID
    filename, drive_mime = _signature_name(user_id, mime)

    # googleapiclient requires a MediaUpload object, not a bare BytesIO.
    from googleapiclient.http import MediaIoBaseUpload

    media = MediaIoBaseUpload(BytesIO(image_bytes), mimetype=drive_mime, resumable=False)
    meta = {"name": filename, "parents": [folder_id]}
    created = drive.files().create(body=meta, media_body=media, fields="id").execute()
    file_id = created["id"]

    # Sheets must be able to load the image: grant anyone-with-the-link read
    # on ONLY this signature file.
    try:
        drive.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
            fields="id",
            sendNotificationEmail=False,
        ).execute()
    except Exception as exc:
        # A private image cannot be rendered by Sheets. Remove the newly
        # created orphan and fail the request instead of persisting a broken URL.
        try:
            drive.files().delete(fileId=file_id).execute()
        except Exception:  # noqa: BLE001 - original sharing error is more useful
            pass
        raise RuntimeError("No se pudo compartir la firma para usarla en la OT.") from exc

    logger.info("Firma de usuario %s subida (file_id=%s)", user_id, file_id)
    return _VIEW_URL.format(file_id=file_id)


def delete_signature(signature_url: str | None) -> None:
    """Best-effort removal of one unreferenced signature file from Drive."""
    file_id = _file_id_from_url(signature_url or "")
    if not file_id or not settings.google_write_enabled:
        return
    try:
        drive = _build_drive_write_service()
        drive.files().delete(fileId=file_id).execute()
        logger.info("Firma eliminada (file_id=%s)", file_id)
    except Exception as exc:
        logger.warning("No se pudo eliminar la firma %s: %s", file_id, exc)


def get_signature_image(file_id: str) -> tuple[bytes, str]:
    """Return one signature image through the authenticated Drive API.

    Drive's public ``uc`` endpoint currently sends ``Cross-Origin-Resource-
    Policy: same-origin``. That prevents browsers from embedding it directly
    in the web app, even though the file itself is public for Google Sheets.
    The API uses this helper to return the same bytes from our own origin.
    """
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", file_id):
        raise ValueError("Identificador de firma inválido.")

    drive = _build_drive_write_service()
    metadata = drive.files().get(
        fileId=file_id,
        fields="mimeType,size,trashed,parents",
    ).execute()
    mime = metadata.get("mimeType")
    size = int(metadata.get("size", 0))
    if (
        metadata.get("trashed")
        or mime not in _ALLOWED_SIGNATURE_MIMES
        or size <= 0
        or size > 2 * 1024 * 1024
        or settings.GOOGLE_SIGNATURES_FOLDER_ID not in metadata.get("parents", [])
    ):
        raise ValueError("La firma solicitada no es válida.")

    content = drive.files().get_media(fileId=file_id).execute()
    if not isinstance(content, bytes) or not content:
        raise RuntimeError("Google Drive no devolvió contenido para la firma.")
    return content, mime
