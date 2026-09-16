"""Validation and size normalization for work-order evidence photos."""

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError


ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_DIMENSION = 1920


def prepare_evidence_image(contents: bytes, declared_mime: str | None) -> tuple[bytes, str]:
    """Validate the actual image and return an EXIF-corrected compact JPEG."""
    if declared_mime not in ALLOWED_IMAGE_MIMES:
        raise ValueError("Solo se permiten fotos JPG, PNG o WebP.")
    if not contents:
        raise ValueError("La imagen está vacía.")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise ValueError("La foto supera el máximo de 12 MB antes de comprimirla.")

    try:
        with Image.open(BytesIO(contents)) as source:
            actual_format = (source.format or "").upper()
            actual_mime = {
                "JPEG": "image/jpeg",
                "PNG": "image/png",
                "WEBP": "image/webp",
            }.get(actual_format)
            if actual_mime != declared_mime:
                raise ValueError("El contenido no coincide con el formato de imagen declarado.")
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ValueError("La resolución de la foto es demasiado alta.")
            source.verify()

        with Image.open(BytesIO(contents)) as source:
            image = ImageOps.exif_transpose(source)
            image.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
            if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")

            output = BytesIO()
            image.save(output, format="JPEG", quality=84, optimize=True, progressive=True)
            encoded = output.getvalue()
            while len(encoded) > 5 * 1024 * 1024 and min(image.size) > 480:
                image.thumbnail((int(image.width * 0.8), int(image.height * 0.8)), Image.Resampling.LANCZOS)
                output = BytesIO()
                image.save(output, format="JPEG", quality=78, optimize=True, progressive=True)
                encoded = output.getvalue()
            return encoded, "image/jpeg"
    except ValueError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("El archivo no contiene una imagen válida.") from exc
