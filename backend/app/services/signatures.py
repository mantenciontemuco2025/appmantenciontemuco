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
import time
from io import BytesIO
from uuid import uuid4

from app.core.config import settings
from app.services.google_drive import _build_drive_write_service

logger = logging.getLogger(__name__)

# Resolved from the file id when we upload; used as the <img>/overlay URL.
_VIEW_URL = "https://drive.google.com/uc?export=view&id={file_id}"
_ALLOWED_SIGNATURE_MIMES = {"image/png", "image/jpeg", "image/webp"}
# Apps Script rejects blobs above 1,000,000 pixels. Keep a small margin so
# rounding and metadata cannot push an otherwise valid image over the limit.
_MAX_SIGNATURE_PIXELS = 900_000
_MAX_SIGNATURE_BYTES = 1_500_000
_RETRYABLE_DRIVE_STATUSES = {408, 429, 500, 502, 503, 504}


def _execute_drive_request(request, operation: str, attempts: int = 3):
    """Execute a Drive request with short exponential retries.

    Google Drive can briefly return 429/5xx responses, especially after an
    OAuth token refresh or when the API is waking up. Validation and
    permission errors are returned immediately; only transient failures are
    retried.
    """
    from googleapiclient.errors import HttpError

    for attempt in range(1, attempts + 1):
        try:
            return request.execute()
        except HttpError as exc:
            response = getattr(exc, "resp", None)
            status = getattr(response, "status", None)
            if status not in _RETRYABLE_DRIVE_STATUSES or attempt == attempts:
                raise
            logger.warning(
                "Google Drive %s falló temporalmente (HTTP %s); reintento %s/%s",
                operation,
                status,
                attempt,
                attempts - 1,
            )
        except (OSError, TimeoutError) as exc:
            if attempt == attempts:
                raise
            logger.warning(
                "Google Drive %s tuvo un error de red (%s); reintento %s/%s",
                operation,
                type(exc).__name__,
                attempt,
                attempts - 1,
            )

        time.sleep(0.75 * (2 ** (attempt - 1)))

    raise RuntimeError(f"No se pudo completar la operación de Google Drive: {operation}")


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


def _prepare_signature_image(image_bytes: bytes, mime: str) -> tuple[bytes, str]:
    """Normalize signatures below Google Sheets' blob and pixel limits."""
    try:
        from PIL import Image, ImageOps

        with Image.open(BytesIO(image_bytes)) as source:
            image = ImageOps.exif_transpose(source)
            if image.width * image.height > _MAX_SIGNATURE_PIXELS:
                scale = (_MAX_SIGNATURE_PIXELS / (image.width * image.height)) ** 0.5
                image = image.resize(
                    (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
                    Image.Resampling.LANCZOS,
                )

            # A white background keeps transparent signatures readable in JPEG.
            if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")

            # 1000x1000 guarantees the Apps Script pixel limit even when the
            # source image is nearly square.
            image.thumbnail((1000, 1000), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format="JPEG", quality=82, optimize=True, progressive=True)
            encoded = output.getvalue()

            while len(encoded) > _MAX_SIGNATURE_BYTES and min(image.size) > 400:
                image = image.resize(
                    (max(1, int(image.width * 0.8)), max(1, int(image.height * 0.8))),
                    Image.Resampling.LANCZOS,
                )
                output = BytesIO()
                image.save(output, format="JPEG", quality=75, optimize=True, progressive=True)
                encoded = output.getvalue()
    except Exception as exc:  # noqa: BLE001 - normalize any invalid image
        raise RuntimeError("No se pudo preparar la imagen de firma.") from exc

    return encoded, "image/jpeg"


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

    image_bytes, mime = _prepare_signature_image(image_bytes, mime)
    drive = _build_drive_write_service()
    folder_id = settings.GOOGLE_SIGNATURES_FOLDER_ID
    filename, drive_mime = _signature_name(user_id, mime)

    # googleapiclient requires a MediaUpload object, not a bare BytesIO.
    from googleapiclient.http import MediaIoBaseUpload

    media = MediaIoBaseUpload(BytesIO(image_bytes), mimetype=drive_mime, resumable=False)
    meta = {"name": filename, "parents": [folder_id]}
    created = _execute_drive_request(
        drive.files().create(body=meta, media_body=media, fields="id"),
        "subir la firma",
    )
    file_id = created["id"]

    # Sheets must be able to load the image: grant anyone-with-the-link read
    # on ONLY this signature file.
    try:
        _execute_drive_request(
            drive.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
                fields="id",
                sendNotificationEmail=False,
            ),
            "compartir la firma",
        )
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


def _download_signature_image(file_id: str, max_bytes: int) -> tuple[bytes, str]:
    """Download a validated signature, with a caller-specific byte limit."""
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
        or size > max_bytes
        or settings.GOOGLE_SIGNATURES_FOLDER_ID not in metadata.get("parents", [])
    ):
        raise ValueError("La firma solicitada no es válida.")

    content = drive.files().get_media(fileId=file_id).execute()
    if not isinstance(content, bytes) or not content:
        raise RuntimeError("Google Drive no devolvió contenido para la firma.")
    return content, mime


def get_signature_image(file_id: str) -> tuple[bytes, str]:
    """Return one signature image through the authenticated Drive API.

    Drive's public ``uc`` endpoint currently sends ``Cross-Origin-Resource-
    Policy: same-origin``. That prevents browsers from embedding it directly
    in the web app, even though the file itself is public for Google Sheets.
    The API uses this helper to return the same bytes from our own origin.
    """
    return _download_signature_image(file_id, 2 * 1024 * 1024)


def get_signature_image_for_processing(file_id: str) -> tuple[bytes, str]:
    """Download an existing signature so it can be normalized before an OT sync.

    Older signatures may exceed the Apps Script limits even when newly uploaded
    signatures are normalized. This path allows a larger source file, then the
    caller compresses it before sending it to Apps Script.
    """
    return _download_signature_image(file_id, 10 * 1024 * 1024)
