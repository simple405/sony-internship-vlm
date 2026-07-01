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
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
DEFAULT_SOURCE_DIR = (
    DEFAULT_DATASET
    / "image"
)
DEFAULT_DIRECT_OUTPUT_DIR = (
    DEFAULT_DATASET
    / "generated_3d_no_rules"
    / "runninghub"
    / "head_key_chain"
)
DEFAULT_PROMPT_FILE = Path("vlm/prompts/generation/runninghub/runninghub_g2_head_keychain.txt")
DEFAULT_ENDPOINT = "https://www.runninghub.cn/openapi/v2/rhart-image-g-2/image-to-image"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one RunningHub G-2.0 head_keychain image-to-image task.")
    parser.add_argument("--sample-id", action="append", default=[], help="Sample ID to process. Repeatable.")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--atomic-dir", type=Path, default=DEFAULT_ATOMIC_DIR)
    parser.add_argument(
        "--sample-reference-dir",
        type=Path,
        default=None,
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
    api_key = os.environ.get("RUNNINGHUB_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("RUNNINGHUB_API_KEY is not set in this process.")
    return api_key


def auth_headers(api_key: str, *, json_content: bool = True) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {api_key}"}
    if json_content:
        headers["Content-Type"] = "application/json"
    return headers


def find_sample_file(sample_dir: Path, sample_id: str, suffix_name: str) -> Path | None:
    for suffix in IMAGE_SUFFIXES:
        path = sample_dir / f"{sample_id}_{suffix_name}{suffix}"
        if path.exists():
            return path
    return None


def find_flat_sample_image(source_dir: Path, sample_id: str) -> Path | None:
    if not source_dir.exists():
        return None
    for suffix in IMAGE_SUFFIXES:
        exact = source_dir / f"{sample_id}{suffix}"
        if exact.exists():
            return exact
    matches = sorted(
        path
        for path in source_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES and path.name.startswith(f"{sample_id}_")
    )
    return matches[0] if matches else None


def resolve_sample_paths(source_dir: Path, atomic_dir: Path, sample_id: str) -> tuple[Path, Path]:
    source_sample_dir = source_dir / sample_id
    image_path = find_sample_file(source_sample_dir, sample_id, "original")
    rules_path = source_sample_dir / f"{sample_id}_atomic_rules.json"

    if image_path is None:
        image_path = find_flat_sample_image(source_dir, sample_id)
    if image_path is None:
        image_path = find_sample_file(atomic_dir / sample_id, sample_id, "original")
    if not rules_path.exists():
        rules_path = atomic_dir / sample_id / f"{sample_id}_atomic_rules.json"

    if image_path is None or not image_path.exists():
        raise FileNotFoundError(f"No original image found for sample {sample_id}.")
    if not rules_path.exists():
        raise FileNotFoundError(f"No atomic_rules JSON found for sample {sample_id}.")
    return image_path, rules_path


def resolve_sample_reference_path(reference_dir: Path | None, sample_id: str, allow_missing: bool) -> Path | None:
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
    payload = {
        "prompt": prompt,
        "imageUrls": image_urls,
        "aspectRatio": aspect_ratio,
        "resolution": resolution,
    }
    response = requests.post(endpoint, headers=auth_headers(api_key), data=json.dumps(payload), timeout=120)
    response.raise_for_status()
    data = response.json()
    if data.get("errorCode") or str(data.get("status") or "").upper() == "FAILED":
        raise RuntimeError(f"RunningHub submission failed: {data}")
    if not data.get("taskId"):
        raise RuntimeError(f"RunningHub response did not include taskId: {data}")
    return data


def query_task(api_key: str, task_id: str) -> dict[str, Any]:
    response = requests.post(
        "https://www.runninghub.cn/openapi/v2/query",
        headers=auth_headers(api_key),
        data=json.dumps({"taskId": task_id}),
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def wait_for_results(api_key: str, task_id: str, poll_interval: int, timeout: int) -> dict[str, Any]:
    deadline = time.time() + timeout
    while True:
        data = query_task(api_key, task_id)
        status = str(data.get("status") or "").upper()
        if status == "SUCCESS":
            return data
        if status not in {"QUEUED", "RUNNING"}:
            raise RuntimeError(f"RunningHub task failed or stopped: {data}")
        if time.time() >= deadline:
            raise TimeoutError(f"Timed out waiting for RunningHub task {task_id}. Last response: {data}")
        print(json.dumps({"taskId": task_id, "status": status}, ensure_ascii=False), flush=True)
        time.sleep(poll_interval)


def download_url(url: str, output_path: Path) -> None:
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
    clean_dir.mkdir(parents=True, exist_ok=True)
    original_suffix = image_path.suffix.lower() if image_path.suffix.lower() in IMAGE_SUFFIXES else ".jpg"
    shutil.copy2(image_path, clean_dir / f"{sample_id}_original{original_suffix}")
    shutil.copy2(rules_path, clean_dir / f"{sample_id}_atomic_rules.json")
    if reference_path is not None:
        reference_suffix = reference_path.suffix.lower() if reference_path.suffix.lower() in IMAGE_SUFFIXES else ".png"
        shutil.copy2(reference_path, clean_dir / f"{sample_id}_head_reference{reference_suffix}")


def download_results(results: list[dict[str, Any]], clean_dir: Path, sample_id: str, output_suffix: str) -> list[Path]:
    downloaded: list[Path] = []
    for index, result in enumerate(results, start=1):
        url = result.get("url")
        if not url:
            continue
        output_type = str(result.get("outputType") or "png").strip(".") or "png"
        suffix = f".{output_type.lower()}"
        output_name = f"{sample_id}_{output_suffix}{suffix}" if index == 1 else f"{sample_id}_{output_suffix}_{index}{suffix}"
        output_path = clean_dir / output_name
        download_url(str(url), output_path)
        downloaded.append(output_path)
    return downloaded


def image_metadata(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        return {"path": str(path), "size": list(image.size), "mode": image.mode}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_one(args: argparse.Namespace, prompt: str, api_key: str, sample_id: str) -> dict[str, Any]:
    image_path, rules_path = resolve_sample_paths(args.source_dir, args.atomic_dir, sample_id)
    reference_path = None
    clean_dir = args.direct_output_dir / sample_id
    debug_dir = args.direct_output_dir / "_debug" / sample_id
    copy_inputs(clean_dir, sample_id, image_path, rules_path, reference_path)

    request_preview = {
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
        write_json(debug_dir / f"{sample_id}_runninghub_g2_request_preview.json", request_preview)
        (debug_dir / f"{sample_id}_runninghub_g2_prompt.txt").write_text(prompt, encoding="utf-8")
    if args.dry_run:
        return {"status": "dry_run", "sample_id": sample_id, "clean_dir": str(clean_dir), "debug_dir": str(debug_dir)}

    start_time = time.time()
    upload_payloads = [upload_image(api_key, image_path)]
    image_urls = [str(payload["download_url"]) for payload in upload_payloads]
    submit_response = submit_task(api_key, args.endpoint, image_urls, prompt, args.aspect_ratio, args.resolution)
    task_id = str(submit_response["taskId"])
    final_response = wait_for_results(api_key, task_id, args.poll_interval, args.timeout)
    results = final_response.get("results") or []
    downloaded = download_results(results, clean_dir, sample_id, args.output_suffix)

    status = {
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
        safe_uploads = [{key: value for key, value in payload.items() if key != "download_url"} for payload in upload_payloads]
        write_json(debug_dir / f"{sample_id}_runninghub_g2_upload.json", safe_uploads)
        write_json(debug_dir / f"{sample_id}_runninghub_g2_submit_response.json", submit_response)
        write_json(debug_dir / f"{sample_id}_runninghub_g2_final_response.json", final_response)
        write_json(debug_dir / f"{sample_id}_runninghub_g2_status.json", status)
        status["debug_dir"] = str(debug_dir)

    return status


def main() -> None:
    args = parse_args()
    if args.workers < 1:
        raise ValueError("--workers must be at least 1")
    prompt = args.prompt_file.read_text(encoding="utf-8-sig").strip()
    if not prompt:
        raise SystemExit("Prompt is empty.")
    sample_ids = list(dict.fromkeys(sample_id.strip() for sample_id in args.sample_id if sample_id.strip()))
    if not sample_ids:
        raise SystemExit("No samples selected. Use --sample-id.")

    api_key = "" if args.dry_run else require_api_key()
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
        future_to_sample = {
            executor.submit(run_one, args, prompt, api_key, sample_id): sample_id
            for sample_id in sample_ids
        }
        for future in as_completed(future_to_sample):
            sample_id = future_to_sample[future]
            try:
                status = future.result()
            except Exception as exc:
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
