"""
Tests für Datei-Referenzen zwischen Pets und Dokumenten sowie das Aufräumen
verwaister Uploads.

Stellt sicher, dass:
- ein Pet-Foto keine Datei verwenden kann, die einem Dokument oder anderen Pet gehört
- das Löschen eines Pets keine fremd referenzierte Datei mitlöscht
- unreferenzierte Uploads nach der Frist entfernt werden, referenzierte nie
- die Dokumentliste keine N+1-Queries pro Dokument/Seite auslöst
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import event

from app.models import Document, DocumentFile, Pet, StoredFile
from app.routers.files import ORPHAN_FILE_GRACE, delete_orphan_files
from tests.conftest import _make_document, engine_test


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _image_file(db, household, user, created_at=None) -> StoredFile:
    sf = StoredFile(
        id=uuid.uuid4(),
        household_id=household.id,
        original_name="bild.jpeg",
        mime_type="image/jpeg",
        size_bytes=100,
        storage_path=f"{household.id}/{uuid.uuid4()}.jpeg",
        uploaded_by_user_id=user.id,
        created_at=created_at or datetime.now(timezone.utc),
    )
    db.add(sf)
    db.commit()
    db.refresh(sf)
    return sf


def _image_document(db, household, user) -> Document:
    sf = _image_file(db, household, user)
    doc = Document(household_id=household.id, title="Garantie", category="warranty", created_by_user_id=user.id)
    doc.file_links.append(DocumentFile(file=sf, position=0))
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def _set_photo(client, household, token, pet, file_id):
    return client.patch(
        f"/api/households/{household.id}/pets/{pet.id}",
        headers=_auth(token),
        json={"photo_file_id": str(file_id)},
    )


# ---------------------------------------------------------------------------
# Pet-Foto ↔ Dokument / anderes Pet
# ---------------------------------------------------------------------------


def test_pet_photo_cannot_use_document_page(client, db, household_a, user_a, token_a, pet_a):
    doc = _image_document(db, household_a, user_a)
    resp = _set_photo(client, household_a, token_a, pet_a, doc.files[0].id)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_IN_USE"


def test_pet_photo_cannot_use_other_pets_photo(client, db, household_a, user_a, token_a, pet_a):
    sf = _image_file(db, household_a, user_a)
    other = Pet(household_id=household_a.id, name="Mimi", species="cat", photo_file_id=sf.id)
    db.add(other)
    db.commit()
    resp = _set_photo(client, household_a, token_a, pet_a, sf.id)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_IN_USE"


def test_pet_photo_can_be_set_again_to_same_file(client, db, household_a, user_a, token_a, pet_a):
    sf = _image_file(db, household_a, user_a)
    assert _set_photo(client, household_a, token_a, pet_a, sf.id).status_code == 200
    assert _set_photo(client, household_a, token_a, pet_a, sf.id).status_code == 200


def test_document_cannot_claim_pet_photo(client, db, household_a, user_a, token_a, pet_a):
    sf = _image_file(db, household_a, user_a)
    assert _set_photo(client, household_a, token_a, pet_a, sf.id).status_code == 200
    resp = client.post(
        f"/api/households/{household_a.id}/documents/",
        headers=_auth(token_a),
        json={"title": "x", "file_ids": [str(sf.id)]},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_IN_USE"


def test_delete_pet_keeps_file_referenced_by_document(client, db, household_a, user_a, token_a, pet_a):
    """Altbestand: Pet-Foto zeigt auf eine Dokumentseite → Seite bleibt erhalten."""
    doc = _image_document(db, household_a, user_a)
    file_id = doc.files[0].id
    pet_a.photo_file_id = file_id
    db.commit()

    with patch("app.routers.files._storage") as mock_storage:
        resp = client.delete(f"/api/households/{household_a.id}/pets/{pet_a.id}", headers=_auth(token_a))
    assert resp.status_code == 204
    mock_storage.delete.assert_not_called()
    db.expire_all()
    assert db.get(StoredFile, file_id) is not None
    assert [f.id for f in db.get(Document, doc.id).files] == [file_id]


def test_delete_pet_keeps_file_shared_with_other_pet(client, db, household_a, user_a, token_a, pet_a):
    sf = _image_file(db, household_a, user_a)
    other = Pet(household_id=household_a.id, name="Mimi", species="cat", photo_file_id=sf.id)
    pet_a.photo_file_id = sf.id
    db.add(other)
    db.commit()

    with patch("app.routers.files._storage") as mock_storage:
        resp = client.delete(f"/api/households/{household_a.id}/pets/{pet_a.id}", headers=_auth(token_a))
    assert resp.status_code == 204
    mock_storage.delete.assert_not_called()
    db.expire_all()
    assert db.get(Pet, other.id).photo_file_id == sf.id


def test_delete_pet_removes_own_photo(client, db, household_a, user_a, token_a, pet_a):
    sf = _image_file(db, household_a, user_a)
    file_id, path = sf.id, sf.storage_path
    pet_a.photo_file_id = file_id
    db.commit()

    with patch("app.routers.files._storage") as mock_storage:
        resp = client.delete(f"/api/households/{household_a.id}/pets/{pet_a.id}", headers=_auth(token_a))
    assert resp.status_code == 204
    mock_storage.delete.assert_called_once_with(path)
    db.expire_all()
    assert db.get(StoredFile, file_id) is None


# ---------------------------------------------------------------------------
# Verwaiste Uploads
# ---------------------------------------------------------------------------


def test_delete_orphan_files(db, household_a, user_a, pet_a):
    old = datetime.now(timezone.utc) - ORPHAN_FILE_GRACE - timedelta(minutes=5)
    orphan = _image_file(db, household_a, user_a, created_at=old)
    fresh_orphan = _image_file(db, household_a, user_a)
    pet_photo = _image_file(db, household_a, user_a, created_at=old)
    pet_a.photo_file_id = pet_photo.id
    db.commit()
    doc = _make_document(db, household_a, user_a, "Alt", "other")
    for link in doc.file_links:
        link.file.created_at = old
    db.commit()
    orphan_id, orphan_path = orphan.id, orphan.storage_path

    with patch("app.routers.files._storage") as mock_storage:
        deleted = delete_orphan_files(db)

    assert deleted == 1
    mock_storage.delete.assert_called_once_with(orphan_path)
    db.expire_all()
    assert db.get(StoredFile, orphan_id) is None
    assert db.get(StoredFile, fresh_orphan.id) is not None
    assert db.get(StoredFile, pet_photo.id) is not None
    assert len(db.get(Document, doc.id).files) == 1


def test_untracked_storage_files_are_removed_after_grace(db, household_a, user_a, tmp_path):
    """CASA-27: Datei auf der Platte ohne DB-Zeile (Commit gescheitert) → nach 24 h weg."""
    import os

    from app.routers.files import delete_untracked_storage_files
    from app.services.storage import LocalStorageService

    storage = LocalStorageService(str(tmp_path))
    tracked_path = storage.save(str(household_a.id), "a.pdf", b"%PDF-1", ".pdf")
    untracked_old = storage.save(str(household_a.id), "b.pdf", b"%PDF-2", ".pdf")
    untracked_new = storage.save(str(household_a.id), "c.pdf", b"%PDF-3", ".pdf")
    db.add(StoredFile(household_id=household_a.id, original_name="a.pdf", mime_type="application/pdf",
                      size_bytes=6, storage_path=tracked_path, uploaded_by_user_id=user_a.id))
    db.commit()
    old = (datetime.now(timezone.utc) - ORPHAN_FILE_GRACE - timedelta(hours=1)).timestamp()
    for path in (tracked_path, untracked_old):
        os.utime(tmp_path / path, (old, old))

    with patch("app.routers.files._storage", storage):
        assert delete_untracked_storage_files(db) == 1

    assert (tmp_path / tracked_path).exists()
    assert not (tmp_path / untracked_old).exists()
    assert (tmp_path / untracked_new).exists()


def test_upload_commit_failure_removes_file_from_storage(client, db, household_a, token_a):
    """CASA-27: scheitert der Commit nach dem Schreiben, bleibt keine Datei ohne Zeile liegen."""
    from sqlalchemy.exc import OperationalError

    def failing_commit():
        raise OperationalError("COMMIT", {}, Exception("connection lost"))

    with patch("app.routers.files._storage") as mock_storage, patch.object(db, "commit", failing_commit):
        mock_storage.save.return_value = f"{household_a.id}/x.pdf"
        resp = client.post(
            f"/api/households/{household_a.id}/files/",
            headers=_auth(token_a),
            files={"file": ("a.pdf", b"%PDF-1.4 test", "application/pdf")},
        )
    assert resp.status_code == 500
    mock_storage.delete.assert_called_once_with(f"{household_a.id}/x.pdf")


# ---------------------------------------------------------------------------
# Dokumentliste ohne N+1
# ---------------------------------------------------------------------------


def _count_selects(fn) -> int:
    count = 0

    def _before(conn, cursor, statement, *args):
        nonlocal count
        if statement.lstrip().upper().startswith("SELECT"):
            count += 1

    event.listen(engine_test, "before_cursor_execute", _before)
    try:
        fn()
    finally:
        event.remove(engine_test, "before_cursor_execute", _before)
    return count


def test_document_list_query_count_independent_of_size(client, db, household_a, user_a, token_a):
    url = f"/api/households/{household_a.id}/documents/"

    _make_document(db, household_a, user_a, "Eins", "other", pages=2)
    db.expire_all()
    few = _count_selects(lambda: client.get(url, headers=_auth(token_a)))

    for i in range(5):
        _make_document(db, household_a, user_a, f"Doc {i}", "other", pages=3)
    db.expire_all()
    many = _count_selects(lambda: client.get(url, headers=_auth(token_a)))

    assert many == few
