"""Run the four RunningHub merchandise categories in a safe fixed order."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_DATASET = Path("vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20")
DEFAULT_ASSIGNMENT_DIR = DEFAULT_DATASET / "reports" / "merchandise_category_assignment"
DEFAULT_RUN_DIR = Path("vlm/tmp/runninghub_full_generation")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")

CATEGORY_CONFIGS = {
    "head_key_chain": {
        "prompt_file": Path("vlm/prompts/generation/runninghub/runninghub_g2_head_keychain_user_cn.txt"),
        "output_suffix": "head_keychain",
        "output_subdir": Path("runninghub/head_key_chain"),
    },
    "backpack": {
        "prompt_file": Path("vlm/prompts/generation/runninghub/runninghub_g2_backpack_user_cn.txt"),
        "output_suffix": "backpack",
        "output_subdir": Path("runninghub/backpack"),
    },
    "cake_roll": {
        "prompt_file": Path("vlm/prompts/generation/runninghub/runninghub_g2_cake_roll_user_cn.txt"),
        "output_suffix": "cake_roll",
        "output_subdir": Path("runninghub/cake_roll"),
    },
    "plush": {
        "prompt_file": Path("vlm/prompts/generation/runninghub/runninghub_g2_plush_user_cn.txt"),
        "output_suffix": "plush",
        "output_subdir": Path("runninghub/plush"),
    },
}

DEFAULT_ORDER = ("head_key_chain", "backpack", "cake_roll", "plush")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RunningHub G-2.0 merchandise batches sequentially.")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--assignment-dir", type=Path, default=DEFAULT_ASSIGNMENT_DIR)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument(
        "--category",
        action="append",
        choices=DEFAULT_ORDER,
        help="Category to run. Repeatable. Default order: head_key_chain, backpack, cake_roll, plush.",
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--poll-interval", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--resolution", default="1k", choices=("1k", "2k", "4k"))
    parser.add_argument("--aspect-ratio", default="21:9")
    parser.add_argument("--max-samples-per-category", type=int, default=0)
    parser.add_argument("--refresh-assignment", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def read_sample_ids(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Sample list does not exist: {path}")
    return [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def has_existing_output(output_dir: Path, sample_id: str, output_suffix: str) -> bool:
    sample_dir = output_dir / sample_id
    if not sample_dir.exists():
        return False
    for suffix in IMAGE_SUFFIXES:
        if (sample_dir / f"{sample_id}_{output_suffix}{suffix}").exists():
            return True
    return False


def run_and_log(command: list[str], log_path: Path) -> tuple[int, dict[str, Any] | None]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    final_summary: dict[str, Any] | None = None
    with log_path.open("w", encoding="utf-8", newline="") as log:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            log.write(line)
            stripped = line.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if payload.get("status") == "finished":
                    final_summary = payload
        return process.wait(), final_summary


def run_refresh_assignment(args: argparse.Namespace) -> None:
    command = [
        sys.executable,
        str(Path("vlm/scripts/data/assign_merchandise_categories.py")),
        "--dataset-dir",
        str(args.dataset_dir),
        "--output-dir",
        str(args.assignment_dir),
    ]
    print(json.dumps({"status": "refresh_assignment_started", "command": command}, ensure_ascii=False), flush=True)
    subprocess.run(command, check=True)


def category_command(
    args: argparse.Namespace,
    category: str,
    sample_ids: list[str],
) -> list[str]:
    config = CATEGORY_CONFIGS[category]
    output_dir = args.dataset_dir / "generated_3d_no_rules" / Path(config["output_subdir"])
    command = [
        sys.executable,
        str(Path("vlm/scripts/generate/generate_head_keychain_with_runninghub_g2.py")),
    ]
    for sample_id in sample_ids:
        command.extend(["--sample-id", sample_id])
    command.extend(
        [
            "--source-dir",
            str(args.dataset_dir / "image"),
            "--atomic-dir",
            str(args.dataset_dir / "atomic_rules"),
            "--direct-output-dir",
            str(output_dir),
            "--prompt-file",
            str(config["prompt_file"]),
            "--output-suffix",
            str(config["output_suffix"]),
            "--aspect-ratio",
            args.aspect_ratio,
            "--resolution",
            args.resolution,
            "--poll-interval",
            str(args.poll_interval),
            "--timeout",
            str(args.timeout),
            "--workers",
            str(args.workers),
            "--keep-debug-files",
        ]
    )
    if args.dry_run:
        command.append("--dry-run")
    return command


def main() -> None:
    args = parse_args()
    if args.workers < 1:
        raise ValueError("--workers must be at least 1")
    if not args.dry_run and not os.environ.get("RUNNINGHUB_API_KEY", "").strip():
        raise SystemExit("RUNNINGHUB_API_KEY is not set in this process.")

    if args.refresh_assignment:
        run_refresh_assignment(args)

    categories = tuple(args.category or DEFAULT_ORDER)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = args.run_dir / run_id
    log_dir.mkdir(parents=True, exist_ok=True)

    overall: list[dict[str, Any]] = []
    print(
        json.dumps(
            {
                "status": "runninghub_full_batch_started",
                "categories": categories,
                "workers_per_category": args.workers,
                "category_parallelism": 1,
                "log_dir": str(log_dir),
                "dry_run": args.dry_run,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    for category in categories:
        config = CATEGORY_CONFIGS[category]
        all_ids = read_sample_ids(args.assignment_dir / "sample_lists" / f"{category}.txt")
        output_dir = args.dataset_dir / "generated_3d_no_rules" / Path(config["output_subdir"])
        pending_ids = [
            sample_id
            for sample_id in all_ids
            if not has_existing_output(output_dir, sample_id, str(config["output_suffix"]))
        ]
        skipped = len(all_ids) - len(pending_ids)
        if args.max_samples_per_category > 0:
            pending_ids = pending_ids[: args.max_samples_per_category]

        start_payload = {
            "status": "category_started",
            "category": category,
            "listed_samples": len(all_ids),
            "skipped_existing_outputs": skipped,
            "selected_samples": len(pending_ids),
        }
        print(json.dumps(start_payload, ensure_ascii=False), flush=True)
        if not pending_ids:
            overall.append({**start_payload, "status": "category_skipped"})
            continue

        log_path = log_dir / f"{category}.log"
        command = category_command(args, category, pending_ids)
        if args.dry_run:
            print(json.dumps({"status": "category_command", "category": category, "command": command}, ensure_ascii=False))
            overall.append(
                {
                    "status": "category_dry_run",
                    "category": category,
                    "selected_samples": len(pending_ids),
                    "log_path": str(log_path),
                    "command": command,
                }
            )
            continue
        return_code, child_summary = run_and_log(command, log_path)
        result = {
            "status": "category_finished",
            "category": category,
            "return_code": return_code,
            "log_path": str(log_path),
            "child_summary": child_summary or {},
        }
        print(json.dumps(result, ensure_ascii=False), flush=True)
        overall.append(result)
        if return_code != 0:
            raise SystemExit(f"Category {category} failed with return code {return_code}. See {log_path}")

    summary_path = log_dir / "summary.json"
    summary_path.write_text(json.dumps(overall, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "runninghub_full_batch_finished", "summary_path": str(summary_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
