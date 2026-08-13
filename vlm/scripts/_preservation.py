"""Non-destructive publication helpers for generated directories."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from vlm.scripts._paths import DATA_ROOT


def _path_exists(path: Path) -> bool:
    """Return true for normal paths and broken symlinks."""
    return path.exists() or path.is_symlink()


def _archive_container(destination: Path, protected_root: Path) -> Path:
    destination = destination.parent.resolve() / destination.name
    protected_root = protected_root.resolve()
    if destination == protected_root:
        raise ValueError(f"Refusing to archive protected root: {destination}")
    if destination != protected_root and protected_root in destination.parents:
        relative = destination.relative_to(protected_root)
        if relative.parts[0] == "_archive":
            raise ValueError(f"Refusing to archive an archive path: {destination}")
        return protected_root / "_archive" / relative
    return destination.parent / "_archive" / destination.name


def archive_existing_path(
    destination: Path,
    *,
    protected_root: Path | None = None,
) -> Path | None:
    """Move an existing path into a unique versioned archive without deleting it."""
    destination = destination.parent.resolve() / destination.name
    if not _path_exists(destination):
        return None

    archive_container = _archive_container(
        destination,
        protected_root if protected_root is not None else DATA_ROOT,
    )
    archive_container.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    archive_path = archive_container / f"{timestamp}-{uuid4().hex[:8]}"
    destination.replace(archive_path)
    return archive_path


def publish_staged_directory(
    staged: Path,
    destination: Path,
    *,
    protected_root: Path | None = None,
) -> Path | None:
    """Publish a staged directory, archiving and restoring the old version on failure."""
    staged = staged.parent.resolve() / staged.name
    destination = destination.parent.resolve() / destination.name
    if not staged.is_dir():
        raise FileNotFoundError(f"Staged directory not found: {staged}")

    archived = archive_existing_path(
        destination,
        protected_root=protected_root,
    )
    try:
        staged.replace(destination)
    except Exception:
        if archived is not None and not _path_exists(destination):
            archived.replace(destination)
        raise
    return archived
