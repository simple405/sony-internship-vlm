"""CLI orchestration for the Safebooru supervision dataset workflow.

Each stage remains independently resumable. This wrapper only invokes stages in
order and never deletes or overwrites successful extraction/package outputs.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Safebooru crawl, extraction, and packaging stages.")
    parser.add_argument("--root", type=Path, default=Path("vlm/data/safebooru_2d"))
    parser.add_argument("--limit", type=int, default=3500)
    parser.add_argument("--pilot-limit", type=int, default=50)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--skip-crawl", action="store_true")
    parser.add_argument("--skip-extraction", action="store_true")
    parser.add_argument("--skip-package", action="store_true")
    parser.add_argument("--full-extraction", action="store_true", help="Use --limit 0 for extraction after pilot approval.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def run(command: list[str]) -> None:
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, check=True)


def main() -> None:
    args = parse_args()
    python = sys.executable
    root = args.root
    manifest = root / "manifest.csv"
    if not args.skip_crawl:
        run([
            python, "-m", "vlm.scripts.crawl_safebooru",
            "--view-preset", "aniplex_supervision_full_body_strict",
            "--out-dir", str(root),
            "--limit", str(args.limit),
            "--existing-metadata", str(root / "metadata.jsonl"),
            "--allow-character-duplicates",
            "--incremental-write",
            "--sleep", "1.0",
            "--request-sleep", "1.0",
            "--max-pages-per-query", "100",
        ])
    if not args.skip_extraction:
        extraction_limit = "0" if args.full_extraction else str(args.pilot_limit)
        command = [
            python, "-m", "vlm.scripts.extract_atomic_rules_safebooru",
            "--manifest", str(manifest),
            "--output-root", str(root / "atomic_rules"),
            "--limit", extraction_limit,
            "--workers", str(args.workers),
        ]
        if args.dry_run:
            command.append("--dry-run")
        run(command)
    if not args.skip_package:
        command = [
            python, "-m", "vlm.scripts.build_safebooru_trial_dataset",
            "--root", str(root),
            "--manifest", str(manifest),
            "--atomic-root", str(root / "atomic_rules"),
            "--package-root", str(root / "multi_view试标数据集_new"),
        ]
        if args.dry_run:
            command.append("--dry-run")
        run(command)


if __name__ == "__main__":
    main()
