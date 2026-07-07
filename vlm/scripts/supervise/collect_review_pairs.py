"""Collect source/generated image pairs for offline supervision review."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[3]))

from vlm.scripts.supervise.review_schemas import (  # noqa: E402
    CATEGORIES,
    FULL_BODY_CATEGORIES,
    HEAD_ONLY_CATEGORIES,
    IMAGE_SUFFIXES,
    ReviewPair,
    to_jsonable,
)


DEFAULT_DATASET = Path("vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20")
DEFAULT_GENERATED_ROOT = DEFAULT_DATASET / "generated"
DEFAULT_OUTPUT = DEFAULT_DATASET / "reports" / "supervision_review" / "latest" / "review_pairs.jsonl"
DEFAULT_SEED_CASES = Path("vlm/experiments/supervision/seed_cases.jsonl")

# Note 1: File names differ by generator and by product category. This table is
# only a priority hint for choosing among already existing outputs; it must not
# create, rename, or delete any generated image.
CATEGORY_GENERATED_STEMS = {
    "head_key_chain": ["{id}_head_keychain", "{id}_head_key_chain"],
    "backpack": ["{id}_backpack"],
    "cake_roll": ["{id}_cake_roll"],
    "plush": ["{id}_plush"],
    "dataset_QSitFigures": ["{id}_SitFigures", "{id}_qsitfigures", "{id}_q_sit_figures"],
    "dataset_figurine": ["{id}_figurine", "{id}_pvc_figurine"],
}


def parse_args() -> argparse.Namespace:
    # Note 2: All defaults are relative to the workspace root. This matches the
    # rest of the vlm scripts and keeps Windows paths with Chinese folder names
    # out of command lines unless the caller needs to override them.
    parser = argparse.ArgumentParser(description="Collect ReviewPair JSONL for offline supervision.")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--generated-root", type=Path, default=DEFAULT_GENERATED_ROOT)
    parser.add_argument("--category", choices=CATEGORIES)
    parser.add_argument("--all-categories", action="store_true")
    parser.add_argument("--seed-cases", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skipped-output", type=Path)
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    # Note 3: utf-8-sig accepts files that were opened by Excel or some Windows
    # tools and gained a BOM. Raising the line number makes broken seed files
    # quick to fix by hand.
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
    return rows


def read_manifest(path: Path) -> dict[str, dict[str, str]]:
    # Note 4: The manifest is optional for path pairing. If it is missing, the
    # review can still proceed with images and rules; reports just lose tag
    # context for that sample.
    rows: dict[str, dict[str, str]] = {}
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            sample_id = str(row.get("post_id") or "").strip()
            if sample_id:
                rows[sample_id] = row
    return rows


def generated_category_dir(generated_root: Path, category: str) -> Path:
    # Note 5: Flat layout — each category is a direct child of generated_root.
    # e.g. generated/backpack/, generated/head_key_chain/, etc.
    return generated_root / category


def is_usable_generated_image(path: Path) -> bool:
    # Note 6: The collector is deliberately conservative: originals, rules,
    # partial downloads, and debug files are evidence/provenance, not generated
    # outputs to be reviewed as product sheets.
    name = path.name.lower()
    if not path.is_file():
        return False
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        return False
    if name.endswith(".part"):
        return False
    if "_original." in name or name.endswith("_original" + path.suffix.lower()):
        return False
    if "_atomic_rules" in name or "debug" in name:
        return False
    return True


def generated_priority(path: Path, sample_id: str, category: str) -> tuple[int, str]:
    # Note 7: Lower numbers win. Explicit product filenames beat generic
    # Image.png, and both beat unknown sample-prefixed images. The file name is
    # the tiebreaker so selection stays deterministic across machines.
    stem = path.stem
    for index, template in enumerate(CATEGORY_GENERATED_STEMS.get(category, [])):
        if stem == template.format(id=sample_id):
            return (index, path.name)
    if stem.lower() == "image":
        return (50, path.name)
    if stem.startswith(sample_id):
        return (80, path.name)
    return (100, path.name)


def find_generated_image(sample_dir: Path, sample_id: str, category: str) -> tuple[Path | None, list[Path]]:
    # Note 8: Returning all candidates is important for auditability. The runner
    # uses the first path, while reports can still show what alternatives were
    # present in the sample folder.
    if not sample_dir.exists():
        return None, []
    candidates = sorted(
        (path for path in sample_dir.iterdir() if is_usable_generated_image(path)),
        key=lambda path: generated_priority(path, sample_id, category),
    )
    return (candidates[0] if candidates else None), candidates


def find_source_image(dataset_dir: Path, sample_dir: Path, sample_id: str) -> Path | None:
    # Note 9: Source lookup mirrors the historical dataset layouts. Prefer the
    # canonical image directory, then fall back to originals stored beside a
    # generated result, then to atomic_rules provenance copies.
    image_dir = dataset_dir / "image"
    for suffix in IMAGE_SUFFIXES:
        exact = image_dir / f"{sample_id}{suffix}"
        if exact.exists():
            return exact
    if image_dir.exists():
        matches = sorted(
            path
            for path in image_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() in IMAGE_SUFFIXES
            and path.name.startswith(f"{sample_id}_")
        )
        if matches:
            return matches[0]
    generated_originals = sorted(
        path
        for path in sample_dir.glob(f"{sample_id}_original.*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    if generated_originals:
        return generated_originals[0]
    atomic_original = dataset_dir / "atomic_rules" / sample_id / f"{sample_id}_original.jpg"
    if atomic_original.exists():
        return atomic_original
    return None


def find_atomic_rules(dataset_dir: Path, sample_dir: Path, sample_id: str) -> Path | None:
    # Note 10: atomic_rules are optional evidence. Missing rules should not block
    # visual review, because the project rule is that images outrank extracted
    # tags or rules when they conflict.
    candidates = [
        dataset_dir / "atomic_rules" / sample_id / f"{sample_id}_atomic_rules.json",
        sample_dir / f"{sample_id}_atomic_rules.json",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def discover_category_sample_ids(generated_root: Path, category: str) -> list[str]:
    # Note 11: Category scans only include numeric sample folders and skip
    # underscore-prefixed debug folders. That prevents _debug/2166018 from being
    # mistaken for a real review target.
    category_dir = generated_category_dir(generated_root, category)
    if not category_dir.exists():
        return []
    return sorted(
        child.name
        for child in category_dir.iterdir()
        if child.is_dir() and not child.name.startswith("_") and child.name.isdigit()
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    # Note 12: JSONL makes large runs appendable and easy to inspect one line at
    # a time. This v1 writer rewrites the full file so reruns produce a clean
    # latest snapshot.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def resolve_pair(
    *,
    dataset_dir: Path,
    generated_root: Path,
    manifest: dict[str, dict[str, str]],
    sample_id: str,
    category: str,
    seed_case: dict[str, Any] | None = None,
) -> tuple[ReviewPair | None, dict[str, Any] | None]:
    # Note 13: resolve_pair never raises for missing sample assets. Batch review
    # should continue and record a skipped row, especially for known content
    # safety blocks or missing generated outputs.
    sample_dir = generated_category_dir(generated_root, category) / sample_id
    generated_path, generated_candidates = find_generated_image(sample_dir, sample_id, category)
    source_path = find_source_image(dataset_dir, sample_dir, sample_id)
    rules_path = find_atomic_rules(dataset_dir, sample_dir, sample_id)

    missing = []
    if not sample_dir.exists():
        missing.append("generated_sample_dir")
    if source_path is None:
        missing.append("source_image")
    if generated_path is None:
        missing.append("generated_image")
    if missing:
        # Note 14: Keep enough information in skipped rows for a maintainer to
        # decide whether the fix is "regenerate", "replace source", or "correct
        # the seed case/category" without rerunning the collector.
        return None, {
            "sample_id": sample_id,
            "category": category,
            "reason": "missing_" + "_and_".join(missing),
            "sample_dir": str(sample_dir),
            "source_image_path": str(source_path) if source_path else "",
            "generated_candidates": [str(path) for path in generated_candidates],
            "seed_case": seed_case or {},
        }

    pair = ReviewPair(
        # Note 15: All paths are stored as strings for JSON compatibility. The
        # runner converts them back to Path objects only at the file-access edge.
        sample_id=sample_id,
        category=category,
        source_image_path=str(source_path),
        generated_image_path=str(generated_path),
        generated_candidates=[str(path) for path in generated_candidates],
        atomic_rules_path=str(rules_path) if rules_path else None,
        manifest_row=manifest.get(sample_id, {}),
        seed_case=seed_case or {},
    )
    return pair, None


def main() -> None:
    args = parse_args()
    if not args.category and not args.all_categories and not args.seed_cases:
        raise SystemExit("Pass --category, --all-categories, or --seed-cases.")

    manifest = read_manifest(args.dataset_dir / "manifest.csv")
    requests: list[tuple[str, str, dict[str, Any]]] = []
    if args.seed_cases:
        # Note 16: Seed mode preserves the human/expected labels from the JSONL
        # row. Category scan mode has no seed_case metadata and is better for
        # broad inventory checks.
        for seed in read_jsonl(args.seed_cases):
            requests.append((str(seed["sample_id"]), str(seed["category"]), seed))
    else:
        categories = CATEGORIES if args.all_categories else (args.category,)
        for category in categories:
            assert category is not None
            for sample_id in discover_category_sample_ids(args.generated_root, category):
                requests.append((sample_id, category, {}))

    pairs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for sample_id, category, seed_case in requests:
        # Note 17: Deduplication is per sample/category, not sample alone. The
        # same original can legitimately be reviewed as multiple merchandise
        # products in different folders.
        key = (sample_id, category)
        if key in seen:
            continue
        seen.add(key)
        pair, skipped_row = resolve_pair(
            dataset_dir=args.dataset_dir,
            generated_root=args.generated_root,
            manifest=manifest,
            sample_id=sample_id,
            category=category,
            seed_case=seed_case,
        )
        if pair is None:
            assert skipped_row is not None
            skipped.append(skipped_row)
        else:
            pairs.append(to_jsonable(pair))

    skipped_output = args.skipped_output or (args.output.parent / "skipped_pairs.jsonl")
    write_jsonl(args.output, pairs)
    write_jsonl(skipped_output, skipped)
    print(
        json.dumps(
            {
                "status": "finished",
                "pairs": len(pairs),
                "skipped": len(skipped),
                "output": str(args.output),
                "skipped_output": str(skipped_output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
