"""
Tests für das Dokumente-Modul (Ablage).

Stellt sicher, dass:
- CRUD inkl. Multipart-Upload und Löschen der Datei funktioniert
- Liste nach Kategorie filtert, nach Titel sucht und paginiert
- Cross-Household-Zugriffe auf JEDEM Endpoint mit 403 abgelehnt werden
- Validierung und Speicher-Quota greifen
- Socket.IO-Events gesendet werden
"""

import io
import uuid
from unittest.mock import patch

import pytest

from app.models import Document, StoredFile

PDF_BYTES = b"%PDF-1.7\n%test document\n"


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _url(household_id, suffix=""):
    return f"/api/households/{household_id}/documents/{suffix}"


def _upload(client, household_id, token, data=PDF_BYTES, name="vertrag.pdf", mime="application/pdf", **form):
    with patch("app.routers.files._storage") as mock_storage:
        mock_storage.save.return_value = f"{household_id}/{uuid.uuid4()}.pdf"
        return client.post(
            _url(household_id, "upload"),
            headers=_auth(token),
            files={"file": (name, io.BytesIO(data), mime)},
            data=form,
        )


def _make_file(db, household, user, size=1000) -> StoredFile:
    sf = StoredFile(
        id=uuid.uuid4(),
        household_id=household.id,
        original_name="scan.pdf",
        mime_type="application/pdf",
        size_bytes=size,
        storage_path=f"{household.id}/{uuid.uuid4()}.pdf",
        uploaded_by_user_id=user.id,
    )
    db.add(sf)
    db.commit()
    db.refresh(sf)
    return sf


def _events(mock_emit, name):
    return [c.args for c in mock_emit.call_args_list if c.args[1] == name]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_upload_document_multipart(client, household_a, token_a, user_a, _mock_socket_emit):
    resp = _upload(
        client, household_a.id, token_a,
        title="  Garantie Waschmaschine ", category="warranty",
        notes="Kaufbeleg", document_date="2026-01-15", expiry_date="2028-01-15",
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Garantie Waschmaschine"
    assert data["category"] == "warranty"
    assert data["notes"] == "Kaufbeleg"
    assert data["document_date"] == "2026-01-15"
    assert data["expiry_date"] == "2028-01-15"
    assert data["created_by_user_id"] == str(user_a.id)
    assert data["file"]["mime_type"] == "application/pdf"
    assert data["file"]["original_name"] == "vertrag.pdf"

    events = _events(_mock_socket_emit, "document_created")
    assert len(events) == 1
    assert events[0][0] == household_a.id
    assert events[0][2]["id"] == data["id"]


def test_upload_document_title_defaults_to_filename(client, household_a, token_a):
    resp = _upload(client, household_a.id, token_a, name="Rechnung Mai.pdf")
    assert resp.status_code == 201
    assert resp.json()["title"] == "Rechnung Mai"
    assert resp.json()["category"] == "other"


def test_upload_document_image(client, household_a, token_a):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (20, 20), color="green").save(buf, format="PNG")
    resp = _upload(client, household_a.id, token_a, data=buf.getvalue(), name="beleg.png", mime="image/png")
    assert resp.status_code == 201
    assert resp.json()["file"]["mime_type"] == "image/jpeg"


def test_create_document_from_uploaded_file(client, db, household_a, user_a, token_a, _mock_socket_emit):
    sf = _make_file(db, household_a, user_a)
    resp = client.post(
        _url(household_a.id),
        headers=_auth(token_a),
        json={"title": "Hausratversicherung", "category": "insurance", "file_id": str(sf.id)},
    )
    assert resp.status_code == 201
    assert resp.json()["file"]["id"] == str(sf.id)
    assert len(_events(_mock_socket_emit, "document_created")) == 1


def test_get_document(client, household_a, token_a, document_a):
    resp = client.get(_url(household_a.id, str(document_a.id)), headers=_auth(token_a))
    assert resp.status_code == 200
    assert resp.json()["title"] == "Mietvertrag"
    assert resp.json()["expiry_date"] == "2027-03-31"


def test_get_document_not_found(client, household_a, token_a):
    resp = client.get(_url(household_a.id, str(uuid.uuid4())), headers=_auth(token_a))
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "DOCUMENT_NOT_FOUND"


def test_update_document(client, household_a, token_a, document_a, _mock_socket_emit):
    resp = client.patch(
        _url(household_a.id, str(document_a.id)),
        headers=_auth(token_a),
        json={"title": "Mietvertrag Wohnung", "notes": "Kündigung 3 Monate", "expiry_date": None},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Mietvertrag Wohnung"
    assert data["notes"] == "Kündigung 3 Monate"
    assert data["expiry_date"] is None
    assert data["category"] == "contract"  # unverändert
    assert len(_events(_mock_socket_emit, "document_updated")) == 1


def test_delete_document_removes_file(client, db, household_a, token_a, document_a, _mock_socket_emit):
    file_id = document_a.file_id
    storage_path = document_a.file.storage_path
    doc_id = document_a.id
    with patch("app.routers.files._storage") as mock_storage:
        resp = client.delete(_url(household_a.id, str(doc_id)), headers=_auth(token_a))
    assert resp.status_code == 204
    mock_storage.delete.assert_called_once_with(storage_path)

    db.expire_all()
    assert db.get(Document, doc_id) is None
    assert db.get(StoredFile, file_id) is None
    events = _events(_mock_socket_emit, "document_deleted")
    assert events == [(household_a.id, "document_deleted", {"id": str(doc_id), "file_id": str(file_id)})]


def test_file_of_document_cannot_be_deleted_via_files(client, household_a, token_a, document_a):
    resp = client.delete(
        f"/api/households/{household_a.id}/files/{document_a.file_id}",
        headers=_auth(token_a),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_IN_USE"


def test_document_file_downloadable(client, household_a, token_a, document_a):
    with patch("app.routers.files._storage") as mock_storage:
        mock_storage.open.return_value = io.BytesIO(PDF_BYTES)
        resp = client.get(
            f"/api/households/{household_a.id}/files/{document_a.file_id}",
            headers=_auth(token_a),
        )
    assert resp.status_code == 200
    assert resp.content == PDF_BYTES


# ---------------------------------------------------------------------------
# Liste: Filter, Suche, Pagination
# ---------------------------------------------------------------------------


@pytest.fixture()
def many_documents(db, household_a, user_a):
    from tests.conftest import _make_document

    return [
        _make_document(db, household_a, user_a, "Mietvertrag", "contract"),
        _make_document(db, household_a, user_a, "Handyvertrag", "contract"),
        _make_document(db, household_a, user_a, "Rechnung 100%_Strom", "invoice"),
        _make_document(db, household_a, user_a, "Garantie TV", "warranty"),
    ]


def test_list_documents(client, household_a, token_a, many_documents, document_b):
    resp = client.get(_url(household_a.id), headers=_auth(token_a))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 4
    ids = {d["id"] for d in data["items"]}
    assert ids == {str(d.id) for d in many_documents}
    assert str(document_b.id) not in ids


def test_list_documents_category_filter(client, household_a, token_a, many_documents):
    resp = client.get(_url(household_a.id), headers=_auth(token_a), params={"category": "contract"})
    data = resp.json()
    assert data["total"] == 2
    assert all(d["category"] == "contract" for d in data["items"])


def test_list_documents_search_case_insensitive(client, household_a, token_a, many_documents):
    resp = client.get(_url(household_a.id), headers=_auth(token_a), params={"q": "VERTRAG"})
    titles = {d["title"] for d in resp.json()["items"]}
    assert titles == {"Mietvertrag", "Handyvertrag"}


def test_list_documents_search_escapes_wildcards(client, household_a, token_a, many_documents):
    resp = client.get(_url(household_a.id), headers=_auth(token_a), params={"q": "%_"})
    assert [d["title"] for d in resp.json()["items"]] == ["Rechnung 100%_Strom"]


def test_list_documents_combined_filter_and_search(client, household_a, token_a, many_documents):
    resp = client.get(
        _url(household_a.id), headers=_auth(token_a), params={"category": "invoice", "q": "vertrag"}
    )
    assert resp.json() == {"items": [], "total": 0}


def test_list_documents_pagination(client, household_a, token_a, many_documents):
    page1 = client.get(_url(household_a.id), headers=_auth(token_a), params={"limit": 3, "offset": 0}).json()
    page2 = client.get(_url(household_a.id), headers=_auth(token_a), params={"limit": 3, "offset": 3}).json()
    assert page1["total"] == page2["total"] == 4
    assert len(page1["items"]) == 3
    assert len(page2["items"]) == 1
    assert not {d["id"] for d in page1["items"]} & {d["id"] for d in page2["items"]}


@pytest.mark.parametrize("params", [{"category": "recipe"}, {"limit": 0}, {"limit": 201}, {"offset": -1}])
def test_list_documents_invalid_params(client, household_a, token_a, params):
    resp = client.get(_url(household_a.id), headers=_auth(token_a), params=params)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Validierung
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "   "},
        {"title": "x" * 151},
        {"category": "recipe"},
        {"notes": "x" * 2001},
        {"expiry_date": "not-a-date"},
    ],
)
def test_create_document_validation(client, db, household_a, user_a, token_a, payload):
    sf = _make_file(db, household_a, user_a)
    body = {"title": "Dokument", "file_id": str(sf.id), **payload}
    resp = client.post(_url(household_a.id), headers=_auth(token_a), json=body)
    assert resp.status_code == 422


def test_create_document_requires_file_id(client, household_a, token_a):
    resp = client.post(_url(household_a.id), headers=_auth(token_a), json={"title": "Ohne Datei"})
    assert resp.status_code == 422


@pytest.mark.parametrize("payload", [{"title": None}, {"category": None}, {"title": ""}, {"category": "x"}])
def test_update_document_validation(client, household_a, token_a, document_a, payload):
    resp = client.patch(_url(household_a.id, str(document_a.id)), headers=_auth(token_a), json=payload)
    assert resp.status_code == 422


def test_upload_document_invalid_metadata_does_not_store_file(client, household_a, token_a):
    with patch("app.routers.files._storage") as mock_storage:
        resp = client.post(
            _url(household_a.id, "upload"),
            headers=_auth(token_a),
            files={"file": ("a.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
            data={"category": "recipe"},
        )
    assert resp.status_code == 422
    mock_storage.save.assert_not_called()


def test_upload_document_rejects_fake_pdf(client, household_a, token_a):
    resp = _upload(client, household_a.id, token_a, data=b"<html></html>")
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_TYPE_NOT_ALLOWED"


def test_create_document_with_foreign_file(client, household_a, token_a, stored_file_b):
    resp = client.post(
        _url(household_a.id),
        headers=_auth(token_a),
        json={"title": "Fremd", "file_id": str(stored_file_b.id)},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_MISMATCH"


def test_create_document_with_file_already_used(client, household_a, token_a, document_a):
    resp = client.post(
        _url(household_a.id),
        headers=_auth(token_a),
        json={"title": "Doppelt", "file_id": str(document_a.file_id)},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_IN_USE"


def test_create_document_with_pet_photo(client, db, household_a, token_a, pet_a, stored_file_a):
    pet_a.photo_file_id = stored_file_a.id
    db.commit()
    resp = client.post(
        _url(household_a.id),
        headers=_auth(token_a),
        json={"title": "Katzenfoto", "file_id": str(stored_file_a.id)},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_IN_USE"


# ---------------------------------------------------------------------------
# Speicher-Quota
# ---------------------------------------------------------------------------


def test_storage_usage(client, household_a, token_a, document_a, document_b):
    with patch("app.routers.files.settings.household_storage_quota_mb", 5):
        resp = client.get(_url(household_a.id, "storage"), headers=_auth(token_a))
    assert resp.status_code == 200
    assert resp.json() == {"used_bytes": 2048, "quota_bytes": 5 * 1024 * 1024}


def test_upload_document_quota_exceeded(client, db, household_a, user_a, token_a):
    _make_file(db, household_a, user_a, size=1024 * 1024 - 10)
    with patch("app.routers.files.settings.household_storage_quota_mb", 1):
        resp = _upload(client, household_a.id, token_a)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "STORAGE_QUOTA_EXCEEDED"
    assert db.query(Document).count() == 0


def test_upload_document_quota_counts_only_own_household(client, db, household_b, user_b, household_a, token_a):
    _make_file(db, household_b, user_b, size=1024 * 1024)
    with patch("app.routers.files.settings.household_storage_quota_mb", 1):
        resp = _upload(client, household_a.id, token_a)
    assert resp.status_code == 201


def test_files_upload_respects_quota(client, db, household_a, user_a, token_a):
    _make_file(db, household_a, user_a, size=1024 * 1024)
    with patch("app.routers.files.settings.household_storage_quota_mb", 1), \
            patch("app.routers.files._storage") as mock_storage:
        resp = client.post(
            f"/api/households/{household_a.id}/files/",
            headers=_auth(token_a),
            files={"file": ("a.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "STORAGE_QUOTA_EXCEEDED"
    mock_storage.save.assert_not_called()


# ---------------------------------------------------------------------------
# Cross-Household-Scoping: jeder Endpoint → 403
# ---------------------------------------------------------------------------


def test_cross_household_list(client, household_b, token_a, document_b):
    assert client.get(_url(household_b.id), headers=_auth(token_a)).status_code == 403


def test_cross_household_storage(client, household_b, token_a):
    assert client.get(_url(household_b.id, "storage"), headers=_auth(token_a)).status_code == 403


def test_cross_household_get(client, household_b, token_a, document_b):
    resp = client.get(_url(household_b.id, str(document_b.id)), headers=_auth(token_a))
    assert resp.status_code == 403


def test_cross_household_create(client, household_b, token_a, stored_file_b):
    resp = client.post(
        _url(household_b.id),
        headers=_auth(token_a),
        json={"title": "Hack", "file_id": str(stored_file_b.id)},
    )
    assert resp.status_code == 403


def test_cross_household_upload(client, household_b, token_a, user_b):
    with patch("app.routers.files._storage") as mock_storage:
        resp = client.post(
            _url(household_b.id, "upload"),
            headers=_auth(token_a),
            files={"file": ("a.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        )
    assert resp.status_code == 403
    mock_storage.save.assert_not_called()


def test_cross_household_update(client, household_b, token_a, document_b):
    resp = client.patch(
        _url(household_b.id, str(document_b.id)), headers=_auth(token_a), json={"title": "Hack"}
    )
    assert resp.status_code == 403


def test_cross_household_delete(client, db, household_b, token_a, document_b):
    resp = client.delete(_url(household_b.id, str(document_b.id)), headers=_auth(token_a))
    assert resp.status_code == 403
    db.expire_all()
    assert db.get(Document, document_b.id) is not None


def test_foreign_document_via_own_household_is_404(client, household_a, token_a, document_b):
    """Fremde Dokument-ID über den eigenen Household-Pfad → 404, nicht lesbar."""
    for method in ("get", "patch", "delete"):
        kwargs = {"json": {"title": "x"}} if method == "patch" else {}
        resp = getattr(client, method)(_url(household_a.id, str(document_b.id)), headers=_auth(token_a), **kwargs)
        assert resp.status_code == 404, method
        assert resp.json()["detail"]["code"] == "DOCUMENT_NOT_FOUND"


def test_unauthenticated_rejected(client, household_a, document_a):
    assert client.get(_url(household_a.id)).status_code == 401
