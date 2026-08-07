"""Generate SN-7 merchandise three-view sheets with RunningHub G-2.0."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from PIL import Image

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[3]))

from vlm.scripts.utils.atomic_rule_xlsx import write_atomic_rules_xlsx
from vlm.scripts.generate.runninghub_client import (
    DEFAULT_ENDPOINT,
    IMAGE_SUFFIXES,
    download_result as download_runninghub_result,
    load_api_env,
    poll_task,
    require_api_key,
    safe_result_extension,
    submit_task,
    upload_image,
)
from vlm.scripts.generate.prompt_renderer import (
    CATEGORY_REQUIREMENTS,
    render_generation_prompt,
)
from vlm.scripts._validation import validate_path_component


DEFAULT_DATASET = Path("vlm/data/design_sheet_10610")
DEFAULT_ATOMIC_DIR = DEFAULT_DATASET / "atomic_rules"
# Note 1: Keep this suffix list in sync with the dataset and download code; it
# defines which local files are considered valid image inputs.
DEFAULT_SOURCE_DIR = (
    DEFAULT_DATASET
    / "image"
)
DEFAULT_PROMPT_FILE = Path("vlm/prompts/generation/runninghub/merchandise_generation_cn.txt")


def parse_args() -> argparse.Namespace:
    # Note 3: This parser supports both single-sample debugging and multi-sample
    # batches. Repeating --sample-id is simpler than maintaining a separate list file here.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-id", action="append", default=[], help="Sample ID to process. Repeatable.")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--atomic-dir", type=Path, default=DEFAULT_ATOMIC_DIR)
    parser.add_argument("--direct-output-dir", type=Path, default=None)
    parser.add_argument("--prompt-file", type=Path, default=DEFAULT_PROMPT_FILE)
    parser.add_argument("--aspect-ratio", default="21:9")
    parser.add_argument("--resolution", default="1k", choices=("1k", "2k", "4k"))
    parser.add_argument("--output-suffix", default="head_keychain")
    parser.add_argument(
        "--category",
        default="head_key_chain",
        choices=tuple(CATEGORY_REQUIREMENTS),
        help="Merchandise category used for prompt rendering and annotation export.",
    )
    parser.add_argument("--poll-interval", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--keep-debug-files", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def find_sample_file(sample_dir: Path, sample_id: str, suffix_name: str) -> Path | None:
    # Note 7: Samples may be stored as png, jpg, jpeg, or webp. Returning the
    # first existing conventional filename keeps lookup deterministic.
    for suffix in IMAGE_SUFFIXES:
        path = sample_dir / f"{sample_id}_{suffix_name}{suffix}"
        if path.exists():
            return path
    return None


def find_flat_sample_image(source_dir: Path, sample_id: str) -> Path | None:
    # Note 8: Some inputs are stored flat as "<id>_hash.png" instead of inside an
    # id-named directory. This fallback supports both dataset layouts.
    if not source_dir.exists():
        return None
    for suffix in IMAGE_SUFFIXES:
        exact = source_dir / f"{sample_id}{suffix}"
        if exact.exists():
            return exact
    matches = sorted(
        # Note 9: Sorting prevents accidental nondeterminism if multiple files
        # share the same id prefix.
        path
        for path in source_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES and path.name.startswith(f"{sample_id}_")
    )
    return matches[0] if matches else None


def resolve_sample_paths(source_dir: Path, atomic_dir: Path, sample_id: str) -> tuple[Path, Path]:
    # Note 10: The generator needs two local inputs: the original 2D image for
    # RunningHub upload and the atomic_rules JSON for archived provenance.
    source_sample_dir = source_dir / sample_id
    image_path = find_sample_file(source_sample_dir, sample_id, "original")
    rules_candidates = [
        source_sample_dir / "atomic_rules.json",
        source_sample_dir / f"{sample_id}_atomic_rules.json",
        atomic_dir / sample_id / "atomic_rules.json",
        atomic_dir / sample_id / f"{sample_id}_atomic_rules.json",
    ]
    rules_path = next((path for path in rules_candidates if path.exists()), rules_candidates[0])

    if image_path is None:
        # Note 11: The fallback order mirrors historical dataset layouts, so old
        # generated samples remain reproducible after folder cleanups.
        image_path = find_flat_sample_image(source_dir, sample_id)
    if image_path is None:
        image_path = find_sample_file(atomic_dir / sample_id, sample_id, "original")

    if image_path is None or not image_path.exists():
        raise FileNotFoundError(f"No original image found for sample {sample_id}.")
    if not rules_path.exists():
        raise FileNotFoundError(f"No atomic_rules JSON found for sample {sample_id}.")
    return image_path, rules_path


def copy_inputs(clean_dir: Path, sample_id: str, image_path: Path, rules_path: Path, reference_path: Path | None) -> None:
    # Note 23: Each output folder stores the exact input image and atomic_rules
    # used for generation, making later visual audits reproducible.
    clean_dir.mkdir(parents=True, exist_ok=True)
    original_suffix = image_path.suffix.lower() if image_path.suffix.lower() in IMAGE_SUFFIXES else ".jpg"
    shutil.copy2(image_path, clean_dir / f"{sample_id}_original{original_suffix}")
    shutil.copy2(rules_path, clean_dir / f"{sample_id}_atomic_rules.json")
    if reference_path is not None:
        # Note 24: Reference copying remains for historical compatibility even
        # though the current RunningHub request does not upload head_reference.
        reference_suffix = reference_path.suffix.lower() if reference_path.suffix.lower() in IMAGE_SUFFIXES else ".png"
        shutil.copy2(reference_path, clean_dir / f"{sample_id}_head_reference{reference_suffix}")


def download_results(results: list[dict[str, Any]], clean_dir: Path, sample_id: str, output_suffix: str) -> list[Path]:
    # Note 25: Some API responses can contain multiple output URLs. The first
    # keeps the canonical name; later outputs get numeric suffixes.
    downloaded: list[Path] = []
    for result in results:
        url = result.get("url")
        if not url:
            # Note 26: Skip malformed result entries instead of failing the whole
            # sample when another result entry may still contain a usable image.
            continue
        index = len(downloaded) + 1
        suffix = safe_result_extension(result.get("outputType"))
        output_name = f"{sample_id}_{output_suffix}{suffix}" if index == 1 else f"{sample_id}_{output_suffix}_{index}{suffix}"
        output_path = clean_dir / output_name
        download_runninghub_result(result, output_path)
        downloaded.append(output_path)
    return downloaded


def image_metadata(path: Path) -> dict[str, Any]:
    # Note 27: Stored metadata gives a quick sanity check for downloaded image
    # size and mode without reopening the image during later audits.
    with Image.open(path) as image:
        return {"path": str(path), "size": list(image.size), "mode": image.mode}


def write_json(path: Path, payload: Any) -> None:
    # Note 28: Centralizing JSON writes keeps all debug files consistently
    # formatted and UTF-8 encoded.
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def sanitize_provider_payload(value: Any) -> Any:
    """Remove temporary media URLs before persisting provider responses."""
    if isinstance(value, dict):
        return {
            key: (
                "<redacted>"
                if key.lower() in {"url", "download_url", "imageurl", "imageurls"}
                else sanitize_provider_payload(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_provider_payload(item) for item in value]
    return value


def classify_rejection(message: str) -> str:
    lowered = message.lower()
    content_markers = (
        "datainspectionfailed",
        "content",
        "policy",
        "safety",
        "sensitive",
        "forbidden",
        "审核",
        "敏感",
        "违规",
        "拒绝",
    )
    return "content_policy_or_provider_rejection" if any(marker in lowered for marker in content_markers) else "runtime_error"


def write_generation_error(args: argparse.Namespace, sample_id: str, status: dict[str, Any]) -> None:
    error_payload = {
        "schema_version": "generation_error.v1",
        "stage": "runninghub_multiview",
        **status,
    }
    if status.get("error_message"):
        error_payload["rejection_type"] = classify_rejection(str(status["error_message"]))
    write_json(args.direct_output_dir / sample_id / "generation_error.json", error_payload)


def run_one(args: argparse.Namespace, prompt: str, api_key: str, sample_id: str) -> dict[str, Any]:
    # Note 29: run_one is the unit of work executed by each thread. It returns a
    # JSON-serializable status dict so callers can log or summarize uniformly.
    image_path, rules_path = resolve_sample_paths(args.source_dir, args.atomic_dir, sample_id)
    reference_path = None
    clean_dir = args.direct_output_dir / sample_id
    debug_dir = args.direct_output_dir / "_debug" / sample_id
    copy_inputs(clean_dir, sample_id, image_path, rules_path, reference_path)

    request_preview = {
        # Note 30: The preview file is useful in dry-run mode because it shows
        # exactly what would be sent or archived without spending API credits.
        "sample_id": sample_id,
        "endpoint": DEFAULT_ENDPOINT,
        "image_path": str(image_path),
        "reference_path": "",
        "image_count": 1,
        "prompt_file": str(args.prompt_file),
        "aspectRatio": args.aspect_ratio,
        "resolution": args.resolution,
        "direct_output_dir": str(args.direct_output_dir),
    }
    if args.keep_debug_files or args.dry_run:
        # Note 31: Debug artifacts are opt-in for real runs to avoid excessive
        # disk usage, but dry-runs always write them because they are the output.
        write_json(debug_dir / f"{sample_id}_runninghub_g2_request_preview.json", request_preview)
        (debug_dir / f"{sample_id}_runninghub_g2_prompt.txt").write_text(prompt, encoding="utf-8")
    if args.dry_run:
        # Note 32: Dry-run stops after file resolution and debug preview writing,
        # so it can validate paths and prompts without requiring an API key.
        return {"status": "dry_run", "sample_id": sample_id, "clean_dir": str(clean_dir), "debug_dir": str(debug_dir)}

    start_time = time.time()
    # Note 33: RunningHub receives only the complete original image. atomic_rules
    # are archived locally for provenance and reflected in the prompt file design.
    upload_payloads = [upload_image(api_key, image_path)]
    image_urls = [str(payload["download_url"]) for payload in upload_payloads]
    submit_response = submit_task(
        api_key,
        prompt,
        image_urls,
        aspect_ratio=args.aspect_ratio,
        resolution=args.resolution,
    )
    task_id = str(submit_response["taskId"])
    final_response = poll_task(
        api_key,
        task_id,
        poll_interval=args.poll_interval,
        timeout=args.timeout,
    )
    results = final_response.get("results") or []
    downloaded = download_results(results, clean_dir, sample_id, args.output_suffix)
    annotation_xlsx = ""
    if downloaded:
        annotation_path = clean_dir / f"{sample_id}.xlsx"
        category = args.category or args.direct_output_dir.name
        write_atomic_rules_xlsx(rules_path, annotation_path, category)
        annotation_xlsx = str(annotation_path)

    status = {
        # Note 34: "no_image_url_found" is separated from failure because the
        # remote task may succeed while returning no downloadable image URL.
        "status": "succeeded" if downloaded else "no_image_url_found",
        "sample_id": sample_id,
        "task_id": task_id,
        "endpoint": DEFAULT_ENDPOINT,
        "aspectRatio": args.aspect_ratio,
        "resolution": args.resolution,
        "elapsed_seconds": round(time.time() - start_time, 2),
        "downloaded_images": [str(path) for path in downloaded],
        "annotation_xlsx": annotation_xlsx,
        "image_metadata": [image_metadata(path) for path in downloaded],
        "clean_dir": str(clean_dir),
        "usage": final_response.get("usage"),
    }
    if args.keep_debug_files:
        # Note 35: Do not persist download_url in debug upload payloads; those
        # URLs can be temporary or sensitive, while other fields are enough for audit.
        safe_uploads = [{key: value for key, value in payload.items() if key != "download_url"} for payload in upload_payloads]
        write_json(debug_dir / f"{sample_id}_runninghub_g2_upload.json", safe_uploads)
        write_json(
            debug_dir / f"{sample_id}_runninghub_g2_submit_response.json",
            sanitize_provider_payload(submit_response),
        )
        write_json(
            debug_dir / f"{sample_id}_runninghub_g2_final_response.json",
            sanitize_provider_payload(final_response),
        )
        write_json(debug_dir / f"{sample_id}_runninghub_g2_status.json", status)
        status["debug_dir"] = str(debug_dir)

    return status


def main() -> None:
    # Note 36: main handles batch-level concerns: argument validation, prompt
    # loading, API-key gating, worker scheduling, and final summary output.
    args = parse_args()
    if args.workers < 1:
        raise ValueError("--workers must be at least 1")
    if args.direct_output_dir is None:
        args.direct_output_dir = DEFAULT_DATASET / "generated" / args.category
    prompt_template = args.prompt_file.read_text(encoding="utf-8-sig").strip()
    # Note 37: utf-8-sig lets prompt files survive edits in tools that add a BOM,
    # while strip avoids sending leading or trailing blank lines as part of the prompt.
    if not prompt_template:
        raise SystemExit("Prompt is empty.")
    prompt = render_generation_prompt(prompt_template, args.category, "multiview")
    sample_ids = list(dict.fromkeys(sample_id.strip() for sample_id in args.sample_id if sample_id.strip()))
    # Note 38: dict.fromkeys preserves user order while removing duplicate ids,
    # preventing accidental duplicate submissions in one command.
    if not sample_ids:
        raise SystemExit("No samples selected. Use --sample-id.")
    for sample_id in sample_ids:
        validate_path_component(sample_id, "sample ID")
    validate_path_component(args.output_suffix, "output suffix")

    load_api_env()
    api_key = "" if args.dry_run else require_api_key()
    # Note 39: The batch start line is machine-readable JSON for log parsers and
    # human-readable enough for PowerShell output.
    print(
        json.dumps(
            {
                "status": "batch_started",
                "selected_samples": len(sample_ids),
                "workers": args.workers,
                "direct_output_dir": str(args.direct_output_dir),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    summaries: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        # Note 40: Parallelism is per process and controlled by --workers. Keep it
        # conservative to avoid triggering remote rate limits or local overload.
        future_to_sample = {
            executor.submit(run_one, args, prompt, api_key, sample_id): sample_id
            for sample_id in sample_ids
        }
        for future in as_completed(future_to_sample):
            sample_id = future_to_sample[future]
            try:
                status = future.result()
            except Exception as exc:
                # Note 41: One failed sample should not hide the rest of the batch.
                # --stop-on-error can restore fail-fast behavior when debugging.
                status = {
                    "status": "failed",
                    "sample_id": sample_id,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
                write_generation_error(args, sample_id, status)
                print(json.dumps(status, ensure_ascii=False), flush=True)
                summaries.append(status)
                if args.stop_on_error:
                    raise
                continue
            if status.get("status") in {"failed", "no_image_url_found"}:
                write_generation_error(args, sample_id, status)
            print(json.dumps(status, ensure_ascii=False), flush=True)
            summaries.append(status)

    summary = {
        "status": "finished",
        "selected_samples": len(sample_ids),
        "succeeded": sum(1 for item in summaries if item.get("status") == "succeeded"),
        "dry_run": sum(1 for item in summaries if item.get("status") == "dry_run"),
        "failed": sum(1 for item in summaries if item.get("status") == "failed"),
        "no_image_url_found": sum(
            1 for item in summaries if item.get("status") == "no_image_url_found"
        ),
    }
    print(
        # Note 42: The final summary mirrors the per-sample status vocabulary so
        # callers can quickly count successes, dry-runs, failures, and empty results.
        json.dumps(summary, ensure_ascii=False),
        flush=True,
    )
    if summary["failed"] or summary["no_image_url_found"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
