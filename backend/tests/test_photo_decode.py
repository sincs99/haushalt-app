"""HEIC fallback validates real bytes and retains existing image limits."""

import io

import pytest
from fastapi import HTTPException
from PIL import Image

from app.routers.files import validate_upload


def image_bytes(format_name: str, size: tuple[int, int] = (80, 60)) -> bytes:
    output = io.BytesIO()
    with Image.new("RGB", size, "orange") as image:
        image.save(output, format=format_name)
    return output.getvalue()


@pytest.mark.parametrize("mime", ["image/heic", "image/heif"])
def test_heic_is_validated_and_converted_to_jpeg(mime):
    data, final_mime, extension = validate_upload(image_bytes("HEIF"), mime)
    assert (final_mime, extension) == ("image/jpeg", ".jpeg")
    with Image.open(io.BytesIO(data)) as image:
        assert image.format == "JPEG"
        assert image.size == (80, 60)


@pytest.mark.parametrize("data", [b"not an image", b"%PDF-1.4", image_bytes("GIF")])
def test_heic_mime_does_not_bypass_content_validation(data):
    with pytest.raises(HTTPException) as error:
        validate_upload(data, "image/heic")
    assert error.value.detail["code"] == "FILE_TYPE_NOT_ALLOWED"


def test_heic_preserves_the_predecode_pixel_limit(monkeypatch):
    data = image_bytes("HEIF")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 3000)
    with pytest.raises(HTTPException) as error:
        validate_upload(data, "image/heic")
    assert error.value.detail["code"] == "IMAGE_TOO_MANY_PIXELS"


def test_heic_above_twice_the_pixel_limit_reports_the_pixel_error(monkeypatch):
    data = image_bytes("HEIF")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    with pytest.raises(HTTPException) as error:
        validate_upload(data, "image/heic")
    assert error.value.detail["code"] == "IMAGE_TOO_MANY_PIXELS"


@pytest.mark.parametrize("size, expected", [((10000, 1), (1600, 1)), ((1, 10000), (1, 1600))])
def test_extremely_thin_images_keep_nonzero_dimensions(size, expected):
    data, _, _ = validate_upload(image_bytes("PNG", size), "image/png")
    with Image.open(io.BytesIO(data)) as image:
        assert image.size == expected
