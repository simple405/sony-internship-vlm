"""Assign SN-7 samples evenly across the six merchandise categories."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image

from vlm.scripts._validation import resolve_manifest_path, validate_path_component


DEFAULT_DATASET = Path("vlm/data/design_sheet_10610")
CATEGORIES = (
    "head_key_chain",
    "cake_roll",
    "backpack",
    "plush",
    "dataset_QSitFigures",
    "dataset_figurine",
)
HEAD_ONLY_CATEGORIES = CATEGORIES[:3]
FULL_BODY_CATEGORIES = CATEGORIES[3:]
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
OUTPUT_SUFFIXES = {
    "head_key_chain": "head_keychain",
    "cake_roll": "cake_roll",
    "backpack": "backpack",
    "plush": "plush",
    "dataset_QSitFigures": "SitFigures",
    "dataset_figurine": "figurine",
}
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
            candidates = [
                sample_dir / f"{sample_id}_{output_suffix}{extension}"
                for extension in IMAGE_SUFFIXES
            ]
            valid_output = False
            for candidate in candidates:
                if not candidate.is_file() or candidate.stat().st_size <= 0:
                    continue
                try:
                    with Image.open(candidate) as image:
                        image.verify()
                except Exception:
                    continue
                valid_output = True
                break
            if not valid_output:
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
    manifest_path = dataset_dir / "manifest.csv"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            sample_id = validate_path_component(
                raw.get("sample_id") or raw.get("post_id") or "", "sample ID"
            )
            if sample_id in seen:
                raise ValueError(f"Duplicate sample ID in manifest: {sample_id}")
            seen.add(sample_id)
            image_path = resolve_manifest_path(
                dataset_dir, raw.get("image_path", ""), "image_path"
            )
            if not image_path.is_file():
                raise FileNotFoundError(image_path)
            rows.append(
                {
                    "sample_id": sample_id,
                    "primary_category": "",
                    "already_generated_category": "",
                    "assignment_source": "",
                    "image_path": image_path.relative_to(dataset_dir.resolve()).as_posix(),
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
