"""Dateien auf PostgreSQL: Quota-Race (CASA-26), Waisen-Bereinigung (CASA-27),
exklusive Zuordnung einer Datei (CASA-28)."""

import io
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from app.core.error_codes import ErrorCode
from app.database import SessionLocal
from app.models import Document, DocumentFile, Pet, StoredFile
from app.routers import files as files_router
from app.services.storage import LocalStorageService
from tests.pg.harness import run_parallel, status_codes


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    """Echter Dateispeicher in einem Temp-Verzeichnis."""
    service = LocalStorageService(str(tmp_path))
    monkeypatch.setattr(files_router, "_storage", service)
    return service


def _pdf(size=1000) -> bytes:
    return b"%PDF-1.4\n" + os.urandom(size)


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), (1, 2, 3)).save(buf, "PNG")
    return buf.getvalue()


def _upload(client, hh, data=None, mime="application/pdf", name="a.pdf", i=0):
    return client.post(
        hh.url("/files/"), files={"file": (name, data or _pdf(), mime)}, headers=hh.headers(i)
    )


def test_parallel_uploads_respect_quota(client, household, monkeypatch):
    """CASA-26: 8 × 200 KB parallel bei 1 MB Quota → vorher 7 angenommen (1.4 MB)."""
    monkeypatch.setattr(files_router.settings, "household_storage_quota_mb", 1)

    results = run_parallel(lambda i: _upload(client, household, _pdf(200_000), i=i % 2), 8)
    codes = status_codes(results)
    assert set(codes) <= {201, 422}, codes
    assert codes.count(201) == 5, codes  # 5 × ~200 KB passen in 1 MB, die übrigen nicht
    for r in results:
        if r.status_code == 422:
            assert r.json()["detail"]["code"] == ErrorCode.STORAGE_QUOTA_EXCEEDED
    usage = client.get(household.url("/documents/storage"), headers=household.headers()).json()
    assert usage["used_bytes"] <= usage["quota_bytes"]


def test_parallel_documents_cannot_claim_same_file(client, household, db):
    """CASA-28: zwei Dokumente mit derselben Datei → genau eines, das andere FILE_IN_USE."""
    for _ in range(5):
        file_id = _upload(client, household).json()["id"]
        results = run_parallel(
            lambda i, file_id=file_id: client.post(
                household.url("/documents/"),
                json={"title": f"Doc{i}", "file_ids": [file_id]},
                headers=household.headers(i),
            ),
            2,
        )
        assert sorted(status_codes(results)) == [201, 422], status_codes(results)
        loser = next(r for r in results if r.status_code == 422)
        assert loser.json()["detail"]["code"] == ErrorCode.FILE_IN_USE
        db.expire_all()
        assert db.query(DocumentFile).filter(DocumentFile.file_id == uuid.UUID(file_id)).count() == 1


def test_pet_photo_and_document_never_share_a_file(client, household, db):
    """CASA-28: Pet-Foto-PATCH ‖ Dokument mit derselben Datei → nie beide (vorher 8/15)."""
    pet = client.post(household.url("/pets/"), json={"name": "Mia"}, headers=household.headers()).json()
    for _ in range(6):
        file_id = _upload(client, household, _png(), "image/png", "p.png").json()["id"]

        def act(i, file_id=file_id):
            if i == 0:
                return client.patch(
                    household.url(f"/pets/{pet['id']}"), json={"photo_file_id": file_id},
                    headers=household.headers(0),
                )
            return client.post(
                household.url("/documents/"), json={"title": "Scan", "file_ids": [file_id]},
                headers=household.headers(1),
            )

        codes = status_codes(run_parallel(act, 2))
        assert sorted(codes) in ([200, 422], [201, 422]), codes
        db.expire_all()
        on_pet = db.get(Pet, uuid.UUID(pet["id"])).photo_file_id == uuid.UUID(file_id)
        in_doc = db.query(DocumentFile).filter(DocumentFile.file_id == uuid.UUID(file_id)).count() == 1
        assert on_pet != in_doc
        client.patch(household.url(f"/pets/{pet['id']}"), json={"photo_file_id": None}, headers=household.headers())


def _age_file(file_id, hours=25):
    with SessionLocal() as s:
        f = s.get(StoredFile, uuid.UUID(file_id))
        f.created_at = datetime.now(timezone.utc) - timedelta(hours=hours)
        s.commit()


def test_orphan_cleanup_never_deletes_file_attached_meanwhile(client, household, db, storage):
    """CASA-27: Cleanup wählt die Datei aus, dann wird sie einem Dokument zugeordnet →
    das Löschen danach muss sie stehen lassen (vorher: Dokument ohne Seiten)."""
    file_id = _upload(client, household).json()["id"]
    _age_file(file_id)

    with SessionLocal() as cleanup:
        candidates = files_router.orphan_file_candidates(cleanup)
        assert uuid.UUID(file_id) in candidates

        attach = client.post(
            household.url("/documents/"), json={"title": "Mietvertrag", "file_ids": [file_id]},
            headers=household.headers(),
        )
        assert attach.status_code == 201

        files_router.delete_orphans(cleanup, candidates)

    doc = client.get(household.url(f"/documents/{attach.json()['id']}"), headers=household.headers()).json()
    assert [f["id"] for f in doc["files"]] == [file_id]
    path = db.get(StoredFile, uuid.UUID(file_id)).storage_path
    assert (storage.upload_dir / path).exists()


def test_orphan_cleanup_skips_file_locked_by_running_attach(client, household, storage):
    """Eine laufende Zuordnung (Zeile gesperrt) wird übersprungen statt blockiert/gelöscht."""
    file_id = _upload(client, household).json()["id"]
    _age_file(file_id)

    with SessionLocal() as attacher, SessionLocal() as cleanup:
        files_router.lock_files(attacher, [uuid.UUID(file_id)])
        assert files_router.delete_orphan_files(cleanup) == 0
        attacher.add(Document(household_id=household.id, title="T", category="other"))
        attacher.flush()
        doc = attacher.query(Document).filter_by(household_id=household.id, title="T").one()
        attacher.add(DocumentFile(document_id=doc.id, file_id=uuid.UUID(file_id), position=0))
        attacher.commit()

    with SessionLocal() as s:
        assert s.get(StoredFile, uuid.UUID(file_id)) is not None


def test_true_orphans_are_still_deleted(client, household, storage):
    file_id = _upload(client, household).json()["id"]
    with SessionLocal() as s:
        path = s.get(StoredFile, uuid.UUID(file_id)).storage_path
    _age_file(file_id)
    with SessionLocal() as cleanup:
        assert files_router.delete_orphan_files(cleanup) >= 1
    with SessionLocal() as s:
        assert s.get(StoredFile, uuid.UUID(file_id)) is None
    assert not (storage.upload_dir / path).exists()
