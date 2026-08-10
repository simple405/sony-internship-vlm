"""Prepare a five-category SN-6 supervision selection manifest.

The selector consumes the paired SN-6 manifest, excludes samples that already
have generated front-view outputs, and assigns fresh samples evenly across the
five categories that were not covered by the first figurine pilot.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[3]))

from vlm.scripts._paths import TMP_DIR, VLM_ROOT
from vlm.scripts.generate.generate_paired_front_view import (
    DEFAULT_INPUT_ROOT,
    DEFAULT_OUTPUT_ROOT,
    Sample,
    read_manifest,
    select_samples,
)
from vlm.scripts.generate.prompt_renderer import CATEGORY_REQUIREMENTS
from vlm.scripts.generate.runninghub_client import IMAGE_SUFFIXES
from vlm.scripts._validation import validate_path_component


FIVE_CATEGORY_SUPERVISION_ROOT = TMP_DIR / "five_category_supervision_v1"
DEFAULT_SELECTION_MANIFEST = FIVE_CATEGORY_SUPERVISION_ROOT / "selection_manifest.csv"
DEFAULT_CATEGORIES = (
    "head_key_chain",
    "cake_roll",
    "backpack",
    "plush",
    "dataset_QSitFigures",
)
DEFAULT_SAMPLES_PER_CATEGORY = 10
OUTPUT_COLUMNS = (
    "category",
    "sample_id",
    "image_path",
    "gold_json",
    "source_sha256",
    "gold_sha256",
    "output_dir",
)


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_generated_sample_dir(path: Path) -> bool:
    """Return whether a directory contains a generated front-view image."""
    sample_id = path.name
    for suffix in IMAGE_SUFFIXES:
        if (path / f"{sample_id}_q_front_view{suffix}").is_file():
            return True
        if any(path.glob(f"{sample_id}_*_front_view{suffix}")):
            return True
    return False


def discover_processed_sample_ids(output_root: Path) -> set[str]:
    """Find sample IDs already used by legacy or category front-view outputs."""
    processed: set[str] = set()
    summary_path = output_root / "batch_summary.json"
    if summary_path.is_file():
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8-sig"))
            processed.update(str(item) for item in payload.get("selected", []))
        except json.JSONDecodeError:
            pass

    if not output_root.is_dir():
        return processed
    for first_level in output_root.iterdir():
        if not first_level.is_dir() or first_level.name.startswith("_"):
            continue
        if _is_generated_sample_dir(first_level):
            processed.add(validate_path_component(first_level.name, "sample ID"))
            continue
        if first_level.name not in CATEGORY_REQUIREMENTS:
            continue
        for sample_dir in first_level.iterdir():
            if sample_dir.is_dir() and _is_generated_sample_dir(sample_dir):
                processed.add(validate_path_component(sample_dir.name, "sample ID"))
    return processed


def _display_path(path: Path, repo_root: Path) -> str:
    """Prefer repo-relative paths in the manifest."""
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def build_selection_rows(
    samples: Iterable[Sample],
    *,
    processed_ids: set[str],
    categories: tuple[str, ...] = DEFAULT_CATEGORIES,
    samples_per_category: int = DEFAULT_SAMPLES_PER_CATEGORY,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    repo_root: Path = VLM_ROOT.parent,
) -> list[dict[str, str]]:
    """Assign unprocessed samples evenly across the requested categories."""
    if samples_per_category < 1:
        raise ValueError("samples_per_category must be >= 1")
    for category in categories:
        if category not in CATEGORY_REQUIREMENTS:
            raise ValueError(f"Unsupported category: {category}")
    needed = len(categories) * samples_per_category
    candidates = [
        sample for sample in samples if sample.sample_id not in processed_ids
    ]
    selected = select_samples(candidates, [], needed)
    if len(selected) < needed:
        raise ValueError(f"Need {needed} unprocessed samples, found {len(selected)}")

    rows: list[dict[str, str]] = []
    for index, sample in enumerate(selected):
        category = categories[index // samples_per_category]
        if sample.gold_path is None:
            raise ValueError(f"Missing gold JSON for sample: {sample.sample_id}")
        rows.append(
            {
                "category": category,
                "sample_id": sample.sample_id,
                "image_path": _display_path(sample.image_path, repo_root),
                "gold_json": _display_path(sample.gold_path, repo_root),
                "source_sha256": _sha256(sample.image_path),
                "gold_sha256": _sha256(sample.gold_path),
                "output_dir": _display_path(
                    output_root / category / sample.sample_id,
                    repo_root,
                ),
            }
        )
    return rows


def write_selection_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    """Write the category selection manifest as UTF-8 CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        with temp.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def parse_args() -> argparse.Namespace:
    """Parse selection-manifest arguments."""
    parser = argparse.ArgumentParser(
        description="Select five-category SN-6 samples for generation supervision."
    )
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_SELECTION_MANIFEST)
    parser.add_argument("--samples-per-category", type=int, default=DEFAULT_SAMPLES_PER_CATEGORY)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    """Write or preview the five-category selection manifest."""
    args = parse_args()
    samples = read_manifest(args.input_root)
    processed = discover_processed_sample_ids(args.output_root)
    rows = build_selection_rows(
        samples,
        processed_ids=processed,
        samples_per_category=args.samples_per_category,
        output_root=args.output_root,
    )
    if not args.dry_run:
        write_selection_manifest(args.output, rows)
    counts = {category: 0 for category in DEFAULT_CATEGORIES}
    for row in rows:
        counts[row["category"]] += 1
    print(
        json.dumps(
            {
                "status": "dry_run" if args.dry_run else "written",
                "output": str(args.output),
                "selected": len(rows),
                "processed_excluded": len(processed),
                "category_counts": counts,
                "sample_ids": [row["sample_id"] for row in rows],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

