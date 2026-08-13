"""Assign SN-7 samples evenly across the six merchandise categories."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from vlm.scripts._dataset_manifest import (
    CONSOLIDATED_MANIFEST,
    MANIFEST_COLUMNS,
    SN7_DATASET_ROOT,
    SN7_DATASET_ID,
    manifest_sample_id,
    read_manifest_rows,
    resolve_manifest_image,
    update_dataset_fields,
)
from vlm.scripts._sn7_artifacts import (
    CATEGORIES,
    CATEGORY_OUTPUT_SUFFIXES as OUTPUT_SUFFIXES,
    FULL_BODY_CATEGORIES,
    HEAD_ONLY_CATEGORIES,
    IMAGE_SUFFIXES,
    find_generated_output,
)
from vlm.scripts._validation import validate_path_component


DEFAULT_DATASET = SN7_DATASET_ROOT
OUTPUT_COLUMNS = (
    "sample_id",
    "primary_category",
    "already_generated_category",
    "assignment_source",
    "image_path",
)


def parse_args() -> argparse.Namespace:
    """Parse category-assignment arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args()


def balanced_target_counts(total: int) -> dict[str, int]:
    """Return deterministic category targets whose sum equals ``total``."""
    base, remainder = divmod(total, len(CATEGORIES))
    return {
        category: base + int(index < remainder)
        for index, category in enumerate(CATEGORIES)
    }


def discover_generated(dataset_dir: Path) -> dict[str, str]:
    """Map completed sample directories to their existing category."""
    generated_root = dataset_dir / "generated"
    generated: dict[str, str] = {}
    for category in CATEGORIES:
        category_dir = generated_root / category
        if not category_dir.is_dir():
            continue
        for sample_dir in sorted(category_dir.iterdir()):
            if not sample_dir.is_dir() or sample_dir.name.startswith("_"):
                continue
            sample_id = validate_path_component(sample_dir.name, "sample ID")
            output_suffix = OUTPUT_SUFFIXES[category]
            if find_generated_output(sample_dir, sample_id, output_suffix) is None:
                continue
            previous = generated.setdefault(sample_id, category)
            if previous != category:
                raise ValueError(
                    f"Sample {sample_id} has outputs in multiple categories: "
                    f"{previous}, {category}"
                )
    return generated


def apply_balanced_assignment(rows: list[dict[str, Any]]) -> None:
    """Assign pending rows while preserving every existing generated category."""
    targets = balanced_target_counts(len(rows))
    counts = Counter(
        str(row.get("already_generated_category", ""))
        for row in rows
        if row.get("already_generated_category") in CATEGORIES
    )
    pending = [
        row for row in rows if row.get("already_generated_category") not in CATEGORIES
    ]
    for row in sorted(pending, key=lambda item: str(item["sample_id"])):
        available = [category for category in CATEGORIES if counts[category] < targets[category]]
        if available:
            category = min(
                available,
                key=lambda value: (counts[value], CATEGORIES.index(value)),
            )
        else:
            category = min(
                CATEGORIES,
                key=lambda value: (counts[value], CATEGORIES.index(value)),
            )
        row["primary_category"] = category
        row["assignment_source"] = "balanced"
        counts[category] += 1

    for row in rows:
        existing = str(row.get("already_generated_category", ""))
        if existing in CATEGORIES:
            row["primary_category"] = existing
            row["assignment_source"] = "existing_generated_output"


def read_manifest(dataset_dir: Path) -> list[dict[str, Any]]:
    """Read and validate the portable SN-7 manifest."""
    resolved_dataset = dataset_dir.resolve()
    manifest_path = (
        CONSOLIDATED_MANIFEST.resolve()
        if resolved_dataset == DEFAULT_DATASET.resolve()
        else resolved_dataset / "manifest.csv"
    )
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in read_manifest_rows(manifest_path, dataset_id=SN7_DATASET_ID):
        sample_id = manifest_sample_id(raw)
        if sample_id in seen:
            raise ValueError(f"Duplicate sample ID in manifest: {sample_id}")
        seen.add(sample_id)
        image_path = resolve_manifest_image(manifest_path, raw)
        if not image_path.is_file():
            raise FileNotFoundError(image_path)
        rows.append(
            {
                "sample_id": sample_id,
                "primary_category": "",
                "already_generated_category": "",
                "assignment_source": "",
                "image_path": image_path.relative_to(resolved_dataset).as_posix(),
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], fields: tuple[str, ...]) -> None:
    """Write an Excel-compatible CSV atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)


def main() -> None:
    """Write balanced assignments, category queues, and a summary."""
    args = parse_args()
    dataset_dir = args.dataset_dir.resolve()
    output_dir = args.output_dir or (
        dataset_dir / "reports" / "merchandise_category_assignment"
    )
    rows = read_manifest(dataset_dir)
    generated = discover_generated(dataset_dir)
    for row in rows:
        row["already_generated_category"] = generated.get(str(row["sample_id"]), "")
    apply_balanced_assignment(rows)
    rows.sort(key=lambda row: (CATEGORIES.index(str(row["primary_category"])), str(row["sample_id"])))
    write_csv(output_dir / "merchandise_category_assignments.csv", rows, OUTPUT_COLUMNS)
    if dataset_dir == DEFAULT_DATASET.resolve():
        update_dataset_fields(
            CONSOLIDATED_MANIFEST,
            SN7_DATASET_ID,
            {
                str(row["sample_id"]): {
                    "primary_category": str(row["primary_category"]),
                    "assignment_source": str(row["assignment_source"]),
                }
                for row in rows
            },
            MANIFEST_COLUMNS,
        )

    counts = Counter(str(row["primary_category"]) for row in rows)
    pending_counts: dict[str, int] = {}
    for category in CATEGORIES:
        pending = [
            str(row["sample_id"])
            for row in rows
            if row["primary_category"] == category
            and not row["already_generated_category"]
        ]
        list_path = output_dir / "sample_lists" / f"{category}.txt"
        list_path.parent.mkdir(parents=True, exist_ok=True)
        list_path.write_text(
            "\n".join(pending) + ("\n" if pending else ""), encoding="utf-8"
        )
        pending_counts[category] = len(pending)

    summary = {
        "schema_version": "sn7_category_assignment.v1",
        "sample_count": len(rows),
        "category_counts": {category: counts[category] for category in CATEGORIES},
        "pending_counts": pending_counts,
    }
    summary_path = output_dir / "assignment_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
