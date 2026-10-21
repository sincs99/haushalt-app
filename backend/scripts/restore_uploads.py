"""Validate and stage an operator-selected upload archive before replacing files.

The application must be stopped for ``apply``. This command never restores SQL.
Only regular files/directories below uploads/ are accepted; tar extraction APIs
and archive-supplied ownership, permissions and links are deliberately not used.
"""

import argparse
import json
import shutil
import tarfile
import uuid
from pathlib import Path, PurePosixPath

DEFAULT_ROOT = Path("/app/data/uploads")
MAX_FILES = 100_000
MAX_BYTES = 20 * 1024**3


def _stage_path(root: Path, stage_id: str) -> Path:
    if uuid.UUID(stage_id).hex != stage_id:
        raise ValueError("Stage ID must be a lowercase UUID hex value")
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Upload root must be an existing real directory")
    root = root.resolve(strict=True)
    result = root / f".restore-{stage_id}"
    if result.is_symlink():
        raise ValueError("Staging path must not be a link")
    return result


def _member_path(member: tarfile.TarInfo) -> tuple[str, ...]:
    name = member.name.rstrip("/")
    if "\\" in name or ":" in name or any(ord(c) < 32 for c in name):
        raise ValueError("Invalid archive path")
    parts = name.split("/")
    if not parts or parts[0] != "uploads" or any(p in ("", ".", "..") for p in parts):
        raise ValueError("Archive entries must stay below uploads/")
    if any(p.startswith(".restore-") for p in parts):
        raise ValueError("Reserved staging name in archive")
    if not (member.isdir() or member.isfile()) or member.issparse():
        raise ValueError("Only regular files and directories are accepted")
    if len(parts) == 1 and not member.isdir():
        raise ValueError("uploads must be a directory")
    # PurePosixPath is only used after rejecting components it would normalize.
    return PurePosixPath(name).parts[1:]


def stage_archive(archive: Path, root: Path, stage_id: str, max_bytes: int = MAX_BYTES) -> None:
    stage = _stage_path(root, stage_id)
    root = stage.parent
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    stage.mkdir(mode=0o700)  # exclusive; no reuse of a prior staging directory
    incoming = stage / "incoming"
    incoming.mkdir(mode=0o700)
    try:
        with tarfile.open(archive, "r:gz") as source:
            members: list[tuple[tarfile.TarInfo, tuple[str, ...]]] = []
            seen: set[tuple[str, ...]] = set()
            total = 0
            for member in source:
                parts = _member_path(member)
                if parts in seen:
                    raise ValueError("Duplicate archive path")
                seen.add(parts)
                total += member.size
                if member.size < 0 or total > max_bytes or len(seen) > MAX_FILES:
                    raise ValueError("Archive exceeds configured extraction limits")
                members.append((member, parts))
            if not members:
                raise ValueError("Empty upload archive")
            if total > shutil.disk_usage(root).free:
                raise ValueError("Insufficient free space for staged upload data")
            for member, parts in members:
                target = incoming.joinpath(*parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True, mode=0o700)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                content = source.extractfile(member)
                if content is None:
                    raise ValueError("Missing archive content")
                with content, target.open("xb") as output:
                    remaining = member.size
                    while remaining:
                        chunk = content.read(min(remaining, 1024 * 1024))
                        if not chunk:
                            raise ValueError("Truncated archive content")
                        output.write(chunk)
                        remaining -= len(chunk)
        (stage / "ready.json").write_text(json.dumps({"bytes": total}), encoding="utf-8")
    except BaseException:
        shutil.rmtree(stage)
        raise


def apply_stage(root: Path, stage_id: str) -> None:
    stage = _stage_path(root, stage_id)
    root = stage.parent
    if not (stage / "ready.json").is_file():
        raise ValueError("No successfully validated stage")
    incoming = stage / "incoming"
    if incoming.is_symlink() or not incoming.is_dir():
        raise ValueError("Invalid staged upload directory")
    for entry in incoming.rglob("*"):
        if entry.is_symlink() or (not entry.is_dir() and not entry.is_file()):
            raise ValueError("Staged data contains a non-regular entry")
        if entry.is_file() and entry.stat().st_nlink != 1:
            raise ValueError("Staged data contains a hard link")
    existing = [entry for entry in root.iterdir() if entry != stage]
    if any(entry.name.startswith(".restore-") for entry in existing):
        raise ValueError("Resolve other retained restore stages before applying")
    previous = stage / "previous"
    previous.mkdir(mode=0o700)
    moved_old: list[Path] = []
    moved_new: list[Path] = []
    try:
        for entry in existing:
            saved = previous / entry.name
            entry.rename(saved)
            moved_old.append(saved)
        for entry in incoming.iterdir():
            destination = root / entry.name
            entry.rename(destination)
            moved_new.append(destination)
    except BaseException:
        # Keep the validated stage on failure; callers must keep the app stopped.
        for entry in reversed(moved_new):
            entry.rename(incoming / entry.name)
        for entry in reversed(moved_old):
            entry.rename(root / entry.name)
        previous.rmdir()
        raise
    shutil.rmtree(stage)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "apply", "discard"))
    parser.add_argument("stage_id")
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    args = parser.parse_args()
    if args.action == "stage":
        if args.archive is None:
            parser.error("stage requires --archive")
        stage_archive(args.archive, args.root, args.stage_id, args.max_bytes)
    elif args.action == "apply":
        apply_stage(args.root, args.stage_id)
    else:
        stage = _stage_path(args.root, args.stage_id)
        if stage.exists():
            shutil.rmtree(stage)


if __name__ == "__main__":
    main()
