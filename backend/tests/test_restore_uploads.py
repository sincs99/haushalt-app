"""Restore only disposable fixtures; never run Docker or contact a database."""

import io
import tarfile
import uuid
from pathlib import Path

import pytest

from scripts.restore_uploads import apply_stage, stage_archive


def make_archive(tmp_path, name="uploads/household/new.pdf", kind=tarfile.REGTYPE, data=b"new"):
    archive = tmp_path / "uploads.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        directory = tarfile.TarInfo("uploads")
        directory.type = tarfile.DIRTYPE
        output.addfile(directory)
        member = tarfile.TarInfo(name)
        member.type = kind
        member.linkname = "../../outside"
        member.size = len(data) if kind == tarfile.REGTYPE else 0
        output.addfile(member, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
    return archive


@pytest.fixture()
def uploads(tmp_path):
    root = tmp_path / "live"
    root.mkdir()
    (root / "old.pdf").write_bytes(b"original")
    return root


@pytest.mark.parametrize("name,kind", [
    ("../outside", tarfile.REGTYPE),
    ("/uploads/absolute", tarfile.REGTYPE),
    ("uploads/../outside", tarfile.REGTYPE),
    ("uploads/a\\outside", tarfile.REGTYPE),
    ("uploads/link", tarfile.SYMTYPE),
    ("uploads/hard", tarfile.LNKTYPE),
    ("uploads/device", tarfile.CHRTYPE),
    ("uploads/pipe", tarfile.FIFOTYPE),
    ("uploads/.restore-conflict/file", tarfile.REGTYPE),
])
def test_rejects_unsafe_archive_before_live_mutation(tmp_path, uploads, name, kind):
    archive = make_archive(tmp_path, name, kind)
    with pytest.raises(ValueError):
        stage_archive(archive, uploads, uuid.uuid4().hex)
    assert (uploads / "old.pdf").read_bytes() == b"original"
    assert list(uploads.iterdir()) == [uploads / "old.pdf"]


def test_stage_then_apply_replaces_only_validated_data(tmp_path, uploads):
    stage_id = uuid.uuid4().hex
    stage_archive(make_archive(tmp_path), uploads, stage_id)
    assert (uploads / "old.pdf").read_bytes() == b"original"
    assert not (uploads / "household").exists()
    apply_stage(uploads, stage_id)
    assert (uploads / "household" / "new.pdf").read_bytes() == b"new"
    assert not (uploads / "old.pdf").exists()
    assert not list(uploads.glob(".restore-*"))


def test_size_limit_preserves_live_files(tmp_path, uploads):
    with pytest.raises(ValueError, match="limits"):
        stage_archive(make_archive(tmp_path, data=b"12345"), uploads, uuid.uuid4().hex, max_bytes=4)
    assert (uploads / "old.pdf").read_bytes() == b"original"


def test_apply_failure_restores_previous_tree(tmp_path, uploads, monkeypatch):
    stage_id = uuid.uuid4().hex
    stage_archive(make_archive(tmp_path), uploads, stage_id)
    original_rename = Path.rename

    def fail_new_move(self, destination):
        if self.parent.name == "incoming":
            raise OSError("fixture disk failure")
        return original_rename(self, destination)

    monkeypatch.setattr(Path, "rename", fail_new_move)
    with pytest.raises(OSError, match="fixture"):
        apply_stage(uploads, stage_id)
    assert (uploads / "old.pdf").read_bytes() == b"original"
    assert not (uploads / "household").exists()
    assert (uploads / f".restore-{stage_id}" / "incoming" / "household" / "new.pdf").is_file()
    monkeypatch.setattr(Path, "rename", original_rename)
    apply_stage(uploads, stage_id)
    assert (uploads / "household" / "new.pdf").read_bytes() == b"new"
    assert not (uploads / "old.pdf").exists()


def test_unvalidated_stage_cannot_replace_files(uploads):
    with pytest.raises(ValueError, match="validated"):
        apply_stage(uploads, uuid.uuid4().hex)
    assert (uploads / "old.pdf").read_bytes() == b"original"
