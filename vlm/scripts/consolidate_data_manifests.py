"""Merge local dataset manifests and SN-7 status into one authoritative CSV."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from vlm.scripts._dataset_manifest import (
    atomic_status_fields,
    CONSOLIDATED_MANIFEST,
    MANIFEST_COLUMNS,
    SN7_DATASET_ROOT,
    SN7_DATASET_ID,
    read_manifest_rows,
    write_manifest_rows,
)


LEGACY_DATASET_ID = "legacy_batch_1000"
DEFAULT_SN7_ROOT = SN7_DATASET_ROOT
def parse_args() -> argparse.Namespace:
    """Parse manifest consolidation arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=CONSOLIDATED_MANIFEST)
    parser.add_argument("--sn7-root", type=Path, default=DEFAULT_SN7_ROOT)
    parser.add_argument("--remove-merged-files", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    """Return a lowercase SHA-256 digest."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_legacy_image(data_root: Path, row: dict[str, str]) -> Path | None:
    expected_hash = row.get("sha256", "").lower()
    source_dirs = {
        "cs": data_root / "safebooru_character_sheet",
        "ta": data_root / "safebooru_turnaround",
        "cd": data_root / "角色分解",
    }
    candidates: list[Path] = []
    preferred = source_dirs.get(row.get("source_dataset", ""))
    if preferred:
        candidates.append(preferred / row.get("original_file_name", ""))
    for root in source_dirs.values():
        candidate = root / row.get("original_file_name", "")
        if candidate not in candidates:
            candidates.append(candidate)
    for candidate in candidates:
        if candidate.is_file() and (not expected_hash or sha256(candidate) == expected_hash):
            return candidate
    return None


def _legacy_rows(manifest: Path, data_root: Path) -> list[dict[str, str]]:
    rows = read_manifest_rows(manifest)
    if any(row.get("dataset_id") for row in rows):
        rows = [row for row in rows if row.get("dataset_id") == LEGACY_DATASET_ID]
    consolidated: list[dict[str, str]] = []
    for row in rows:
        sample_id = row.get("sample_id") or row.get("post_id") or ""
        image = _find_legacy_image(data_root, row)
        consolidated.append(
            {
                **row,
                "dataset_id": LEGACY_DATASET_ID,
                "post_id": sample_id,
                "sample_id": sample_id,
                "image_path": image.relative_to(data_root).as_posix() if image else "",
                "data_status": "available" if image else "missing_source",
                "atomic_rules_used": "false",
                "atomic_rules_status": "not_started",
            }
        )
    return consolidated


def _sn7_rows(manifest: Path, sn7_root: Path) -> list[dict[str, str]]:
    source_manifest = sn7_root / "manifest.csv"
    if source_manifest.is_file():
        rows = read_manifest_rows(
            source_manifest,
            dataset_id=(
                SN7_DATASET_ID
                if source_manifest.resolve() == manifest.resolve()
                else None
            ),
        )
    else:
        rows = read_manifest_rows(manifest, dataset_id=SN7_DATASET_ID)
    assignment_path = sn7_root / "category_assignment.csv"
    assignments = {
        row.get("sample_id", ""): row
        for row in read_manifest_rows(assignment_path)
    } if assignment_path.is_file() else {}
    data_root = sn7_root.resolve().parent
    consolidated: list[dict[str, str]] = []
    for row in rows:
        sample_id = row.get("sample_id") or row.get("post_id") or ""
        assignment = assignments.get(sample_id, row)
        raw_image = Path(row.get("image_path", ""))
        if raw_image.parts[:1] == (sn7_root.name,):
            image_path = raw_image
        elif raw_image.parts[:1] == ("image",):
            image_path = Path(sn7_root.name) / raw_image
        else:
            image_path = Path(sn7_root.name) / "image" / raw_image.name
        image = data_root / image_path
        consolidated.append(
            {
                **row,
                "dataset_id": SN7_DATASET_ID,
                "post_id": sample_id,
                "sample_id": sample_id,
                "image_path": image_path.as_posix(),
                "data_status": "available" if image.is_file() else "missing_source",
                "primary_category": assignment.get("primary_category", ""),
                "candidate_categories": assignment.get("candidate_categories", ""),
                "assignment_source": assignment.get("assignment_source", ""),
                "review_required": assignment.get("review_required", ""),
                "crawl_label": assignment.get("crawl_label", ""),
                "assignment_reason": assignment.get("reason", assignment.get("assignment_reason", "")),
                "key_tags": assignment.get("key_tags", ""),
                "primary_score": assignment.get("primary_score", ""),
                **atomic_status_fields(sn7_root / "atomic_rules", sample_id),
            }
        )
    return consolidated


def consolidate(args: argparse.Namespace) -> dict[str, Any]:
    """Write the consolidated manifest and optionally remove merged inputs."""
    manifest = args.manifest.resolve()
    sn7_root = args.sn7_root.resolve()
    data_root = sn7_root.parent
    legacy = _legacy_rows(manifest, data_root)
    sn7 = _sn7_rows(manifest, sn7_root)
    rows = legacy + sn7
    rows.sort(key=lambda row: (row["dataset_id"], row["sample_id"]))
    write_manifest_rows(manifest, rows, MANIFEST_COLUMNS)

    removed: list[str] = []
    if args.remove_merged_files:
        for path in (sn7_root / "manifest.csv", sn7_root / "category_assignment.csv"):
            if path.is_file() and path.resolve() != manifest:
                path.unlink()
                removed.append(str(path))

    summary = {
        "status": "ok",
        "manifest": str(manifest),
        "rows": len(rows),
        "legacy_rows": len(legacy),
        "sn7_rows": len(sn7),
        "missing_source": sum(row.get("data_status") != "available" for row in rows),
        "atomic_success": sum(row.get("atomic_rules_status") == "success" for row in sn7),
        "atomic_errors": sum(row.get("atomic_rules_status") == "error" for row in sn7),
        "removed": removed,
    }
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def main() -> None:
    """Run manifest consolidation."""
    consolidate(parse_args())


if __name__ == "__main__":
    main()
