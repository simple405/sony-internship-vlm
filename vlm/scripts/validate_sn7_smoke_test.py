"""Validate the manifest-driven SN-7 smoke-test inputs before API submission."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from PIL import Image

from vlm.scripts._validation import resolve_manifest_path, validate_path_component


EXPECTED_CATEGORIES = {
    "backpack",
    "cake_roll",
    "dataset_figurine",
    "dataset_QSitFigures",
    "head_key_chain",
    "plush",
}


def parse_args() -> argparse.Namespace:
    """Parse SN-7 smoke-test validation arguments."""
    parser = argparse.ArgumentParser(description="Validate a prepared SN-7 smoke-test dataset.")
    parser.add_argument("--root", type=Path, default=Path("vlm/data/design_sheet_10610_smoke12"))
    return parser.parse_args()


def sha256(path: Path) -> str:
    """Return the SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    """Validate the SN-7 smoke dataset contract and image integrity."""
    args = parse_args()
    with (args.root / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        manifest = list(csv.DictReader(handle))
    with (args.root / "category_assignment.csv").open(encoding="utf-8-sig", newline="") as handle:
        assignments = list(csv.DictReader(handle))

    errors: list[str] = []
    sample_ids = [row.get("post_id", "") for row in manifest]
    if len(manifest) != 12:
        errors.append(f"expected 12 manifest rows, found {len(manifest)}")
    if len(sample_ids) != len(set(sample_ids)):
        errors.append("manifest sample IDs are not unique")
    manifest_by_id = {row.get("post_id", ""): row for row in manifest}
    for sample_id, row in manifest_by_id.items():
        try:
            validate_path_component(sample_id, "sample ID")
            image_path = resolve_manifest_path(
                args.root, row.get("image_path", ""), "image_path"
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not image_path.exists():
            errors.append(f"missing image: {sample_id}")
            continue
        try:
            with Image.open(image_path) as image:
                image.verify()
        except Exception as exc:
            errors.append(f"unreadable image: {sample_id}: {exc}")
            continue
        if sha256(image_path) != row.get("sha256"):
            errors.append(f"hash mismatch: {sample_id}")

    counts = Counter(row.get("primary_category", "") for row in assignments)
    if set(counts) != EXPECTED_CATEGORIES:
        errors.append(f"unexpected categories: {sorted(counts)}")
    for category in sorted(EXPECTED_CATEGORIES):
        if counts[category] != 2:
            errors.append(f"{category} has {counts[category]} samples, expected 2")
    assignment_ids = [row.get("sample_id", "") for row in assignments]
    if set(assignment_ids) != set(sample_ids):
        errors.append("assignment sample IDs do not exactly match manifest sample IDs")

    report = {
        "status": "ok" if not errors else "error",
        "manifest_rows": len(manifest),
        "readable_images": len(manifest) - sum(item.startswith("unreadable image") for item in errors),
        "unique_sample_ids": len(set(sample_ids)),
        "category_counts": dict(sorted(counts.items())),
        "errors": errors,
    }
    report_path = args.root / "reports" / "input_manifest_audit.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**report, "report_path": str(report_path)}, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
