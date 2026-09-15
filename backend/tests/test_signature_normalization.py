from io import BytesIO

from PIL import Image

from app.services.signatures import _MAX_SIGNATURE_PIXELS, _prepare_signature_image


def _image_bytes(size=(4000, 2000)):
    image = Image.new("RGBA", size, (255, 255, 255, 0))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_signature_normalization_respects_apps_script_limits():
    encoded, mime = _prepare_signature_image(_image_bytes(), "image/png")

    assert mime == "image/jpeg"
    assert len(encoded) <= 1_500_000

    with Image.open(BytesIO(encoded)) as image:
        assert image.width * image.height <= _MAX_SIGNATURE_PIXELS
        assert image.width <= 1000
        assert image.height <= 1000


def test_apps_script_receives_normalized_inline_signature(monkeypatch):
    import app.services.signature_sheet_images as service
    import app.services.signatures as signatures
    from app.core.config import settings

    monkeypatch.setattr(settings, "GOOGLE_SIGNATURES_APPS_SCRIPT_URL", "https://script.test/exec")
    monkeypatch.setattr(settings, "GOOGLE_SIGNATURES_APPS_SCRIPT_SECRET", "secret")
    monkeypatch.setattr(
        signatures,
        "get_signature_image_for_processing",
        lambda file_id: (b"original", "image/png"),
    )
    monkeypatch.setattr(
        signatures,
        "_prepare_signature_image",
        lambda contents, mime: (b"normalized", "image/jpeg"),
    )

    sent = {}

    class Response:
        status_code = 200
        text = '{"ok": true}'

        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, json):
            sent["url"] = url
            sent["payload"] = json
            return Response()

    monkeypatch.setattr(service.httpx, "Client", Client)

    service.insert_signature_image(
        "sheet-123",
        "SEPTIEMBRE",
        "requested_by",
        "https://drive.google.com/uc?export=view&id=signature-123",
    )

    assert sent["payload"]["signatureFileId"] == "signature-123"
    assert sent["payload"]["signatureMimeType"] == "image/jpeg"
    assert sent["payload"]["signatureData"] == "bm9ybWFsaXplZA=="
