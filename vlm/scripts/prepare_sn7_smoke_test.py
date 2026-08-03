"""Prepare a deterministic 12-image SN-7 smoke-test input dataset.

The script copies two readable source images for each merchandise category into
an isolated directory, then writes the manifest and fixed category assignment
used by the existing Qwen, RunningHub, and packaging commands.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path

from PIL import Image


SOURCES = {
    "cs": Path("vlm/data/safebooru_character_sheet"),
    "ta": Path("vlm/data/safebooru_turnaround"),
    "cd": Path("vlm/data/角色分解"),
}
CATEGORY_SOURCES = {
    "head_key_chain": "cs",
    "cake_roll": "ta",
    "backpack": "cd",
    "plush": "cs",
    "dataset_QSitFigures": "ta",
    "dataset_figurine": "cd",
}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare the isolated SN-7 12-image smoke-test dataset.")
    parser.add_argument("--output-root", type=Path, default=Path("vlm/data/design_sheet_10610_smoke12"))
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def readable_images(source: Path) -> list[Path]:
    paths: list[Path] = []
    for path in sorted(source.iterdir()):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        try:
            with Image.open(path) as image:
                image.verify()
        except Exception:
            continue
        paths.append(path)
    return paths


def main() -> None:
    args = parse_args()
    image_root = args.output_root / "image"
    if args.output_root.exists() and not args.overwrite:
        raise SystemExit(f"Output root already exists: {args.output_root}. Pass --overwrite only after reviewing it.")
    if args.output_root.exists():
        shutil.rmtree(args.output_root)
    image_root.mkdir(parents=True)

    available = {name: readable_images(path) for name, path in SOURCES.items()}
    offsets = {name: 0 for name in SOURCES}
    manifest_rows: list[dict[str, str]] = []
    assignment_rows: list[dict[str, str]] = []
    for category, source_name in CATEGORY_SOURCES.items():
        selections = available[source_name][offsets[source_name] : offsets[source_name] + 2]
        offsets[source_name] += 2
        if len(selections) != 2:
            raise RuntimeError(f"Could not select two readable images from {SOURCES[source_name]}")
        for source_path in selections:
            sample_id = f"{source_name}_{source_path.stem}"
            target = image_root / f"{sample_id}{source_path.suffix.lower()}"
            shutil.copy2(source_path, target)
            with Image.open(target) as image:
                width, height = image.size
            manifest_rows.append(
                {
                    "post_id": sample_id,
                    "image_path": str(target.resolve()),
                    "source_dataset": source_name,
                    "source_path": str(source_path.resolve()),
                    "original_file_name": source_path.name,
                    "sha256": sha256(target),
                    "width": str(width),
                    "height": str(height),
                    "extension": target.suffix.lower(),
                }
            )
            assignment_rows.append(
                {
                    "sample_id": sample_id,
                    "primary_category": category,
                    "candidate_categories": category,
                    "assignment_source": "smoke_test_fixed",
                    "review_required": "false",
                    "image_path": str(target.resolve()),
                    "crawl_label": "",
                    "reason": "two_per_category_smoke_test",
                    "key_tags": "",
                    "primary_score": "",
                }
            )

    manifest_path = args.output_root / "manifest.csv"
    with manifest_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest_rows[0]))
        writer.writeheader()
        writer.writerows(manifest_rows)
    assignment_path = args.output_root / "category_assignment.csv"
    with assignment_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(assignment_rows[0]))
        writer.writeheader()
        writer.writerows(assignment_rows)
    (args.output_root / "selection.json").write_text(
        json.dumps({"sample_count": len(manifest_rows), "samples": manifest_rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"status": "prepared", "output_root": str(args.output_root), "sample_count": len(manifest_rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
