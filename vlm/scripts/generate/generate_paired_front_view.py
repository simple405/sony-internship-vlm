"""Generate paired character images with a JSON-independent front-view prompt.

The paired JSON files are deliberately never parsed by this module.  They are
copied byte-for-byte into completed sample packages, while RunningHub receives
only the original image and frozen prompt.  Request metadata is stored outside
the three-file deliverable folders.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

from vlm.scripts._paths import API_ENV_FILE, GENERATION_PROMPTS_DIR, VLM_ROOT
from vlm.scripts.generate.runninghub_client import (
    DEFAULT_ENDPOINT,
    IMAGE_SUFFIXES,
    download_result,
    load_api_env,
    poll_task,
    require_api_key,
    submit_task,
    upload_image,
)
from vlm.scripts.generate.prompt_renderer import render_generation_prompt
from vlm.scripts._validation import resolve_manifest_path, validate_path_component


DEFAULT_INPUT_ROOT = VLM_ROOT / "data" / "1-动漫标注结果导出_paired_samples"
DEFAULT_OUTPUT_ROOT = VLM_ROOT / "data" / "front_view_generation_v1"
DEFAULT_PROMPT_FILE = GENERATION_PROMPTS_DIR / "merchandise_generation_cn.txt"


@dataclass(frozen=True)
class Sample:
    """Describe one paired source image and its untouched gold JSON."""

    sample_id: str
    image_path: Path
    image_ext: str
    image_bytes: int
    gold_path: Path | None = None


def read_manifest(input_root: Path) -> list[Sample]:
    """Resolve paired image/JSON paths without parsing the gold JSON content."""
    manifest = input_root / "manifest.csv"
    if not manifest.exists():
        raise FileNotFoundError(f"Manifest does not exist: {manifest}")
    samples: list[Sample] = []
    seen: set[str] = set()
    with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        for row_number, row in enumerate(csv.DictReader(handle), start=2):
            sample_id = str(row.get("sample_id") or "").strip()
            image_file = str(row.get("image_file") or "").strip()
            json_file = str(row.get("json_file") or "").strip()
            if not sample_id or not image_file or not json_file:
                raise ValueError(f"Manifest row {row_number} is missing a required field")
            validate_path_component(sample_id, "sample ID")
            if sample_id in seen:
                raise ValueError(f"Duplicate sample ID in manifest: {sample_id}")
            seen.add(sample_id)
            image_path = resolve_manifest_path(input_root, image_file, "image_file")
            gold_path = resolve_manifest_path(input_root, json_file, "json_file")
            if image_path.suffix.lower() not in IMAGE_SUFFIXES:
                raise ValueError(f"Unsupported image suffix in manifest: {image_path}")
            if gold_path.suffix.lower() != ".json":
                raise ValueError(f"Gold path is not JSON: {gold_path}")
            if not image_path.is_file():
                raise FileNotFoundError(image_path)
            if not gold_path.is_file():
                raise FileNotFoundError(gold_path)
            samples.append(
                Sample(
                    sample_id=sample_id,
                    image_path=image_path,
                    image_ext=image_path.suffix.lower(),
                    image_bytes=image_path.stat().st_size,
                    gold_path=gold_path,
                )
            )
    return sorted(samples, key=lambda item: item.sample_id)


def _stratum(sample: Sample) -> tuple[str, str, str]:
    """Return deterministic visual-only buckets for pilot coverage."""
    try:
        with Image.open(sample.image_path) as image:
            width, height = image.size
    except Exception:
        width, height = 1, 1
    ratio = width / max(height, 1)
    orientation = "portrait" if ratio < 0.85 else "landscape" if ratio > 1.2 else "square"
    size = "small" if sample.image_bytes < 100_000 else "medium" if sample.image_bytes < 500_000 else "large"
    return sample.image_ext, orientation, size


def select_samples(samples: Iterable[Sample], requested_ids: list[str], limit: int) -> list[Sample]:
    """Select explicit IDs or a deterministic round-robin visual stratified pilot."""
    by_id = {sample.sample_id: sample for sample in samples}
    if requested_ids:
        missing = [sample_id for sample_id in requested_ids if sample_id not in by_id]
        if missing:
            raise ValueError(f"Unknown sample_id(s): {', '.join(missing)}")
        selected = [by_id[sample_id] for sample_id in dict.fromkeys(requested_ids)]
        return selected[:limit] if limit > 0 else selected
    ordered = sorted(by_id.values(), key=lambda sample: (str(_stratum(sample)), sample.sample_id))
    buckets: dict[tuple[str, str, str], list[Sample]] = {}
    for sample in ordered:
        buckets.setdefault(_stratum(sample), []).append(sample)
    bucket_keys = sorted(buckets)
    selected: list[Sample] = []
    while bucket_keys and (limit <= 0 or len(selected) < limit):
        next_keys: list[tuple[str, str, str]] = []
        for key in bucket_keys:
            if buckets[key] and (limit <= 0 or len(selected) < limit):
                selected.append(buckets[key].pop(0))
            if buckets[key]:
                next_keys.append(key)
        bucket_keys = next_keys
    return selected


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def _copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".part")
    shutil.copy2(source, temp_path)
    temp_path.replace(destination)


def _migrate_legacy_metadata(sample_dir: Path, metadata_dir: Path) -> None:
    """Move metadata created by the first pilot layout out of deliverable folders."""
    for name in ("prompt.txt", "request_preview.json", "status.json"):
        legacy_path = sample_dir / name
        if not legacy_path.exists():
            continue
        metadata_dir.mkdir(parents=True, exist_ok=True)
        destination = metadata_dir / name
        if destination.exists():
            legacy_path.unlink()
        else:
            legacy_path.replace(destination)


def _package_inputs(sample: Sample, sample_dir: Path) -> tuple[Path, Path]:
    if sample.gold_path is None or not sample.gold_path.is_file():
        raise FileNotFoundError(f"Gold JSON does not exist for {sample.sample_id}")
    original_path = sample_dir / f"{sample.sample_id}_original{sample.image_ext}"
    gold_path = sample_dir / f"{sample.sample_id}.json"
    _copy_atomic(sample.image_path, original_path)
    _copy_atomic(sample.gold_path, gold_path)
    return original_path, gold_path


def _success_image(output_dir: Path, sample_id: str) -> Path | None:
    for suffix in IMAGE_SUFFIXES:
        path = output_dir / f"{sample_id}_q_front_view{suffix}"
        if path.exists() and path.stat().st_size > 0:
            try:
                with Image.open(path) as image:
                    image.verify()
                return path
            except Exception:
                continue
    return None


def _request_preview(sample: Sample, prompt_file: Path, prompt: str, output_dir: Path) -> dict[str, Any]:
    return {
        "schema_version": "runninghub_front_view_request.v1",
        "sample_id": sample.sample_id,
        "source_image_sha256": _sha256(sample.image_path),
        "prompt_file": str(prompt_file),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "endpoint": DEFAULT_ENDPOINT,
        "request": {
            "prompt": prompt,
            "sourceImages": [str(sample.image_path)],
            "image_count": 1,
            "aspectRatio": "21:9",
            "resolution": "1k",
        },
        "output_dir": str(output_dir),
    }


def process_one(
    sample: Sample,
    output_root: Path,
    prompt_file: Path,
    prompt: str,
    *,
    dry_run: bool,
    api_key: str = "",
    poll_interval: int = 6,
    timeout: int = 900,
) -> dict[str, Any]:
    """Generate or resume one paired front-view sample."""
    sample_dir = output_root / sample.sample_id
    metadata_dir = output_root / "_metadata" / sample.sample_id
    _migrate_legacy_metadata(sample_dir, metadata_dir)
    existing = _success_image(sample_dir, sample.sample_id)
    if existing:
        snapshot_path = metadata_dir / "prompt.txt"
        if snapshot_path.exists() and snapshot_path.read_text(encoding="utf-8") != prompt:
            raise RuntimeError(
                f"Existing output uses a different prompt: {sample_dir}. Use a new output root."
            )
        original_path, gold_path = _package_inputs(sample, sample_dir)
        return {
            "schema_version": "front_view_generation_status.v1",
            "sample_id": sample.sample_id,
            "status": "skipped",
            "reason": "success_exists",
            "output": str(existing),
            "original": str(original_path),
            "gold": str(gold_path),
        }
    metadata_dir.mkdir(parents=True, exist_ok=True)
    (metadata_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    preview = _request_preview(sample, prompt_file, prompt, sample_dir)
    _write_json(metadata_dir / "request_preview.json", preview)
    if dry_run:
        status = {"schema_version": "front_view_generation_status.v1", "sample_id": sample.sample_id, "status": "dry_run", "source_image": str(sample.image_path)}
        _write_json(metadata_dir / "status.json", status)
        return status
    started = time.time()
    upload = upload_image(api_key, sample.image_path)
    submitted = submit_task(api_key, prompt, [str(upload["download_url"])], aspect_ratio="21:9", resolution="1k")
    task_id = str(submitted["taskId"])
    final = poll_task(api_key, task_id, poll_interval=poll_interval, timeout=timeout)
    results = final.get("results") or []
    if not results:
        raise RuntimeError("RunningHub task succeeded without results")
    ext = str(results[0].get("outputType") or "png").strip(".").lower() or "png"
    if f".{ext}" not in IMAGE_SUFFIXES:
        ext = "png"
    output_path = sample_dir / f"{sample.sample_id}_q_front_view.{ext}"
    download_result(results[0], output_path)
    with Image.open(output_path) as image:
        size = list(image.size)
    original_path, gold_path = _package_inputs(sample, sample_dir)
    status = {"schema_version": "front_view_generation_status.v1", "sample_id": sample.sample_id, "status": "succeeded", "task_id": task_id, "output": str(output_path), "original": str(original_path), "gold": str(gold_path), "size": size, "elapsed_seconds": round(time.time() - started, 2)}
    _write_json(metadata_dir / "status.json", status)
    return status


def parse_args() -> argparse.Namespace:
    """Parse paired front-view generation arguments."""
    parser = argparse.ArgumentParser(description="Generate paired front-view images without reading paired JSON.")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--prompt-file", type=Path, default=DEFAULT_PROMPT_FILE)
    parser.add_argument("--sample-id", action="append", default=[])
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--poll-interval", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=900)
    return parser.parse_args()


def main() -> None:
    """Run the paired front-view generation batch."""
    args = parse_args()
    if args.limit < 0:
        raise SystemExit("--limit must be >= 0")
    if args.workers < 1 or args.workers > 3:
        raise SystemExit("--workers must be between 1 and 3")
    if not args.dry_run:
        load_api_env(API_ENV_FILE)
        api_key = require_api_key()
    else:
        api_key = ""
    prompt_template = args.prompt_file.read_text(encoding="utf-8-sig").strip()
    if not prompt_template:
        raise SystemExit(f"Prompt file is empty: {args.prompt_file}")
    prompt = render_generation_prompt(
        prompt_template,
        category="dataset_figurine",
        view_mode="front",
    )
    samples = select_samples(read_manifest(args.input_root), args.sample_id, args.limit)
    if not samples:
        raise SystemExit("No samples selected")
    args.output_root.mkdir(parents=True, exist_ok=True)
    summary: list[dict[str, Any]] = []
    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_sample = {
            executor.submit(
                process_one,
                sample,
                args.output_root,
                args.prompt_file,
                prompt,
                dry_run=args.dry_run,
                api_key=api_key,
                poll_interval=args.poll_interval,
                timeout=args.timeout,
            ): sample
            for sample in samples
        }
        for future in as_completed(future_to_sample):
            sample = future_to_sample[future]
            try:
                status = future.result()
            except Exception as exc:
                status = {
                    "schema_version": "front_view_generation_status.v1",
                    "sample_id": sample.sample_id,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                _write_json(args.output_root / "_metadata" / sample.sample_id / "status.json", status)
                failed.append(sample.sample_id)
            summary.append(status)
            print(json.dumps(status, ensure_ascii=False), flush=True)
    selected_order = {sample.sample_id: index for index, sample in enumerate(samples)}
    summary.sort(key=lambda item: selected_order[str(item["sample_id"])])
    _write_json(args.output_root / "batch_summary.json", {"schema_version": "front_view_generation_batch.v1", "dry_run": args.dry_run, "selected": [sample.sample_id for sample in samples], "results": summary})
    _write_json(args.output_root / "failed_queue.json", {"schema_version": "front_view_generation_failed_queue.v1", "sample_ids": failed})
    print(json.dumps({"status": "finished", "selected": len(samples), "dry_run": args.dry_run, "failed": len(failed), "output_root": str(args.output_root)}, ensure_ascii=False), flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
