"""
Regressionstests für das Security-Review Epic 8 (docs/security/epic8-upload-review.md).

F-01: Upload wird in Chunks gelesen und frühzeitig abgebrochen
F-02: Decompression-Bomb-Schutz (Pixel-Limit vor dem Dekomprimieren)
F-03: Inhaltsvalidierung (PDF Magic Bytes, nur erlaubte Bild-Decoder) + nosniff
F-04: Content-Disposition ohne Header-Injection, Unicode via RFC 5987
"""

import io
import uuid
from unittest.mock import patch

import pytest
from PIL import Image

from app.models import StoredFile
from app.routers.files import (
    CHUNK_SIZE,
    MAX_FILE_SIZE,
    content_disposition,
    read_upload_limited,
)


def _png_bytes(width=50, height=50) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color="blue").save(buf, format="PNG")
    return buf.getvalue()


def _upload(client, household_id, token, name, data, mime):
    with patch("app.routers.files._storage") as mock_storage:
        mock_storage.save.return_value = f"{household_id}/test-uuid.bin"
        resp = client.post(
            f"/api/households/{household_id}/files/",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (name, io.BytesIO(data), mime)},
        )
    return resp


def _download(client, db, household, user, token, original_name, mime):
    sf = StoredFile(
        id=uuid.uuid4(),
        household_id=household.id,
        original_name=original_name,
        mime_type=mime,
        size_bytes=10,
        storage_path=f"{household.id}/x.bin",
        uploaded_by_user_id=user.id,
    )
    db.add(sf)
    db.commit()
    with patch("app.routers.files._storage") as mock_storage:
        mock_storage.open.return_value = io.BytesIO(b"%PDF-1.4 data")
        return client.get(
            f"/api/households/{household.id}/files/{sf.id}",
            headers={"Authorization": f"Bearer {token}"},
        )


# ---------------------------------------------------------------------------
# F-01 — Chunk-basiertes Lesen
# ---------------------------------------------------------------------------


class _EndlessUpload:
    """Simuliert einen Upload ohne Ende und zählt die gelesenen Bytes."""

    def __init__(self):
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        self.bytes_read += size
        return b"x" * size


def test_read_upload_limited_aborts_early():
    """Lesen stoppt direkt nach Überschreiten des Limits, nicht am Dateiende."""
    from fastapi import HTTPException

    upload = _EndlessUpload()
    with pytest.raises(HTTPException) as exc:
        read_upload_limited(upload, max_size=MAX_FILE_SIZE)
    assert exc.value.detail["code"] == "FILE_TOO_LARGE"
    assert upload.bytes_read <= MAX_FILE_SIZE + CHUNK_SIZE


def test_read_upload_limited_accepts_exact_limit():
    data = b"y" * (3 * CHUNK_SIZE)
    result = read_upload_limited(io.BytesIO(data), max_size=len(data))
    assert result == data


# ---------------------------------------------------------------------------
# F-02 — Decompression Bomb
# ---------------------------------------------------------------------------


def test_upload_image_over_pixel_limit_rejected(client, household_a, token_a, monkeypatch):
    """Bilder über MAX_IMAGE_PIXELS werden abgelehnt, auch im Warn-Bereich (1x–2x)."""
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1_000)
    # 40x40 = 1600 Pixel: zwischen 1x und 2x Limit → Pillow würde nur warnen
    resp = _upload(client, household_a.id, token_a, "bomb.png", _png_bytes(40, 40), "image/png")
    assert resp.status_code == 422
    # Eigener Code, damit die App „zu viele Pixel“ statt „falsches Format“ anzeigt
    assert resp.json()["detail"]["code"] == "IMAGE_TOO_MANY_PIXELS"


def test_upload_image_under_pixel_limit_ok(client, household_a, token_a):
    resp = _upload(client, household_a.id, token_a, "ok.png", _png_bytes(40, 40), "image/png")
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# F-03 — Inhaltsvalidierung
# ---------------------------------------------------------------------------


def test_upload_valid_pdf(client, household_a, token_a):
    resp = _upload(client, household_a.id, token_a, "rechnung.pdf", b"%PDF-1.7\n...", "application/pdf")
    assert resp.status_code == 201
    assert resp.json()["mime_type"] == "application/pdf"


def test_upload_html_disguised_as_pdf_rejected(client, household_a, token_a):
    """HTML mit gefälschtem Content-Type application/pdf → 422."""
    html = b"<html><script>alert(1)</script></html>"
    resp = _upload(client, household_a.id, token_a, "evil.pdf", html, "application/pdf")
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_TYPE_NOT_ALLOWED"


def test_upload_non_image_disguised_as_png_rejected(client, household_a, token_a):
    resp = _upload(client, household_a.id, token_a, "evil.png", b"%PDF-1.4 not an image", "image/png")
    assert resp.status_code == 422


def test_upload_disallowed_image_format_rejected(client, household_a, token_a):
    """Ein GIF mit Content-Type image/png wird nicht dekodiert (nur JPEG/PNG/WEBP)."""
    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, format="GIF")
    resp = _upload(client, household_a.id, token_a, "x.png", buf.getvalue(), "image/png")
    assert resp.status_code == 422


def test_download_pdf_is_attachment_with_nosniff(client, db, household_a, user_a, token_a):
    resp = _download(client, db, household_a, user_a, token_a, "vertrag.pdf", "application/pdf")
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["content-disposition"].startswith("attachment;")


def test_download_image_is_inline_with_nosniff(client, db, household_a, user_a, token_a):
    resp = _download(client, db, household_a, user_a, token_a, "cat.jpeg", "image/jpeg")
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["content-disposition"].startswith("inline;")


# ---------------------------------------------------------------------------
# F-04 — Content-Disposition
# ---------------------------------------------------------------------------


def test_content_disposition_strips_injection():
    header = content_disposition('photo"; filename="evil.exe\r\nX-Injected: 1', "inline")
    assert "\r" not in header and "\n" not in header
    fallback = header.split('filename="', 1)[1].split('"', 1)[0]
    assert '"' not in fallback and ";" not in fallback


def test_content_disposition_rfc5987_unicode():
    header = content_disposition("Rechnung März 日本.pdf", "attachment")
    assert header.startswith('attachment; filename="Rechnung_M_rz___.pdf"; ')
    assert "filename*=UTF-8''Rechnung%20M%C3%A4rz%20%E6%97%A5%E6%9C%AC.pdf" in header
    header.encode("latin-1")  # Header muss Latin-1-kodierbar sein


def test_download_unicode_filename_does_not_crash(client, db, household_a, user_a, token_a):
    """Vorher 500 (UnicodeEncodeError) bei Nicht-Latin-1-Dateinamen."""
    resp = _download(client, db, household_a, user_a, token_a, "日本 Rechnung.pdf", "application/pdf")
    assert resp.status_code == 200
    assert "filename*=UTF-8''%E6%97%A5%E6%9C%AC%20Rechnung.pdf" in resp.headers["content-disposition"]


def test_download_injection_filename_single_header(client, db, household_a, user_a, token_a):
    resp = _download(client, db, household_a, user_a, token_a, 'a"; filename="evil.exe', "application/pdf")
    assert resp.status_code == 200
    cd = resp.headers["content-disposition"]
    assert 'filename="a___filename__evil.exe"' in cd
