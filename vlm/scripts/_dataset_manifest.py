"""Shared accessors for the consolidated local dataset manifest."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from vlm.scripts._validation import resolve_manifest_path, validate_path_component


DATA_ROOT = Path("vlm/data")
SN7_DATASET_ROOT = DATA_ROOT / "sn7_data_generation"
CONSOLIDATED_MANIFEST = SN7_DATASET_ROOT / "manifest.csv"
SN7_DATASET_ID = "design_sheet_10610"
MANIFEST_COLUMNS = (
    "dataset_id",
    "post_id",
    "sample_id",
    "image_path",
    "data_status",
    "source_dataset",
    "source_path",
    "original_file_name",
    "sha256",
    "width",
    "height",
    "extension",
    "primary_category",
    "candidate_categories",
    "assignment_source",
    "review_required",
    "crawl_label",
    "assignment_reason",
    "key_tags",
    "primary_score",
    "atomic_rules_used",
    "atomic_rules_status",
    "atomic_rules_error_type",
    "atomic_rules_error_reason",
    "atomic_rules_rejection_type",
)


def read_manifest_rows(
    path: Path,
    *,
    dataset_id: str | None = None,
) -> list[dict[str, str]]:
    """Read manifest rows and optionally select one consolidated dataset."""
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    if dataset_id and any(row.get("dataset_id") for row in rows):
        rows = [row for row in rows if row.get("dataset_id") == dataset_id]
    return rows


def manifest_sample_id(row: dict[str, str]) -> str:
    """Return and validate the canonical sample identifier for a manifest row."""
    return validate_path_component(
        row.get("sample_id") or row.get("post_id") or "",
        "sample ID",
    )


def index_manifest_rows(
    path: Path,
    *,
    dataset_id: str | None = None,
) -> dict[str, dict[str, str]]:
    """Read manifest rows into a duplicate-checked sample mapping."""
    indexed: dict[str, dict[str, str]] = {}
    for row in read_manifest_rows(path, dataset_id=dataset_id):
        sample_id = manifest_sample_id(row)
        if sample_id in indexed:
            raise ValueError(f"Duplicate sample ID in {path}: {sample_id}")
        indexed[sample_id] = row
    return indexed


def resolve_manifest_image(path: Path, row: dict[str, str]) -> Path:
    """Resolve an image path relative to the manifest that declares it."""
    manifest = path.resolve()
    root = DATA_ROOT.resolve() if manifest == CONSOLIDATED_MANIFEST.resolve() else manifest.parent
    return resolve_manifest_path(root, row.get("image_path", ""), "image_path")


def atomic_status_fields(atomic_root: Path, sample_id: str) -> dict[str, str]:
    """Return consolidated atomic extraction fields for one sample."""
    sample_root = atomic_root / sample_id
    error_path = sample_root / "error.json"
    if error_path.is_file():
        payload = json.loads(error_path.read_text(encoding="utf-8"))
        return {
            "atomic_rules_used": "true",
            "atomic_rules_status": "error",
            "atomic_rules_error_type": str(payload.get("error_type", "")),
            "atomic_rules_error_reason": str(payload.get("error", "")),
            "atomic_rules_rejection_type": str(payload.get("rejection_type", "")),
        }
    if (sample_root / "atomic_rules.json").is_file() or (
        sample_root / f"{sample_id}_atomic_rules.json"
    ).is_file():
        return {
            "atomic_rules_used": "true",
            "atomic_rules_status": "success",
            "atomic_rules_error_type": "",
            "atomic_rules_error_reason": "",
            "atomic_rules_rejection_type": "",
        }
    if (sample_root / "request_redacted.json").is_file():
        return {
            "atomic_rules_used": "true",
            "atomic_rules_status": "attempted_no_result",
            "atomic_rules_error_type": "",
            "atomic_rules_error_reason": "",
            "atomic_rules_rejection_type": "",
        }
    return {
        "atomic_rules_used": "false",
        "atomic_rules_status": "not_started",
        "atomic_rules_error_type": "",
        "atomic_rules_error_reason": "",
        "atomic_rules_rejection_type": "",
    }


def write_manifest_rows(
    path: Path,
    rows: Iterable[dict[str, Any]],
    fieldnames: Iterable[str],
) -> None:
    """Atomically write an Excel-compatible manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    fields = list(fieldnames)
    try:
        with temp.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def replace_dataset_rows(
    path: Path,
    dataset_id: str,
    replacement_rows: Iterable[dict[str, Any]],
    fieldnames: Iterable[str],
) -> None:
    """Replace one dataset slice while preserving all other consolidated rows."""
    existing = read_manifest_rows(path) if path.is_file() else []
    retained = [row for row in existing if row.get("dataset_id") != dataset_id]
    replacement = [{**row, "dataset_id": dataset_id} for row in replacement_rows]
    combined = retained + replacement
    combined.sort(
        key=lambda row: (
            str(row.get("dataset_id", "")),
            str(row.get("sample_id") or row.get("post_id") or ""),
        )
    )
    write_manifest_rows(path, combined, fieldnames)


def update_dataset_fields(
    path: Path,
    dataset_id: str,
    updates: dict[str, dict[str, Any]],
    fields: Iterable[str],
) -> None:
    """Update every row in one dataset slice without changing other columns."""
    rows = read_manifest_rows(path)
    dataset_ids = {
        manifest_sample_id(row)
        for row in rows
        if row.get("dataset_id") == dataset_id
    }
    if dataset_ids != set(updates):
        raise ValueError(
            f"Manifest/update sample IDs differ for {dataset_id}: "
            f"missing={sorted(dataset_ids - set(updates))[:10]}, "
            f"unknown={sorted(set(updates) - dataset_ids)[:10]}"
        )
    for row in rows:
        if row.get("dataset_id") != dataset_id:
            continue
        sample_id = manifest_sample_id(row)
        row.update(updates[sample_id])
    write_manifest_rows(path, rows, fields)
