"""Generate paired character images with a front-view merchandise prompt.

By default the paired JSON files are deliberately never parsed by this module.
They are copied byte-for-byte into completed sample packages, while RunningHub
receives only the original image and frozen prompt.  The optional
``--include-silver-json`` smoke-test mode appends vendor silver-label elements
to the prompt for the SN-6 silver auto-supervision workflow.
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
from vlm.scripts.generate.prompt_renderer import (
    CATEGORY_REQUIREMENTS,
    render_generation_prompt,
)
from vlm.scripts._validation import resolve_manifest_path, validate_path_component


DEFAULT_INPUT_ROOT = VLM_ROOT / "data" / "1-动漫标注结果导出_paired_samples"
DEFAULT_OUTPUT_ROOT = VLM_ROOT / "data" / "front_view_generation_v1"
DEFAULT_PROMPT_FILE = GENERATION_PROMPTS_DIR / "merchandise_generation_cn.txt"
DEFAULT_FIVE_CATEGORY_METADATA_ROOT = (
    VLM_ROOT / "tmp" / "five_category_supervision_v1" / "generation"
)
CATEGORY_OUTPUT_SUFFIXES = {
    "head_key_chain": "head_keychain",
    "cake_roll": "cake_roll",
    "backpack": "backpack",
    "plush": "plush",
    "dataset_QSitFigures": "SitFigures",
    "dataset_figurine": "figurine",
}
LEGACY_OUTPUT_SUFFIX = "q"



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


def _success_image(
    output_dir: Path,
    sample_id: str,
    output_suffix: str = LEGACY_OUTPUT_SUFFIX,
) -> Path | None:
    """Return an existing valid generated front-view image, if present."""
    prefixes = [output_suffix]
    if output_suffix != LEGACY_OUTPUT_SUFFIX:
        prefixes.append(LEGACY_OUTPUT_SUFFIX)
    for prefix in prefixes:
        for suffix in IMAGE_SUFFIXES:
            path = output_dir / f"{sample_id}_{prefix}_front_view{suffix}"
            if path.exists() and path.stat().st_size > 0:
                try:
                    with Image.open(path) as image:
                        image.verify()
                    return path
                except Exception:
                    continue
    return None


def _request_preview(
    sample: Sample,
    prompt_file: Path,
    prompt: str,
    output_dir: Path,
    *,
    category: str,
    output_suffix: str,
) -> dict[str, Any]:
    return {
        "schema_version": "runninghub_front_view_request.v1",
        "sample_id": sample.sample_id,
        "category": category,
        "output_suffix": output_suffix,
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


def _clip_text(value: str, limit: int) -> str:
    """Return a single-line text snippet capped for prompt safety."""
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(limit - 1, 0)].rstrip() + "…"


def render_silver_label_constraints(
    sample: Sample,
    *,
    max_elements: int = 12,
    description_limit: int = 96,
) -> str:
    """Render vendor paired JSON as a compact silver-label preservation list."""
    if sample.gold_path is None or not sample.gold_path.is_file():
        raise FileNotFoundError(f"Gold JSON does not exist for {sample.sample_id}")
    try:
        payload = json.loads(sample.gold_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid paired JSON for {sample.sample_id}: {sample.gold_path}") from exc
    if not isinstance(payload, list):
        raise ValueError(f"Paired JSON must be a list for {sample.sample_id}: {sample.gold_path}")
    lines = [
        "",
        "【乙方 SN6 silver label 约束】",
        "以下元素来自乙方标注，只作为身份保留清单；若文字与输入图直接可见内容冲突，以输入图为准。不要把 bbox 数字、文字标签或标注框画进结果。",
    ]
    for index, item in enumerate(payload[:max_elements], start=1):
        if not isinstance(item, dict):
            continue
        element = _clip_text(str(item.get("element") or item.get("name") or "").strip(), 80)
        description = _clip_text(str(item.get("description") or "").strip(), description_limit)
        bbox = item.get("bbox")
        bbox_text = ""
        if isinstance(bbox, list) and len(bbox) == 4:
            bbox_text = f"；原图区域 bbox={bbox}"
        if element and description:
            lines.append(f"{index}. {element}：{description}{bbox_text}")
        elif element:
            lines.append(f"{index}. {element}{bbox_text}")
    if len(payload) > max_elements:
        lines.append(f"另有 {len(payload) - max_elements} 个低优先级元素未展开，整体配色和服装结构仍需参考输入图。")
    lines.append("请优先保留头发、眼睛、头饰、服装主色块、身份配件和显著图案；不可新增未出现的核心身份元素。")
    return "\n".join(lines)


def build_sample_prompt(
    base_prompt: str,
    sample: Sample,
    *,
    include_silver_json: bool,
    silver_elements_limit: int = 12,
) -> str:
    """Return the final per-sample prompt, optionally enriched with silver labels."""
    if not include_silver_json:
        return base_prompt
    return base_prompt.rstrip() + "\n" + render_silver_label_constraints(
        sample,
        max_elements=silver_elements_limit,
    )


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
    metadata_root: Path | None = None,
    category: str = "dataset_figurine",
    output_suffix: str = LEGACY_OUTPUT_SUFFIX,
) -> dict[str, Any]:
    """Generate or resume one paired front-view sample."""
    sample_dir = output_root / sample.sample_id
    metadata_dir = (
        metadata_root / category / sample.sample_id
        if metadata_root is not None
        else output_root / "_metadata" / sample.sample_id
    )
    _migrate_legacy_metadata(sample_dir, metadata_dir)
    existing = _success_image(sample_dir, sample.sample_id, output_suffix)
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
            "category": category,
            "status": "skipped",
            "reason": "success_exists",
            "output": str(existing),
            "original": str(original_path),
            "gold": str(gold_path),
        }
    metadata_dir.mkdir(parents=True, exist_ok=True)
    (metadata_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    preview = _request_preview(
        sample,
        prompt_file,
        prompt,
        sample_dir,
        category=category,
        output_suffix=output_suffix,
    )
    _write_json(metadata_dir / "request_preview.json", preview)
    if dry_run:
        status = {"schema_version": "front_view_generation_status.v1", "sample_id": sample.sample_id, "category": category, "status": "dry_run", "source_image": str(sample.image_path)}
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
    output_path = sample_dir / f"{sample.sample_id}_{output_suffix}_front_view.{ext}"
    download_result(results[0], output_path)
    with Image.open(output_path) as image:
        size = list(image.size)
    original_path, gold_path = _package_inputs(sample, sample_dir)
    status = {"schema_version": "front_view_generation_status.v1", "sample_id": sample.sample_id, "category": category, "status": "succeeded", "task_id": task_id, "output": str(output_path), "original": str(original_path), "gold": str(gold_path), "size": size, "elapsed_seconds": round(time.time() - started, 2)}
    _write_json(metadata_dir / "status.json", status)
    return status



def read_category_sample_manifest(path: Path) -> list[dict[str, str]]:
    """Read a category selection manifest with category and sample_id columns."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    if not rows:
        raise ValueError(f"Sample manifest is empty: {path}")
    for row_number, row in enumerate(rows, start=2):
        category = str(row.get("category") or "").strip()
        sample_id = str(row.get("sample_id") or "").strip()
        if category not in CATEGORY_REQUIREMENTS:
            raise ValueError(f"Row {row_number} has unsupported category: {category}")
        validate_path_component(sample_id, "sample ID")
        row["category"] = category
        row["sample_id"] = sample_id
    return rows


def build_category_jobs(
    samples: list[Sample],
    *,
    sample_manifest: Path | None,
    requested_ids: list[str],
    limit: int,
    category: str,
) -> list[tuple[str, Sample]]:
    """Return category/sample jobs from a manifest or legacy CLI selection."""
    by_id = {sample.sample_id: sample for sample in samples}
    if sample_manifest is not None:
        jobs: list[tuple[str, Sample]] = []
        for row in read_category_sample_manifest(sample_manifest):
            sample_id = row["sample_id"]
            if sample_id not in by_id:
                raise ValueError(f"Unknown sample_id in selection manifest: {sample_id}")
            jobs.append((row["category"], by_id[sample_id]))
        return jobs
    return [(category, sample) for sample in select_samples(samples, requested_ids, limit)]

def parse_args() -> argparse.Namespace:
    """Parse paired front-view generation arguments."""
    parser = argparse.ArgumentParser(description="Generate paired front-view images without reading paired JSON.")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--prompt-file", type=Path, default=DEFAULT_PROMPT_FILE)
    parser.add_argument("--sample-id", action="append", default=[])
    parser.add_argument("--sample-manifest", type=Path, default=None)
    parser.add_argument("--category", default="dataset_figurine", choices=tuple(CATEGORY_REQUIREMENTS))
    parser.add_argument("--metadata-root", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--poll-interval", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--include-silver-json",
        action="store_true",
        help="Append vendor paired JSON elements to each RunningHub prompt.",
    )
    parser.add_argument("--silver-elements-limit", type=int, default=12)
    return parser.parse_args()


def main() -> None:
    """Run the paired front-view generation batch."""
    args = parse_args()
    if not hasattr(args, "sample_manifest"):
        args.sample_manifest = None
    if not hasattr(args, "category"):
        args.category = "dataset_figurine"
    if not hasattr(args, "metadata_root"):
        args.metadata_root = None
    if args.limit < 0:
        raise SystemExit("--limit must be >= 0")
    if args.workers < 1 or args.workers > 5:
        raise SystemExit("--workers must be between 1 and 5")
    if args.silver_elements_limit < 1:
        raise SystemExit("--silver-elements-limit must be >= 1")
    if not args.dry_run:
        load_api_env(API_ENV_FILE)
        api_key = require_api_key()
    else:
        api_key = ""
    prompt_template = args.prompt_file.read_text(encoding="utf-8-sig").strip()
    if not prompt_template:
        raise SystemExit(f"Prompt file is empty: {args.prompt_file}")
    all_samples = read_manifest(args.input_root)
    jobs = build_category_jobs(
        all_samples,
        sample_manifest=args.sample_manifest,
        requested_ids=args.sample_id,
        limit=args.limit,
        category=args.category,
    )
    if not jobs:
        raise SystemExit("No samples selected")
    prompt_by_category = {
        category: render_generation_prompt(prompt_template, category, "front")
        for category in sorted({category for category, _sample in jobs})
    }
    metadata_root = args.metadata_root
    if metadata_root is None and args.sample_manifest is not None:
        metadata_root = DEFAULT_FIVE_CATEGORY_METADATA_ROOT
    args.output_root.mkdir(parents=True, exist_ok=True)
    if metadata_root is not None:
        metadata_root.mkdir(parents=True, exist_ok=True)
    summary: list[dict[str, Any]] = []
    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_sample = {
            executor.submit(
                process_one,
                sample,
                args.output_root / category if args.sample_manifest else args.output_root,
                args.prompt_file,
                build_sample_prompt(
                    prompt_by_category[category],
                    sample,
                    include_silver_json=args.include_silver_json,
                    silver_elements_limit=args.silver_elements_limit,
                ),
                dry_run=args.dry_run,
                api_key=api_key,
                poll_interval=args.poll_interval,
                timeout=args.timeout,
                metadata_root=metadata_root,
                category=category,
                output_suffix=CATEGORY_OUTPUT_SUFFIXES.get(category, LEGACY_OUTPUT_SUFFIX),
            ): (category, sample)
            for category, sample in jobs
        }
        for future in as_completed(future_to_sample):
            category, sample = future_to_sample[future]
            try:
                status = future.result()
            except Exception as exc:
                status = {
                    "schema_version": "front_view_generation_status.v1",
                    "sample_id": sample.sample_id,
                    "category": category,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                failure_root = metadata_root or args.output_root / "_metadata"
                failure_path = (
                    failure_root / category / sample.sample_id / "status.json"
                    if args.sample_manifest or metadata_root is not None
                    else failure_root / sample.sample_id / "status.json"
                )
                _write_json(failure_path, status)
                failed.append(sample.sample_id)
            summary.append(status)
            print(json.dumps(status, ensure_ascii=False), flush=True)
    selected_order = {
        f"{category}/{sample.sample_id}": index
        for index, (category, sample) in enumerate(jobs)
    }
    summary.sort(
        key=lambda item: selected_order[
            f"{item.get('category', args.category)}/{item['sample_id']}"
        ]
    )
    batch = {
        "schema_version": "front_view_generation_batch.v2",
        "dry_run": args.dry_run,
        "selected": [sample.sample_id for _category, sample in jobs],
        "jobs": [
            {"category": category, "sample_id": sample.sample_id}
            for category, sample in jobs
        ],
        "results": summary,
    }
    summary_root = metadata_root or args.output_root
    _write_json(summary_root / "batch_summary.json", batch)
    _write_json(summary_root / "failed_queue.json", {"schema_version": "front_view_generation_failed_queue.v1", "sample_ids": failed})
    print(json.dumps({"status": "finished", "selected": len(jobs), "dry_run": args.dry_run, "failed": len(failed), "output_root": str(args.output_root), "metadata_root": str(summary_root)}, ensure_ascii=False), flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
