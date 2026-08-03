"""Write annotation xlsx files for completed RunningHub generation samples."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from vlm.scripts.build_safebooru_trial_dataset import write_xlsx


DEFAULT_GENERATED_ROOT = Path("vlm/data/design_sheet_10610/generated")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
CATEGORY_OUTPUT_SUFFIXES = {
    "head_key_chain": "head_keychain",
    "cake_roll": "cake_roll",
    "backpack": "backpack",
    "plush": "plush",
    "dataset_QSitFigures": "SitFigures",
    "dataset_figurine": "figurine",
}


def has_generated_image(sample_dir: Path, sample_id: str, output_suffix: str) -> bool:
    return any((sample_dir / f"{sample_id}_{output_suffix}{suffix}").exists() for suffix in IMAGE_SUFFIXES)


def find_atomic_rules(sample_dir: Path, sample_id: str) -> Path | None:
    for name in (f"{sample_id}_atomic_rules.json", "atomic_rules.json"):
        path = sample_dir / name
        if path.exists():
            return path
    return None


def sync_sample(sample_dir: Path, category: str, output_suffix: str) -> bool:
    sample_id = sample_dir.name
    workbook = sample_dir / f"{sample_id}.xlsx"
    if workbook.exists() or not has_generated_image(sample_dir, sample_id, output_suffix):
        return False
    atomic_rules = find_atomic_rules(sample_dir, sample_id)
    if atomic_rules is None:
        return False
    write_xlsx(atomic_rules, workbook, {}, category)
    return True


def sync_once(generated_root: Path) -> dict[str, int]:
    counts = {"scanned": 0, "written": 0}
    for category, output_suffix in CATEGORY_OUTPUT_SUFFIXES.items():
        category_dir = generated_root / category
        if not category_dir.exists():
            continue
        for sample_dir in category_dir.iterdir():
            if not sample_dir.is_dir() or sample_dir.name.startswith("_"):
                continue
            counts["scanned"] += 1
            counts["written"] += int(sync_sample(sample_dir, category, output_suffix))
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync xlsx files for completed RunningHub samples.")
    parser.add_argument("--generated-root", type=Path, default=DEFAULT_GENERATED_ROOT)
    parser.add_argument("--follow", action="store_true", help="Continue syncing images that arrive after startup.")
    parser.add_argument("--poll-interval", type=int, default=30)
    args = parser.parse_args()
    if args.poll_interval < 1:
        raise ValueError("--poll-interval must be at least 1")
    while True:
        counts = sync_once(args.generated_root)
        print(json.dumps({"status": "xlsx_sync", **counts}, ensure_ascii=False), flush=True)
        if not args.follow:
            return
        time.sleep(args.poll_interval)


if __name__ == "__main__":
    main()
