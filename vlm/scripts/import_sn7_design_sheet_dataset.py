"""Import the three SN-7 source directories into the production dataset root."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from PIL import Image


SOURCES = {
    "cs": Path("vlm/data/safebooru_character_sheet"),
    "ta": Path("vlm/data/safebooru_turnaround"),
    "cd": Path("vlm/data/角色分解"),
}
CATEGORIES = (
    "head_key_chain",
    "cake_roll",
    "backpack",
    "plush",
    "dataset_QSitFigures",
    "dataset_figurine",
)
DIRECT_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
SUPPORTED_SUFFIXES = DIRECT_SUFFIXES | {".gif"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import the SN-7 10610-image design-sheet dataset.")
    parser.add_argument("--output-root", type=Path, default=Path("vlm/data/design_sheet_10610"))
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_image(source_path: Path, target_path: Path) -> tuple[int, int, str]:
    """Copy direct formats or convert a GIF first frame to PNG atomically."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if source_path.suffix.lower() == ".gif":
        target_path = target_path.with_suffix(".png")
        tmp_path = target_path.with_suffix(".png.part")
        with Image.open(source_path) as image:
            image.seek(0)
            image.convert("RGBA" if "A" in image.getbands() else "RGB").save(tmp_path, format="PNG")
        tmp_path.replace(target_path)
    elif not target_path.exists():
        shutil.copy2(source_path, target_path)
    with Image.open(target_path) as image:
        width, height = image.size
        image.verify()
    return width, height, target_path.suffix.lower()


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    output_root = args.output_root
    image_root = output_root / "image"
    rows: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    raw_ids: defaultdict[str, list[str]] = defaultdict(list)

    for source_name, source_root in SOURCES.items():
        for source_path in sorted(source_root.iterdir()):
            if not source_path.is_file() or source_path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            sample_id = f"{source_name}_{source_path.stem}"
            raw_ids[source_path.stem].append(sample_id)
            target_path = image_root / f"{sample_id}{source_path.suffix.lower()}"
            try:
                width, height, extension = import_image(source_path, target_path)
                final_path = target_path.with_suffix(extension)
                rows.append(
                    {
                        "post_id": sample_id,
                        "sample_id": sample_id,
                        "image_path": str(final_path.resolve()),
                        "source_dataset": source_name,
                        "source_path": str(source_path.resolve()),
                        "original_file_name": source_path.name,
                        "sha256": sha256(final_path),
                        "width": str(width),
                        "height": str(height),
                        "extension": extension,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                rejected.append(
                    {"source_dataset": source_name, "source_path": str(source_path.resolve()), "error": f"{type(exc).__name__}: {exc}"}
                )

    rows.sort(key=lambda row: row["sample_id"])
    manifest_fields = list(rows[0]) if rows else ["post_id", "sample_id", "image_path"]
    write_csv(output_root / "manifest.csv", rows, manifest_fields)
    with (output_root / "metadata.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    reports = output_root / "reports"
    write_csv(reports / "rejected_images.csv", rejected, ["source_dataset", "source_path", "error"])
    duplicate_rows = [
        {"raw_id": raw_id, "sample_ids": "|".join(sample_ids)}
        for raw_id, sample_ids in sorted(raw_ids.items())
        if len(sample_ids) > 1
    ]
    write_csv(reports / "duplicate_ids.csv", duplicate_rows, ["raw_id", "sample_ids"])

    assignments: list[dict[str, str]] = []
    for index, row in enumerate(rows):
        category = CATEGORIES[index % len(CATEGORIES)]
        assignments.append(
            {
                "sample_id": row["sample_id"],
                "primary_category": category,
                "assignment_source": "balanced_round_robin",
                "image_path": row["image_path"],
            }
        )
    assignment_root = reports / "merchandise_category_assignment"
    write_csv(
        assignment_root / "merchandise_category_assignments.csv",
        assignments,
        ["sample_id", "primary_category", "assignment_source", "image_path"],
    )
    counts = Counter(row["primary_category"] for row in assignments)
    for category in CATEGORIES:
        ids = [row["sample_id"] for row in assignments if row["primary_category"] == category]
        list_path = assignment_root / "sample_lists" / f"{category}.txt"
        list_path.parent.mkdir(parents=True, exist_ok=True)
        list_path.write_text("\n".join(ids) + ("\n" if ids else ""), encoding="utf-8")
    summary = {
        "status": "ok" if not rejected else "partial",
        "created_at": datetime.now().astimezone().isoformat(),
        "imported": len(rows),
        "rejected": len(rejected),
        "duplicate_raw_ids": len(duplicate_rows),
        "category_counts": dict(counts),
    }
    (reports / "import_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
