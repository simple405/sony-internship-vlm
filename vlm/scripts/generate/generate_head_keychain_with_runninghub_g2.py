"""Generate one head-keychain sheet with RunningHub G-2.0 image-to-image."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests
from PIL import Image


DEFAULT_DATASET = Path("vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20")
DEFAULT_ATOMIC_DIR = DEFAULT_DATASET / "atomic_rules"
# Note 1: Keep this suffix list in sync with the dataset and download code; it
# defines which local files are considered valid image inputs.
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
DEFAULT_SOURCE_DIR = (
    DEFAULT_DATASET
    / "image"
)
DEFAULT_DIRECT_OUTPUT_DIR = (
    DEFAULT_DATASET
    / "generated"
    / "runninghub"
    / "head_key_chain"
)
DEFAULT_PROMPT_FILE = Path("vlm/prompts/generation/runninghub/runninghub_g2_head_keychain.txt")
# Note 2: The endpoint is configurable from the CLI so this runner can reuse the
# same transport code if RunningHub exposes another compatible image endpoint.
DEFAULT_ENDPOINT = "https://www.runninghub.cn/openapi/v2/rhart-image-g-2/image-to-image"


def parse_args() -> argparse.Namespace:
    # Note 3: This parser supports both single-sample debugging and multi-sample
    # batches. Repeating --sample-id is simpler than maintaining a separate list file here.
    parser = argparse.ArgumentParser(description="Run one RunningHub G-2.0 head_keychain image-to-image task.")
    parser.add_argument("--sample-id", action="append", default=[], help="Sample ID to process. Repeatable.")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--atomic-dir", type=Path, default=DEFAULT_ATOMIC_DIR)
    parser.add_argument(
        "--sample-reference-dir",
        type=Path,
        default=None,
        # Note 4: The option remains for backward compatibility with old shell
        # commands, but the current workflow sends only the complete original image.
        help="Deprecated and ignored. RunningHub requests use only the full original image.",
    )
    parser.add_argument("--allow-missing-sample-reference", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--direct-output-dir", type=Path, default=DEFAULT_DIRECT_OUTPUT_DIR)
    parser.add_argument("--prompt-file", type=Path, default=DEFAULT_PROMPT_FILE)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--aspect-ratio", default="21:9")
    parser.add_argument("--resolution", default="1k", choices=("1k", "2k", "4k"))
    parser.add_argument("--output-suffix", default="head_keychain")
    parser.add_argument("--poll-interval", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--keep-debug-files", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def require_api_key() -> str:
    # Note 5: Keep secrets in environment variables, not in config files or
    # command lines that may be committed or saved in shell history.
    api_key = os.environ.get("RUNNINGHUB_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("RUNNINGHUB_API_KEY is not set in this process.")
    return api_key


def auth_headers(api_key: str, *, json_content: bool = True) -> dict[str, str]:
    # Note 6: Upload requests are multipart/form-data, so they must not force a
    # JSON Content-Type. Other API calls send JSON payloads.
    headers = {"Authorization": f"Bearer {api_key}"}
    if json_content:
        headers["Content-Type"] = "application/json"
    return headers


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
    rules_path = source_sample_dir / f"{sample_id}_atomic_rules.json"

    if image_path is None:
        # Note 11: The fallback order mirrors historical dataset layouts, so old
        # generated samples remain reproducible after folder cleanups.
        image_path = find_flat_sample_image(source_dir, sample_id)
    if image_path is None:
        image_path = find_sample_file(atomic_dir / sample_id, sample_id, "original")
    if not rules_path.exists():
        # Note 12: atomic_rules are normally under the atomic_rules root, but some
        # older runs kept them beside source images; both layouts are accepted.
        rules_path = atomic_dir / sample_id / f"{sample_id}_atomic_rules.json"

    if image_path is None or not image_path.exists():
        raise FileNotFoundError(f"No original image found for sample {sample_id}.")
    if not rules_path.exists():
        raise FileNotFoundError(f"No atomic_rules JSON found for sample {sample_id}.")
    return image_path, rules_path


def resolve_sample_reference_path(reference_dir: Path | None, sample_id: str, allow_missing: bool) -> Path | None:
    # Note 13: This function is retained only to keep older code paths readable.
    # run_one currently sets reference_path to None and does not call it.
    if reference_dir is None:
        return None
    path = find_sample_file(reference_dir / sample_id, sample_id, "head_reference")
    if path is None:
        path = find_sample_file(reference_dir, sample_id, "head_reference")
    if path is not None:
        return path
    if allow_missing:
        return None
    raise FileNotFoundError(f"No head reference found for sample {sample_id} under {reference_dir}.")


def upload_image(api_key: str, image_path: Path) -> dict[str, Any]:
    # Note 14: RunningHub image generation accepts URLs, so local files must be
    # uploaded first to obtain a temporary download_url.
    url = "https://www.runninghub.cn/openapi/v2/media/upload/binary"
    with image_path.open("rb") as handle:
        response = requests.post(
            url,
            headers=auth_headers(api_key, json_content=False),
            files={"file": (image_path.name, handle)},
            timeout=120,
        )
    response.raise_for_status()
    data = response.json()
    # Note 15: RunningHub responses mix HTTP status with body-level status codes,
    # so successful HTTP alone is not enough to trust the upload.
    if data.get("code") not in (0, "0", None):
        raise RuntimeError(f"RunningHub upload failed: {data}")
    payload = data.get("data") or {}
    if not payload.get("download_url"):
        raise RuntimeError(f"RunningHub upload response did not include download_url: {data}")
    return payload


def submit_task(
    api_key: str,
    endpoint: str,
    image_urls: list[str],
    prompt: str,
    aspect_ratio: str,
    resolution: str,
) -> dict[str, Any]:
    # Note 16: Keep the payload shape small and explicit; changing these field
    # names changes the public API contract with RunningHub.
    payload = {
        "prompt": prompt,
        "imageUrls": image_urls,
        "aspectRatio": aspect_ratio,
        "resolution": resolution,
    }
    response = requests.post(endpoint, headers=auth_headers(api_key), data=json.dumps(payload), timeout=120)
    response.raise_for_status()
    data = response.json()
    # Note 17: Treat both explicit errorCode and FAILED status as failures because
    # API versions may report errors differently.
    if data.get("errorCode") or str(data.get("status") or "").upper() == "FAILED":
        raise RuntimeError(f"RunningHub submission failed: {data}")
    if not data.get("taskId"):
        raise RuntimeError(f"RunningHub response did not include taskId: {data}")
    return data


def query_task(api_key: str, task_id: str) -> dict[str, Any]:
    # Note 18: Polling is isolated here so retry or backoff behavior can be added
    # later without changing the higher-level wait loop.
    response = requests.post(
        "https://www.runninghub.cn/openapi/v2/query",
        headers=auth_headers(api_key),
        data=json.dumps({"taskId": task_id}),
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def wait_for_results(api_key: str, task_id: str, poll_interval: int, timeout: int) -> dict[str, Any]:
    # Note 19: The deadline is computed once so the loop cannot run forever if
    # RunningHub keeps returning QUEUED or RUNNING.
    deadline = time.time() + timeout
    while True:
        data = query_task(api_key, task_id)
        status = str(data.get("status") or "").upper()
        if status == "SUCCESS":
            return data
        if status not in {"QUEUED", "RUNNING"}:
            # Note 20: Unknown statuses are considered terminal failures. This is
            # safer for unattended batches than silently polling forever.
            raise RuntimeError(f"RunningHub task failed or stopped: {data}")
        if time.time() >= deadline:
            raise TimeoutError(f"Timed out waiting for RunningHub task {task_id}. Last response: {data}")
        print(json.dumps({"taskId": task_id, "status": status}, ensure_ascii=False), flush=True)
        # Note 21: Progress is printed as JSON so the orchestrator can stream logs
        # and future tools can parse status lines reliably.
        time.sleep(poll_interval)


def download_url(url: str, output_path: Path) -> None:
    # Note 22: Downloads go to a .part file first; replace is atomic on the same
    # filesystem, which avoids leaving corrupt final images after interruptions.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".part")
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with tmp_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    handle.write(chunk)
    tmp_path.replace(output_path)


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
    for index, result in enumerate(results, start=1):
        url = result.get("url")
        if not url:
            # Note 26: Skip malformed result entries instead of failing the whole
            # sample when another result entry may still contain a usable image.
            continue
        output_type = str(result.get("outputType") or "png").strip(".") or "png"
        suffix = f".{output_type.lower()}"
        output_name = f"{sample_id}_{output_suffix}{suffix}" if index == 1 else f"{sample_id}_{output_suffix}_{index}{suffix}"
        output_path = clean_dir / output_name
        download_url(str(url), output_path)
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
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
        "endpoint": args.endpoint,
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
    submit_response = submit_task(api_key, args.endpoint, image_urls, prompt, args.aspect_ratio, args.resolution)
    task_id = str(submit_response["taskId"])
    final_response = wait_for_results(api_key, task_id, args.poll_interval, args.timeout)
    results = final_response.get("results") or []
    downloaded = download_results(results, clean_dir, sample_id, args.output_suffix)

    status = {
        # Note 34: "no_image_url_found" is separated from failure because the
        # remote task may succeed while returning no downloadable image URL.
        "status": "succeeded" if downloaded else "no_image_url_found",
        "sample_id": sample_id,
        "task_id": task_id,
        "endpoint": args.endpoint,
        "aspectRatio": args.aspect_ratio,
        "resolution": args.resolution,
        "elapsed_seconds": round(time.time() - start_time, 2),
        "downloaded_images": [str(path) for path in downloaded],
        "image_metadata": [image_metadata(path) for path in downloaded],
        "clean_dir": str(clean_dir),
        "usage": final_response.get("usage"),
    }
    if args.keep_debug_files:
        # Note 35: Do not persist download_url in debug upload payloads; those
        # URLs can be temporary or sensitive, while other fields are enough for audit.
        safe_uploads = [{key: value for key, value in payload.items() if key != "download_url"} for payload in upload_payloads]
        write_json(debug_dir / f"{sample_id}_runninghub_g2_upload.json", safe_uploads)
        write_json(debug_dir / f"{sample_id}_runninghub_g2_submit_response.json", submit_response)
        write_json(debug_dir / f"{sample_id}_runninghub_g2_final_response.json", final_response)
        write_json(debug_dir / f"{sample_id}_runninghub_g2_status.json", status)
        status["debug_dir"] = str(debug_dir)

    return status


def main() -> None:
    # Note 36: main handles batch-level concerns: argument validation, prompt
    # loading, API-key gating, worker scheduling, and final summary output.
    args = parse_args()
    if args.workers < 1:
        raise ValueError("--workers must be at least 1")
    prompt = args.prompt_file.read_text(encoding="utf-8-sig").strip()
    # Note 37: utf-8-sig lets prompt files survive edits in tools that add a BOM,
    # while strip avoids sending leading or trailing blank lines as part of the prompt.
    if not prompt:
        raise SystemExit("Prompt is empty.")
    sample_ids = list(dict.fromkeys(sample_id.strip() for sample_id in args.sample_id if sample_id.strip()))
    # Note 38: dict.fromkeys preserves user order while removing duplicate ids,
    # preventing accidental duplicate submissions in one command.
    if not sample_ids:
        raise SystemExit("No samples selected. Use --sample-id.")

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
                print(json.dumps(status, ensure_ascii=False), flush=True)
                summaries.append(status)
                if args.stop_on_error:
                    raise
                continue
            print(json.dumps(status, ensure_ascii=False), flush=True)
            summaries.append(status)

    print(
        # Note 42: The final summary mirrors the per-sample status vocabulary so
        # callers can quickly count successes, dry-runs, failures, and empty results.
        json.dumps(
            {
                "status": "finished",
                "selected_samples": len(sample_ids),
                "succeeded": sum(1 for item in summaries if item.get("status") == "succeeded"),
                "dry_run": sum(1 for item in summaries if item.get("status") == "dry_run"),
                "failed": sum(1 for item in summaries if item.get("status") == "failed"),
                "no_image_url_found": sum(1 for item in summaries if item.get("status") == "no_image_url_found"),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
