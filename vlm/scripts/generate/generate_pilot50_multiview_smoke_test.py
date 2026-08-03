"""Smoke-test RunningHub multiview generation on the Safebooru pilot50 batch."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[3]))

from vlm.scripts.generate.runninghub_client import (
    load_api_env,
    poll_task,
    require_api_key,
    submit_task,
    upload_image,
)


DEFAULT_ROOT = Path("vlm/data/safebooru_2d/multi_view试标数据集_pilot50")
DEFAULT_PROMPT_DIR = Path("vlm/prompts/generation/runninghub")
DEFAULT_RUN_DIR = Path("vlm/tmp/pilot50_multiview_smoke_test")
DEFAULT_ENDPOINT = "https://www.runninghub.cn/openapi/v2/rhart-image-g-2/image-to-image"
DEFAULT_ASPECT_RATIO = "21:9"
DEFAULT_RESOLUTION = "1k"
DEFAULT_WORKERS = 2
PROMPT_FILES = {
    "backpack": "runninghub_g2_backpack_user_cn.txt",
    "cake_roll": "runninghub_g2_cake_roll_user_cn.txt",
    "dataset_figurine": "runninghub_g2_dataset_figurine_user_cn.txt",
    "dataset_QSitFigures": "runninghub_g2_dataset_QSitFigures_user_cn.txt",
    "head_key_chain": "runninghub_g2_head_keychain_user_cn.txt",
    "plush": "runninghub_g2_plush_user_cn.txt",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test multiview design generation on the pilot50 sample set.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--prompt-dir", type=Path, default=DEFAULT_PROMPT_DIR)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--aspect-ratio", default=DEFAULT_ASPECT_RATIO)
    parser.add_argument("--resolution", default=DEFAULT_RESOLUTION)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--poll-interval", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--keep-debug-files", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def iter_sample_dirs(root: Path) -> list[Path]:
    sample_dirs: list[Path] = []
    for category in sorted(PROMPT_FILES):
        category_dir = root / category
        if not category_dir.exists():
            continue
        for sample_dir in sorted(path for path in category_dir.iterdir() if path.is_dir()):
            sample_dirs.append(sample_dir)
    return sample_dirs


def find_first_existing(directory: Path, patterns: tuple[str, ...]) -> Path | None:
    for pattern in patterns:
        matches = sorted(directory.glob(pattern))
        if matches:
            return matches[0]
    return None


def find_source_image(sample_dir: Path, sample_id: str) -> Path:
    image = find_first_existing(sample_dir, ("2d_original.*", f"{sample_id}_original.*", "*_original.*"))
    if image is None:
        raise FileNotFoundError(f"No source image found in {sample_dir}")
    return image


def prompt_for_category(prompt_dir: Path, category: str) -> Path:
    file_name = PROMPT_FILES.get(category)
    if not file_name:
        raise KeyError(f"No RunningHub prompt registered for category: {category}")
    path = prompt_dir / file_name
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path


def save_png(src_path: Path, dst_path: Path) -> None:
    with Image.open(src_path) as image:
        image.save(dst_path, format="PNG")


def run_one(
    sample_dir: Path,
    prompt_dir: Path,
    api_key: str,
    *,
    endpoint: str,
    aspect_ratio: str,
    resolution: str,
    poll_interval: int,
    timeout: int,
    overwrite: bool,
    keep_debug_files: bool,
    run_dir: Path,
) -> dict[str, Any]:
    sample_id = sample_dir.name
    category = sample_dir.parent.name
    output_path = sample_dir / "multiview_design.png"
    if output_path.exists() and not overwrite:
        return {"status": "skipped", "sample_id": sample_id, "category": category, "reason": "output_exists"}

    source_image = find_source_image(sample_dir, sample_id)
    atomic_rules = sample_dir / "atomic_rules.json"
    prompt_path = prompt_for_category(prompt_dir, category)
    prompt = prompt_path.read_text(encoding="utf-8-sig").strip()
    if not atomic_rules.exists():
        raise FileNotFoundError(f"Missing atomic_rules.json for {sample_dir}")

    debug_dir = run_dir / category / sample_id
    if keep_debug_files:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        (debug_dir / "source_image.txt").write_text(str(source_image), encoding="utf-8")
        (debug_dir / "atomic_rules_path.txt").write_text(str(atomic_rules), encoding="utf-8")

    t0 = time.time()
    upload_payload = upload_image(api_key, source_image)
    submit_response = submit_task(
        api_key,
        prompt,
        [str(upload_payload["download_url"])],
        endpoint=endpoint,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
    )
    task_id = str(submit_response["taskId"])
    final_response = poll_task(api_key, task_id, poll_interval=poll_interval, timeout=timeout)
    results = final_response.get("results") or []
    if not results:
        return {
            "status": "no_results",
            "sample_id": sample_id,
            "category": category,
            "task_id": task_id,
            "elapsed_seconds": round(time.time() - t0, 2),
        }

    output_type = str(results[0].get("outputType") or "png").strip(".") or "png"
    raw_path = output_path.with_name(f"multiview_design_raw.{output_type.lower()}")
    tmp_path = output_path.with_suffix(output_path.suffix + ".part")
    if tmp_path.exists():
        tmp_path.unlink()
    from vlm.scripts.generate.runninghub_client import download_result

    download_result(results[0], raw_path)
    save_png(raw_path, tmp_path)
    tmp_path.replace(output_path)
    if raw_path.exists():
        raw_path.unlink()

    status = {
        "status": "succeeded",
        "sample_id": sample_id,
        "category": category,
        "task_id": task_id,
        "elapsed_seconds": round(time.time() - t0, 2),
        "output_path": str(output_path),
        "prompt_file": str(prompt_path),
        "source_image": str(source_image),
    }
    if keep_debug_files:
        (debug_dir / "upload_response.json").write_text(json.dumps(upload_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (debug_dir / "submit_response.json").write_text(json.dumps(submit_response, ensure_ascii=False, indent=2), encoding="utf-8")
        (debug_dir / "final_response.json").write_text(json.dumps(final_response, ensure_ascii=False, indent=2), encoding="utf-8")
        (debug_dir / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        status["debug_dir"] = str(debug_dir)
    return status


def main() -> None:
    args = parse_args()
    if args.workers < 1:
        raise ValueError("--workers must be at least 1")
    load_api_env()
    api_key = "" if args.dry_run else require_api_key()
    sample_dirs = iter_sample_dirs(args.root)
    if not sample_dirs:
        raise SystemExit(f"No sample folders found under {args.root}")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = args.run_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    print(json.dumps({
        "status": "smoke_test_started",
        "root": str(args.root),
        "sample_count": len(sample_dirs),
        "workers": args.workers,
        "run_dir": str(run_dir),
        "dry_run": args.dry_run,
    }, ensure_ascii=False), flush=True)

    summaries: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_sample = {
            executor.submit(
                run_one,
                sample_dir,
                args.prompt_dir,
                api_key,
                endpoint=args.endpoint,
                aspect_ratio=args.aspect_ratio,
                resolution=args.resolution,
                poll_interval=args.poll_interval,
                timeout=args.timeout,
                overwrite=args.overwrite,
                keep_debug_files=args.keep_debug_files,
                run_dir=run_dir,
            ): sample_dir
            for sample_dir in sample_dirs
        }
        for future in as_completed(future_to_sample):
            sample_dir = future_to_sample[future]
            try:
                status = future.result()
            except Exception as exc:
                status = {
                    "status": "failed",
                    "sample_id": sample_dir.name,
                    "category": sample_dir.parent.name,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            print(json.dumps(status, ensure_ascii=False), flush=True)
            summaries.append(status)

    summary = {
        "status": "smoke_test_finished",
        "sample_count": len(sample_dirs),
        "succeeded": sum(1 for item in summaries if item.get("status") == "succeeded"),
        "skipped": sum(1 for item in summaries if item.get("status") == "skipped"),
        "failed": sum(1 for item in summaries if item.get("status") == "failed"),
        "no_results": sum(1 for item in summaries if item.get("status") == "no_results"),
        "run_dir": str(run_dir),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
