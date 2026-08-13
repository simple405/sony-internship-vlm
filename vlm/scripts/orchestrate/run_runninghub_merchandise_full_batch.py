"""Run the six RunningHub merchandise categories in a safe fixed order."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[3]))

from vlm.scripts._sn7_artifacts import (
    CATEGORIES,
    CATEGORY_OUTPUT_SUFFIXES,
    find_generated_output,
)
from vlm.scripts.generate.runninghub_client import load_api_env
from vlm.scripts._validation import validate_path_component


DEFAULT_DATASET = Path("vlm/data/sn7_data_generation")
DEFAULT_ASSIGNMENT_DIR = DEFAULT_DATASET / "reports" / "merchandise_category_assignment"
DEFAULT_RUN_DIR = Path("vlm/tmp/sn7_runninghub_full_generation")
DEFAULT_PROMPT_FILE = Path("vlm/prompts/generation/runninghub/merchandise_generation_cn.txt")
CATEGORY_CONFIGS = {
    category: {"output_suffix": suffix, "output_subdir": Path(category)}
    for category, suffix in CATEGORY_OUTPUT_SUFFIXES.items()
}

# Note 3: The order is intentionally sequential and stable. Running one category
# at a time keeps logs readable and reduces accidental duplicate API pressure.
DEFAULT_ORDER = CATEGORIES


def parse_args() -> argparse.Namespace:
    """Parse SN-7 RunningHub orchestration arguments."""
    # Note 4: These arguments describe orchestration policy, while the child
    # generator still owns sample-level upload, polling, and download behavior.
    parser = argparse.ArgumentParser(description="Run RunningHub G-2.0 merchandise batches sequentially.")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--assignment-dir", type=Path, default=DEFAULT_ASSIGNMENT_DIR)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument(
        "--category",
        action="append",
        choices=DEFAULT_ORDER,
        # Note 5: Repeating --category lets a maintainer retry one or two queues
        # without editing code or changing the default full order.
        help="Category to run. Repeatable. Default order covers all six merchandise categories.",
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--poll-interval", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--resolution", default="1k", choices=("1k", "2k", "4k"))
    parser.add_argument("--aspect-ratio", default="21:9")
    parser.add_argument("--max-samples-per-category", type=int, default=0)
    parser.add_argument(
        "--follow-atomic-rules",
        action="store_true",
        help="Keep polling for newly extracted atomic rules and submit them as they appear.",
    )
    parser.add_argument(
        "--atomic-poll-interval",
        type=int,
        default=30,
        help="Seconds to wait before rescanning for atomic rules in --follow-atomic-rules mode.",
    )
    parser.add_argument("--refresh-assignment", action="store_true")
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Resubmit samples that already have generation_error.json.",
    )
    parser.add_argument(
        "--skip-xlsx",
        action="store_true",
        help="Generate images without creating per-sample annotation workbooks.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def read_sample_ids(path: Path) -> list[str]:
    """Read, validate, and deduplicate a category sample list."""
    # Note 6: Sample lists are plain text so they can be inspected and edited by
    # hand. Blank lines are ignored to make manual edits forgiving.
    if not path.exists():
        raise FileNotFoundError(f"Sample list does not exist: {path}")
    sample_ids = [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    for sample_id in sample_ids:
        validate_path_component(sample_id, "sample ID")
    return list(dict.fromkeys(sample_ids))


def has_existing_output(output_dir: Path, sample_id: str, output_suffix: str) -> bool:
    """Return whether a valid generated output already exists for this sample."""
    # Note 7: This is the resume guard. A sample is skipped only when the expected
    # generated image file already exists in its output directory.
    return find_generated_output(output_dir / sample_id, sample_id, output_suffix) is not None


def has_atomic_rules(atomic_dir: Path, sample_id: str) -> bool:
    """Return whether a sample has usable atomic rules.

    A terminal ``error.json`` wins over stale rule files. This matters after an
    ``--overwrite`` extraction run: a rejected sample may still have an older
    ``atomic_rules.json`` from a previous prompt, and submitting that stale file
    would silently bypass the extraction failure.
    """
    sample_dir = atomic_dir / sample_id
    if has_atomic_error(atomic_dir, sample_id):
        return False
    return (
        (sample_dir / "atomic_rules.json").exists()
        or (sample_dir / f"{sample_id}_atomic_rules.json").exists()
    )


def has_atomic_error(atomic_dir: Path, sample_id: str) -> bool:
    """Return whether Qwen recorded a terminal extraction error for this sample."""
    return (atomic_dir / sample_id / "error.json").exists()


def has_generation_error(output_dir: Path, sample_id: str) -> bool:
    """Return whether RunningHub recorded a terminal generation error."""
    return (output_dir / sample_id / "generation_error.json").is_file()


def categorize_sample_ids(
    sample_ids: list[str],
    output_dir: Path,
    output_suffix: str,
    atomic_dir: Path,
    attempted_ids: set[str],
    *,
    retry_failed: bool = False,
) -> dict[str, list[str]]:
    """Partition a category queue without resubmitting completed or failed work."""
    states = {
        "existing": [],
        "attempted": [],
        "generation_errors": [],
        "ready": [],
        "atomic_errors": [],
        "waiting": [],
    }
    for sample_id in sample_ids:
        if has_existing_output(output_dir, sample_id, output_suffix):
            states["existing"].append(sample_id)
        elif sample_id in attempted_ids:
            states["attempted"].append(sample_id)
        elif has_atomic_error(atomic_dir, sample_id):
            states["atomic_errors"].append(sample_id)
        elif has_generation_error(output_dir, sample_id) and not retry_failed:
            states["generation_errors"].append(sample_id)
        elif has_atomic_rules(atomic_dir, sample_id):
            states["ready"].append(sample_id)
        else:
            states["waiting"].append(sample_id)
    return states


def run_and_log(command: list[str], log_path: Path) -> tuple[int, dict[str, Any] | None]:
    """Run a child batch while mirroring output to a log file."""
    # Note 8: The child process streams JSON status lines. This wrapper mirrors
    # them to the console, saves a full log, and captures the final summary.
    log_path.parent.mkdir(parents=True, exist_ok=True)
    final_summary: dict[str, Any] | None = None
    with log_path.open("w", encoding="utf-8", newline="") as log:
        process = subprocess.Popen(
            # Note 9: stderr is merged into stdout so each category has one
            # chronological log file, which makes failure analysis much easier.
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
            # Note 10: Streaming each line immediately helps long-running remote
            # tasks show progress instead of appearing frozen.
            print(line, end="")
            log.write(line)
            stripped = line.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                # Note 11: Not every line must be JSON; parse opportunistically
                # and ignore plain text or partially written diagnostics.
                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if payload.get("status") == "finished":
                    final_summary = payload
        return process.wait(), final_summary


def is_nonfatal_sample_failure(return_code: int, child_summary: dict[str, Any] | None) -> bool:
    """Return whether a child failure is limited to completed sample-level failures."""
    # Note 12a: The lower-level generator intentionally exits 1 when any sample is
    # rejected by RunningHub or returns no image. That should not stop later
    # categories; only a missing/incomplete child summary means the category
    # process itself crashed and the orchestrator must fail fast.
    if return_code == 0 or not child_summary:
        return False
    if child_summary.get("status") != "finished":
        return False
    return bool(child_summary.get("failed", 0) or child_summary.get("no_image_url_found", 0))


def run_refresh_assignment(args: argparse.Namespace) -> None:
    """Regenerate category assignments before orchestration."""
    # Note 12: Assignment refresh is optional because it rewrites queue files.
    # Use it only when the manifest or scoring rules intentionally changed.
    command = [
        sys.executable,
        str(Path("vlm/scripts/data/assign_merchandise_categories.py")),
        "--dataset-dir",
        str(args.dataset_dir),
        "--output-dir",
        str(args.assignment_dir),
    ]
    print(json.dumps({"status": "refresh_assignment_started", "command": command}, ensure_ascii=False), flush=True)
    # Note 13: check=True is correct here because stale assignment data should
    # stop the batch before any generation work begins.
    subprocess.run(command, check=True)


def category_command(
    args: argparse.Namespace,
    category: str,
    sample_ids: list[str],
) -> list[str]:
    """Build the generator command for one category and sample batch."""
    # Note 14: Build the child command as a list rather than a string. This avoids
    # shell quoting bugs on Windows paths and keeps arguments exact.
    config = CATEGORY_CONFIGS[category]
    output_dir = args.dataset_dir / "generated" / Path(config["output_subdir"])
    command = [
        sys.executable,
        "-m",
        "vlm.scripts.generate.generate_sn7_multiview",
    ]
    for sample_id in sample_ids:
        # Note 15: The lower-level script accepts repeated --sample-id flags, so
        # the orchestrator does not need to create temporary sample-list files.
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
            str(DEFAULT_PROMPT_FILE),
            "--output-suffix",
            str(config["output_suffix"]),
            "--category",
            category,
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
        # Note 16: Dry-run is forwarded to the child generator so the complete
        # command path can be validated without requiring RunningHub credits.
        command.append("--dry-run")
    if getattr(args, "skip_xlsx", False):
        command.append("--skip-xlsx")
    return command


def main() -> None:
    """Run requested merchandise categories sequentially."""
    # Note 17: In follow mode, Qwen produces local rule files while this process
    # consumes each completed file exactly once for RunningHub generation.
    args = parse_args()
    if args.workers < 1:
        raise ValueError("--workers must be at least 1")
    if args.atomic_poll_interval < 1:
        raise ValueError("--atomic-poll-interval must be at least 1")
    load_api_env()
    if not args.dry_run and not os.environ.get("RUNNINGHUB_API_KEY", "").strip():
        # Note 18: Fail before creating per-category logs if the API key is
        # missing; otherwise a long batch would fail sample by sample.
        raise SystemExit("RUNNINGHUB_API_KEY is not set in this process.")

    if args.refresh_assignment:
        # Note 19: Refresh happens before choosing categories so every requested
        # category sees queue files from the same assignment run.
        run_refresh_assignment(args)

    categories = tuple(args.category or DEFAULT_ORDER)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Note 20: A timestamped run directory keeps retry logs separate and prevents
    # newer batches from overwriting earlier evidence.
    log_dir = args.run_dir / run_id
    log_dir.mkdir(parents=True, exist_ok=True)

    overall: list[dict[str, Any]] = []
    attempted_ids = {category: set() for category in categories}
    saw_nonfatal_sample_failures = False
    print(
        # Note 21: The first line records batch-level configuration in a
        # machine-readable form for later handoff notes or debugging.
        json.dumps(
            {
                "status": "runninghub_full_batch_started",
                "categories": categories,
                "workers_per_category": args.workers,
                "category_parallelism": 1,
                "follow_atomic_rules": args.follow_atomic_rules,
                "atomic_poll_interval": args.atomic_poll_interval if args.follow_atomic_rules else None,
                "skip_xlsx": bool(getattr(args, "skip_xlsx", False)),
                "log_dir": str(log_dir),
                "dry_run": args.dry_run,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    round_number = 0
    while True:
        round_number += 1
        waiting_for_atomic = 0
        for category in categories:
            # Note 22: Categories remain sequential to preserve the established
            # request rate, while each child still uses per-sample workers.
            config = CATEGORY_CONFIGS[category]
            all_ids = read_sample_ids(args.assignment_dir / "sample_lists" / f"{category}.txt")
            output_dir = args.dataset_dir / "generated" / Path(config["output_subdir"])
            states = categorize_sample_ids(
                all_ids,
                output_dir,
                str(config["output_suffix"]),
                args.dataset_dir / "atomic_rules",
                attempted_ids[category],
                retry_failed=args.retry_failed,
            )
            pending_ids = states["ready"]
            if args.max_samples_per_category > 0:
                remaining_capacity = max(0, args.max_samples_per_category - len(attempted_ids[category]))
                pending_ids = pending_ids[:remaining_capacity]
            waiting_for_atomic += len(states["waiting"]) if (
                args.max_samples_per_category == 0
                or len(attempted_ids[category]) < args.max_samples_per_category
            ) else 0

            start_payload = {
                "status": "category_started",
                "round": round_number,
                "category": category,
                "listed_samples": len(all_ids),
                "existing_outputs": len(states["existing"]),
                "already_attempted_this_run": len(states["attempted"]),
                "skipped_missing_atomic_rules": len(states["waiting"]),
                "skipped_generation_errors": len(states["generation_errors"]),
                "skipped_atomic_rule_errors": len(states["atomic_errors"]),
                "selected_samples": len(pending_ids),
            }
            print(json.dumps(start_payload, ensure_ascii=False), flush=True)
            if not pending_ids:
                overall.append({**start_payload, "status": "category_skipped"})
                continue

            attempted_ids[category].update(pending_ids)
            log_name = f"{round_number:04d}_{category}.log" if args.follow_atomic_rules else f"{category}.log"
            log_path = log_dir / log_name
            command = category_command(args, category, pending_ids)
            if args.dry_run:
                print(json.dumps({"status": "category_command", "category": category, "command": command}, ensure_ascii=False))
                overall.append(
                    {
                        "status": "category_dry_run",
                        "round": round_number,
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
                "round": round_number,
                "category": category,
                "return_code": return_code,
                "log_path": str(log_path),
                "child_summary": child_summary or {},
            }
            nonfatal_sample_failure = is_nonfatal_sample_failure(return_code, child_summary)
            if nonfatal_sample_failure:
                # Note 22a: RunningHub rejections are recorded per sample. Keep
                # moving so one policy/size failure does not strand every later
                # category in a long SN-7 run.
                result["status"] = "category_finished_with_sample_failures"
                result["sample_failure_nonfatal"] = True
                saw_nonfatal_sample_failures = True
            print(json.dumps(result, ensure_ascii=False), flush=True)
            overall.append(result)
            if return_code != 0 and not nonfatal_sample_failure:
                raise SystemExit(f"Category {category} failed with return code {return_code}. See {log_path}")

        if not args.follow_atomic_rules or args.dry_run or waiting_for_atomic == 0:
            break
        print(
            json.dumps(
                {
                    "status": "waiting_for_atomic_rules",
                    "round": round_number,
                    "samples": waiting_for_atomic,
                    "poll_interval_seconds": args.atomic_poll_interval,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        time.sleep(args.atomic_poll_interval)

    summary_path = log_dir / "summary.json"
    # Note 29: The summary file is compact compared with full logs and is usually
    # the first artifact to inspect after a long run.
    summary_path.write_text(json.dumps(overall, ensure_ascii=False, indent=2), encoding="utf-8")
    final_status = (
        "runninghub_full_batch_finished_with_sample_failures"
        if saw_nonfatal_sample_failures
        else "runninghub_full_batch_finished"
    )
    print(json.dumps({"status": final_status, "summary_path": str(summary_path)}, ensure_ascii=False))
    if saw_nonfatal_sample_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
