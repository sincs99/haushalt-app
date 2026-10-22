"""Portable persisted keys must preserve files without weakening path confinement."""

import uuid

import pytest

from app.services.storage import LocalStorageService


def test_saved_key_matches_inventory_on_every_platform(tmp_path, monkeypatch):
    object_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    monkeypatch.setattr("app.services.storage.uuid.uuid4", lambda: object_id)
    storage = LocalStorageService(str(tmp_path))

    key = storage.save("household", "invoice.pdf", b"%PDF-invoice", ".pdf")

    assert key == f"household/{object_id}.pdf"
    assert [path for path, _mtime in storage.list_files()] == [key]


@pytest.mark.parametrize("separator", ["/", "\\"])
def test_existing_key_can_be_read_and_deleted_on_every_platform(tmp_path, separator):
    storage = LocalStorageService(str(tmp_path))
    directory = tmp_path / "household"
    directory.mkdir()
    target = directory / "existing.pdf"
    target.write_bytes(b"%PDF-existing")
    key = f"household{separator}existing.pdf"

    with storage.open(key) as stream:
        assert stream.read() == b"%PDF-existing"
    storage.delete(key)

    assert not target.exists()


@pytest.mark.parametrize("key", [
    "../outside.pdf", r"..\outside.pdf", r"household\..\..\outside.pdf",
    "/outside.pdf", r"\outside.pdf", r"C:\outside.pdf", "C:outside.pdf",
    r"\\server\share\outside.pdf", "household/file.pdf:stream", "", ".",
])
@pytest.mark.parametrize("operation", ["open", "delete", "delete_household"])
def test_legacy_path_support_rejects_unsafe_paths(tmp_path, key, operation):
    storage = LocalStorageService(str(tmp_path / "uploads"))
    storage.upload_dir.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"keep")

    with pytest.raises(ValueError):
        getattr(storage, operation)(key)

    assert outside.read_bytes() == b"keep"
    assert storage.upload_dir.is_dir()


def test_resolved_symlink_cannot_escape_storage(tmp_path):
    storage = LocalStorageService(str(tmp_path / "uploads"))
    storage.upload_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "keep.pdf"
    target.write_bytes(b"keep")
    try:
        (storage.upload_dir / "linked").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Creating symlinks is unavailable on this host: {exc}")

    for operation in (storage.open, storage.delete):
        with pytest.raises(ValueError):
            operation(r"linked\keep.pdf")

    assert target.read_bytes() == b"keep"
