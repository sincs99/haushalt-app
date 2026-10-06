"""
Tests für das Dokumente-Modul (Ablage).

Stellt sicher, dass:
- CRUD inkl. Multipart-Upload und Löschen aller Dateien funktioniert
- Mehrseitige Dokumente: Seiten anhängen, entfernen, neu anordnen
- Liste nach Kategorie filtert, nach Titel sucht und paginiert
- Cross-Household-Zugriffe auf JEDEM Endpoint mit 403 abgelehnt werden
- Validierung und Speicher-Quota greifen
- Socket.IO-Events gesendet werden
"""

import io
import uuid
from unittest.mock import patch

import pytest

from app.models import Document, DocumentFile, StoredFile

PDF_BYTES = b"%PDF-1.7\n%test document\n"


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _url(household_id, suffix=""):
    return f"/api/households/{household_id}/documents/{suffix}"


def _upload(client, household_id, token, data=PDF_BYTES, name="vertrag.pdf", mime="application/pdf", pages=None, **form):
    pages = pages or [(name, data, mime)]
    with patch("app.routers.files._storage") as mock_storage:
        mock_storage.save.side_effect = lambda **kw: f"{household_id}/{uuid.uuid4()}{kw['ext']}"
        return client.post(
            _url(household_id, "upload"),
            headers=_auth(token),
            files=[("files", (n, io.BytesIO(d), m)) for n, d, m in pages],
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
    assert len(data["files"]) == 1
    assert data["files"][0]["mime_type"] == "application/pdf"
    assert data["files"][0]["original_name"] == "vertrag.pdf"

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
    assert resp.json()["files"][0]["mime_type"] == "image/jpeg"


def test_create_document_from_uploaded_file(client, db, household_a, user_a, token_a, _mock_socket_emit):
    sf = _make_file(db, household_a, user_a)
    resp = client.post(
        _url(household_a.id),
        headers=_auth(token_a),
        json={"title": "Hausratversicherung", "category": "insurance", "file_ids": [str(sf.id)]},
    )
    assert resp.status_code == 201
    assert [f["id"] for f in resp.json()["files"]] == [str(sf.id)]
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


def test_delete_document_removes_all_files(client, db, household_a, token_a, document_a, _mock_socket_emit):
    file_ids = [f.id for f in document_a.files]
    storage_paths = [f.storage_path for f in document_a.files]
    doc_id = document_a.id
    assert len(file_ids) == 2
    with patch("app.routers.files._storage") as mock_storage:
        resp = client.delete(_url(household_a.id, str(doc_id)), headers=_auth(token_a))
    assert resp.status_code == 204
    assert [c.args[0] for c in mock_storage.delete.call_args_list] == storage_paths

    db.expire_all()
    assert db.get(Document, doc_id) is None
    assert all(db.get(StoredFile, fid) is None for fid in file_ids)
    assert db.query(DocumentFile).count() == 0
    events = _events(_mock_socket_emit, "document_deleted")
    assert events == [
        (household_a.id, "document_deleted", {"id": str(doc_id), "file_ids": [str(f) for f in file_ids]})
    ]


def test_file_of_document_cannot_be_deleted_via_files(client, household_a, token_a, document_a):
    resp = client.delete(
        f"/api/households/{household_a.id}/files/{document_a.files[0].id}",
        headers=_auth(token_a),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_IN_USE"


def test_document_file_downloadable(client, household_a, token_a, document_a):
    with patch("app.routers.files._storage") as mock_storage:
        mock_storage.open.return_value = io.BytesIO(PDF_BYTES)
        resp = client.get(
            f"/api/households/{household_a.id}/files/{document_a.files[0].id}",
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
    body = {"title": "Dokument", "file_ids": [str(sf.id)], **payload}
    resp = client.post(_url(household_a.id), headers=_auth(token_a), json=body)
    assert resp.status_code == 422


@pytest.mark.parametrize("extra", [{}, {"file_ids": []}])
def test_create_document_requires_files(client, household_a, token_a, extra):
    resp = client.post(_url(household_a.id), headers=_auth(token_a), json={"title": "Ohne Datei", **extra})
    assert resp.status_code == 422


def test_create_document_duplicate_file_ids(client, db, household_a, user_a, token_a):
    sf = _make_file(db, household_a, user_a)
    resp = client.post(
        _url(household_a.id), headers=_auth(token_a), json={"title": "x", "file_ids": [str(sf.id)] * 2}
    )
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
            files={"files": ("a.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
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
        json={"title": "Fremd", "file_ids": [str(stored_file_b.id)]},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_MISMATCH"


def test_create_document_with_file_already_used(client, household_a, token_a, document_a):
    resp = client.post(
        _url(household_a.id),
        headers=_auth(token_a),
        json={"title": "Doppelt", "file_ids": [str(document_a.files[0].id)]},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_IN_USE"


def test_create_document_with_pet_photo(client, db, household_a, token_a, pet_a, stored_file_a):
    pet_a.photo_file_id = stored_file_a.id
    db.commit()
    resp = client.post(
        _url(household_a.id),
        headers=_auth(token_a),
        json={"title": "Katzenfoto", "file_ids": [str(stored_file_a.id)]},
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
    assert resp.json() == {"used_bytes": 2 * 2048, "quota_bytes": 5 * 1024 * 1024}


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
# Mehrseitige Dokumente
# ---------------------------------------------------------------------------


def test_upload_multi_page_document(client, db, household_a, token_a, _mock_socket_emit):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (20, 20), color="green").save(buf, format="PNG")
    resp = _upload(
        client, household_a.id, token_a,
        pages=[
            ("seite1.pdf", PDF_BYTES, "application/pdf"),
            ("seite2.png", buf.getvalue(), "image/png"),
            ("seite3.pdf", PDF_BYTES, "application/pdf"),
        ],
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "seite1"
    assert [f["original_name"] for f in data["files"]] == ["seite1.pdf", "seite2.png", "seite3.pdf"]
    assert data["files"][1]["mime_type"] == "image/jpeg"
    assert len(_events(_mock_socket_emit, "document_created")) == 1


def test_upload_multi_page_all_or_nothing(client, db, household_a, token_a):
    """Ungültige dritte Seite → nichts wird angelegt, gespeicherte Dateien werden entfernt."""
    with patch("app.routers.files._storage") as mock_storage:
        mock_storage.save.side_effect = lambda **kw: f"{household_a.id}/{uuid.uuid4()}{kw['ext']}"
        resp = client.post(
            _url(household_a.id, "upload"),
            headers=_auth(token_a),
            files=[
                ("files", ("1.pdf", io.BytesIO(PDF_BYTES), "application/pdf")),
                ("files", ("2.pdf", io.BytesIO(PDF_BYTES), "application/pdf")),
                ("files", ("3.pdf", io.BytesIO(b"<html>"), "application/pdf")),
            ],
        )
    assert resp.status_code == 422
    assert mock_storage.delete.call_count == 2
    assert db.query(Document).count() == 0
    assert db.query(StoredFile).count() == 0


def test_create_document_with_multiple_files_keeps_order(client, db, household_a, user_a, token_a):
    files = [_make_file(db, household_a, user_a) for _ in range(3)]
    ids = [str(files[2].id), str(files[0].id), str(files[1].id)]
    resp = client.post(_url(household_a.id), headers=_auth(token_a), json={"title": "Scan", "file_ids": ids})
    assert resp.status_code == 201
    assert [f["id"] for f in resp.json()["files"]] == ids


def test_create_document_too_many_files(client, db, household_a, user_a, token_a):
    from app.routers.documents import MAX_FILES_PER_DOCUMENT

    ids = [str(_make_file(db, household_a, user_a).id) for _ in range(MAX_FILES_PER_DOCUMENT + 1)]
    resp = client.post(_url(household_a.id), headers=_auth(token_a), json={"title": "Viel", "file_ids": ids})
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "DOCUMENT_TOO_MANY_FILES"


def test_add_files_to_document(client, db, household_a, user_a, token_a, document_a, _mock_socket_emit):
    new = _make_file(db, household_a, user_a)
    before = [str(f.id) for f in document_a.files]
    resp = client.post(
        _url(household_a.id, f"{document_a.id}/files"), headers=_auth(token_a), json={"file_ids": [str(new.id)]}
    )
    assert resp.status_code == 200
    assert [f["id"] for f in resp.json()["files"]] == before + [str(new.id)]
    assert len(_events(_mock_socket_emit, "document_updated")) == 1


def test_add_files_already_used(client, household_a, token_a, document_a):
    resp = client.post(
        _url(household_a.id, f"{document_a.id}/files"),
        headers=_auth(token_a),
        json={"file_ids": [str(document_a.files[0].id)]},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_IN_USE"


def test_add_files_respects_max(client, db, household_a, user_a, token_a):
    from app.routers.documents import MAX_FILES_PER_DOCUMENT
    from tests.conftest import _make_document

    doc = _make_document(db, household_a, user_a, "Voll", "other", pages=MAX_FILES_PER_DOCUMENT)
    new = _make_file(db, household_a, user_a)
    resp = client.post(
        _url(household_a.id, f"{doc.id}/files"), headers=_auth(token_a), json={"file_ids": [str(new.id)]}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "DOCUMENT_TOO_MANY_FILES"


def test_reorder_document_files(client, household_a, token_a, document_a, _mock_socket_emit):
    reversed_ids = [str(f.id) for f in reversed(document_a.files)]
    resp = client.put(
        _url(household_a.id, f"{document_a.id}/files/order"), headers=_auth(token_a), json={"file_ids": reversed_ids}
    )
    assert resp.status_code == 200
    assert [f["id"] for f in resp.json()["files"]] == reversed_ids
    # Reihenfolge ist persistent
    again = client.get(_url(household_a.id, str(document_a.id)), headers=_auth(token_a)).json()
    assert [f["id"] for f in again["files"]] == reversed_ids
    assert len(_events(_mock_socket_emit, "document_updated")) == 1


def test_reorder_requires_exact_file_set(client, db, household_a, user_a, token_a, document_a):
    first = str(document_a.files[0].id)
    other = str(_make_file(db, household_a, user_a).id)
    for ids in ([first], [first, other]):
        resp = client.put(
            _url(household_a.id, f"{document_a.id}/files/order"), headers=_auth(token_a), json={"file_ids": ids}
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "FILE_MISMATCH"


def test_remove_document_file(client, db, household_a, token_a, document_a, _mock_socket_emit):
    first, second = document_a.files
    first_id, first_path, second_id = first.id, first.storage_path, str(second.id)
    with patch("app.routers.files._storage") as mock_storage:
        resp = client.delete(_url(household_a.id, f"{document_a.id}/files/{first_id}"), headers=_auth(token_a))
    assert resp.status_code == 200
    assert [f["id"] for f in resp.json()["files"]] == [second_id]
    mock_storage.delete.assert_called_once_with(first_path)
    db.expire_all()
    assert db.get(StoredFile, first_id) is None
    assert len(_events(_mock_socket_emit, "document_updated")) == 1


def test_remove_last_document_file_rejected(client, household_a, token_a, document_a):
    first, second = (str(f.id) for f in document_a.files)
    with patch("app.routers.files._storage"):
        assert client.delete(
            _url(household_a.id, f"{document_a.id}/files/{first}"), headers=_auth(token_a)
        ).status_code == 200
        resp = client.delete(_url(household_a.id, f"{document_a.id}/files/{second}"), headers=_auth(token_a))
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "DOCUMENT_LAST_FILE"


def test_remove_file_not_in_document(client, db, household_a, user_a, token_a, document_a):
    other = _make_file(db, household_a, user_a)
    resp = client.delete(_url(household_a.id, f"{document_a.id}/files/{other.id}"), headers=_auth(token_a))
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "FILE_NOT_FOUND"


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
        json={"title": "Hack", "file_ids": [str(stored_file_b.id)]},
    )
    assert resp.status_code == 403


def test_cross_household_upload(client, household_b, token_a, user_b):
    with patch("app.routers.files._storage") as mock_storage:
        resp = client.post(
            _url(household_b.id, "upload"),
            headers=_auth(token_a),
            files={"files": ("a.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
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


def test_cross_household_add_files(client, household_b, token_a, document_b, stored_file_b):
    resp = client.post(
        _url(household_b.id, f"{document_b.id}/files"),
        headers=_auth(token_a),
        json={"file_ids": [str(stored_file_b.id)]},
    )
    assert resp.status_code == 403


def test_cross_household_reorder_files(client, household_b, token_a, document_b):
    resp = client.put(
        _url(household_b.id, f"{document_b.id}/files/order"),
        headers=_auth(token_a),
        json={"file_ids": [str(document_b.files[0].id)]},
    )
    assert resp.status_code == 403


def test_cross_household_remove_file(client, household_b, token_a, document_b):
    resp = client.delete(
        _url(household_b.id, f"{document_b.id}/files/{document_b.files[0].id}"), headers=_auth(token_a)
    )
    assert resp.status_code == 403


def test_add_foreign_file_to_own_document(client, household_a, token_a, document_a, stored_file_b):
    resp = client.post(
        _url(household_a.id, f"{document_a.id}/files"),
        headers=_auth(token_a),
        json={"file_ids": [str(stored_file_b.id)]},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_MISMATCH"


def test_foreign_document_via_own_household_is_404(client, household_a, token_a, document_b):
    """Fremde Dokument-ID über den eigenen Household-Pfad → 404, nicht lesbar."""
    for method in ("get", "patch", "delete"):
        kwargs = {"json": {"title": "x"}} if method == "patch" else {}
        resp = getattr(client, method)(_url(household_a.id, str(document_b.id)), headers=_auth(token_a), **kwargs)
        assert resp.status_code == 404, method
        assert resp.json()["detail"]["code"] == "DOCUMENT_NOT_FOUND"


def test_unauthenticated_rejected(client, household_a, document_a):
    assert client.get(_url(household_a.id)).status_code == 401
