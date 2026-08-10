"""
Multi-Tenant Scoping Tests für Files (Upload-Infrastruktur).

Stellt sicher, dass:
- Cross-Tenant-Zugriffe auf Dateien abgelehnt werden (403)
- Größen- und MIME-Typ-Prüfungen greifen (422)
- Normaler Upload/Download/Delete funktioniert
- FILE_IN_USE verhindert das Löschen referenzierter Dateien
"""

import io
import uuid
from unittest.mock import patch

from PIL import Image


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_test_png(width=100, height=100):
    """Erzeugt ein kleines PNG in-memory."""
    img = Image.new("RGB", (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def make_test_png_transparent(width=100, height=100):
    """Erzeugt ein PNG mit Transparenz in-memory."""
    img = Image.new("RGBA", (width, height), color=(255, 0, 0, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def make_large_fake_file(size_bytes: int) -> io.BytesIO:
    """Erzeugt ein BytesIO mit genau size_bytes an Daten."""
    buf = io.BytesIO(b"x" * size_bytes)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Upload Tests
# ---------------------------------------------------------------------------


def test_upload_file_success(client, household_a, token_a):
    """POST Upload mit gültigem PNG liefert 201 + korrekte Response."""
    buf = make_test_png()
    with patch("app.routers.files._storage") as mock_storage:
        mock_storage.save.return_value = f"{household_a.id}/test-uuid.jpeg"
        resp = client.post(
            f"/api/households/{household_a.id}/files/",
            headers={"Authorization": f"Bearer {token_a}"},
            files={"file": ("cat.png", buf, "image/png")},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["original_name"] == "cat.png"
    assert data["mime_type"] in ("image/jpeg", "image/png")
    assert data["size_bytes"] > 0
    assert "id" in data
    assert "created_at" in data


def test_upload_transparent_png_stays_png(client, household_a, token_a):
    """PNG mit Transparenz bleibt als PNG erhalten."""
    buf = make_test_png_transparent()
    with patch("app.routers.files._storage") as mock_storage:
        mock_storage.save.return_value = f"{household_a.id}/test-uuid.png"
        resp = client.post(
            f"/api/households/{household_a.id}/files/",
            headers={"Authorization": f"Bearer {token_a}"},
            files={"file": ("alpha.png", buf, "image/png")},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["mime_type"] == "image/png"


def test_upload_cross_tenant_forbidden(client, household_b, token_a):
    """POST Upload in fremden Haushalt → 403."""
    buf = make_test_png()
    resp = client.post(
        f"/api/households/{household_b.id}/files/",
        headers={"Authorization": f"Bearer {token_a}"},
        files={"file": ("cat.png", buf, "image/png")},
    )
    assert resp.status_code == 403


def test_upload_file_too_large(client, household_a, token_a):
    """POST Upload > 10 MB → 422 FILE_TOO_LARGE."""
    buf = make_large_fake_file(11 * 1024 * 1024)
    resp = client.post(
        f"/api/households/{household_a.id}/files/",
        headers={"Authorization": f"Bearer {token_a}"},
        files={"file": ("huge.png", buf, "image/png")},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_TOO_LARGE"


def test_upload_wrong_mime_type(client, household_a, token_a):
    """POST Upload mit nicht-erlaubtem MIME → 422 FILE_TYPE_NOT_ALLOWED."""
    buf = io.BytesIO(b"not a real file")
    resp = client.post(
        f"/api/households/{household_a.id}/files/",
        headers={"Authorization": f"Bearer {token_a}"},
        files={"file": ("script.sh", buf, "application/x-shellscript")},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_TYPE_NOT_ALLOWED"


# ---------------------------------------------------------------------------
# Download Tests
# ---------------------------------------------------------------------------


def test_download_own_file(client, household_a, token_a, stored_file_a):
    """GET eigene Datei → 200."""
    with patch("app.routers.files._storage") as mock_storage:
        mock_storage.open.return_value = io.BytesIO(b"fake image data")
        resp = client.get(
            f"/api/households/{household_a.id}/files/{stored_file_a.id}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
    assert resp.status_code == 200


def test_download_cross_tenant_forbidden(
    client, household_b, token_a, stored_file_b
):
    """GET Datei aus fremdem Haushalt → 403."""
    resp = client.get(
        f"/api/households/{household_b.id}/files/{stored_file_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


def test_download_nonexistent_file(client, household_a, token_a):
    """GET nicht existierende Datei → 404."""
    fake_id = uuid.uuid4()
    resp = client.get(
        f"/api/households/{household_a.id}/files/{fake_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Delete Tests
# ---------------------------------------------------------------------------


def test_delete_own_file(client, household_a, token_a, stored_file_a):
    """DELETE eigene Datei → 204."""
    with patch("app.routers.files._storage") as mock_storage:
        mock_storage.delete.return_value = None
        resp = client.delete(
            f"/api/households/{household_a.id}/files/{stored_file_a.id}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
    assert resp.status_code == 204


def test_delete_cross_tenant_forbidden(
    client, household_b, token_a, stored_file_b
):
    """DELETE Datei aus fremdem Haushalt → 403."""
    resp = client.delete(
        f"/api/households/{household_b.id}/files/{stored_file_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


def test_delete_file_in_use(client, db, household_a, token_a, stored_file_a, pet_a):
    """DELETE Datei die von Pet referenziert wird → 422 FILE_IN_USE."""
    # Pet mit photo_file_id verknüpfen
    pet_a.photo_file_id = stored_file_a.id
    db.commit()

    with patch("app.routers.files._storage") as mock_storage:
        resp = client.delete(
            f"/api/households/{household_a.id}/files/{stored_file_a.id}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_IN_USE"


# ---------------------------------------------------------------------------
# Pet Photo PATCH Tests
# ---------------------------------------------------------------------------


def test_patch_pet_photo_file_id(client, db, household_a, token_a, pet_a, stored_file_a):
    """PATCH Pet mit gültigem photo_file_id → 200."""
    resp = client.patch(
        f"/api/households/{household_a.id}/pets/{pet_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"photo_file_id": str(stored_file_a.id)},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["photo_file_id"] == str(stored_file_a.id)


def test_patch_pet_photo_file_id_cross_tenant(
    client, household_a, token_a, pet_a, stored_file_b
):
    """PATCH Pet mit Datei aus anderem Haushalt → 422 FILE_MISMATCH."""
    resp = client.patch(
        f"/api/households/{household_a.id}/pets/{pet_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"photo_file_id": str(stored_file_b.id)},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_MISMATCH"


def test_patch_pet_photo_file_id_nonexistent(client, household_a, token_a, pet_a):
    """PATCH Pet mit nicht existierendem photo_file_id → 422 FILE_MISMATCH."""
    fake_id = uuid.uuid4()
    resp = client.patch(
        f"/api/households/{household_a.id}/pets/{pet_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"photo_file_id": str(fake_id)},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_MISMATCH"
