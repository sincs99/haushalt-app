"""Upload rollback regressions; no external services or existing upload files."""

import io
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy.exc import DBAPIError
from starlette.datastructures import Headers

from app.models import StoredFile
from app.routers import files
from app.services.storage import LocalStorageService


def _upload(name="fixture.pdf"):
    return UploadFile(
        file=io.BytesIO(b"%PDF-1.7 fixture"), filename=name,
        headers=Headers({"content-type": "application/pdf"}),
    )


@pytest.fixture
def upload_storage(tmp_path, monkeypatch):
    storage = LocalStorageService(str(tmp_path))
    monkeypatch.setattr(files, "_storage", storage)
    return tmp_path


def _blobs(path):
    return [item for item in path.rglob("*") if item.is_file()]


def test_reject_control_character_before_save(db, household_a, user_a, upload_storage):
    with pytest.raises(HTTPException):
        with files.upload_transaction(db):
            files.store_upload(db, household_a.id, user_a.id, _upload("bad\x00.pdf"))
    assert _blobs(upload_storage) == []
    assert db.query(StoredFile).count() == 0


def test_failed_flush_cleans_current_blob(db, household_a, user_a, upload_storage, monkeypatch):
    household_id, user_id = household_a.id, user_a.id

    def fail_flush(*args, **kwargs):
        raise RuntimeError("injected metadata write failure")

    with monkeypatch.context() as patch:
        patch.setattr(db, "flush", fail_flush)
        with pytest.raises(RuntimeError, match="metadata"):
            with files.upload_transaction(db):
                files.store_upload(db, household_id, user_id, _upload())
    assert _blobs(upload_storage) == []
    assert db.query(StoredFile).count() == 0


def test_commit_failure_cleans_entire_batch_but_retains_existing(
    db, household_a, user_a, upload_storage, monkeypatch,
):
    household_id, user_id = household_a.id, user_a.id
    with files.upload_transaction(db):
        existing = files.store_upload(db, household_id, user_id, _upload())
    retained = upload_storage / existing.storage_path

    def fail_commit():
        raise RuntimeError("injected commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="commit"):
            with files.upload_transaction(db):
                files.store_upload(db, household_id, user_id, _upload("first.pdf"))
                files.store_upload(db, household_id, user_id, _upload("second.pdf"))
    assert _blobs(upload_storage) == [retained]
    assert retained.read_bytes() == b"%PDF-1.7 fixture"
    assert db.query(StoredFile).count() == 1


def test_second_invalid_upload_rolls_back_first(db, household_a, user_a, upload_storage):
    with pytest.raises(HTTPException):
        with files.upload_transaction(db):
            files.store_upload(db, household_a.id, user_a.id, _upload())
            files.store_upload(db, household_a.id, user_a.id, _upload("bad\x00.pdf"))
    assert _blobs(upload_storage) == []
    assert db.query(StoredFile).count() == 0


def test_indeterminate_commit_retains_blob_for_reconciliation(
    db, household_a, user_a, upload_storage, monkeypatch, caplog,
):
    household_id, user_id = household_a.id, user_a.id

    def lost_connection():
        raise DBAPIError("COMMIT", {}, OSError("connection lost"), connection_invalidated=True)

    with monkeypatch.context() as patch:
        patch.setattr(db, "commit", lost_connection)
        with pytest.raises(DBAPIError):
            with files.upload_transaction(db):
                files.store_upload(db, household_id, user_id, _upload())
    assert len(_blobs(upload_storage)) == 1
    assert "commit outcome unknown" in caplog.text


def test_partial_disk_write_is_removed(tmp_path, monkeypatch):
    real_open = Path.open

    class BrokenWriter:
        def __init__(self, target):
            self.target = target

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.target.close()

        def write(self, data):
            self.target.write(data[:3])
            self.target.flush()
            raise OSError("injected disk full")

        def close(self):
            self.target.close()

    def broken_open(path, mode="r", *args, **kwargs):
        target = real_open(path, mode, *args, **kwargs)
        return BrokenWriter(target) if mode == "xb" else target

    monkeypatch.setattr(Path, "open", broken_open)
    with pytest.raises(OSError, match="disk full"):
        LocalStorageService(str(tmp_path)).save("fixture", "x.pdf", b"%PDF-fixture", ".pdf")
    assert _blobs(tmp_path) == []
