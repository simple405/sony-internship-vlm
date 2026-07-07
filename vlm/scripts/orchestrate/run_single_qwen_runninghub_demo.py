"""Run one sample through Qwen rule extraction and RunningHub generation."""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import requests

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[3]))

from vlm.scripts.generate.generate_head_keychain_with_runninghub_g2 import (  # noqa: E402
    DEFAULT_ENDPOINT,
    IMAGE_SUFFIXES,
    download_results,
    image_metadata,
    submit_task,
    upload_image,
    wait_for_results,
)


DEFAULT_DATASET = Path("vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20")
DEFAULT_SOURCE_DIR = DEFAULT_DATASET / "image"
DEFAULT_OUTPUT_DIR = Path("vlm/tmp/qwen_runninghub_single_demo")
DEFAULT_REFERENCE_PROMPT_DIR = Path("vlm/archive/ip_review_project/prompts")
DEFAULT_ENV_FILE = Path("vlm/archive/ip_review_project/.env")
DEFAULT_RUNNINGHUB_PROMPT = Path("vlm/prompts/generation/runninghub/runninghub_g2_dataset_figurine_user_cn.txt")
DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one source image through Qwen rules and RunningHub generation.")
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--qwen-api-key", default="", help="Qwen/DashScope API key. Prefer passing via PowerShell variable.")
    parser.add_argument("--qwen-base-url", default=DEFAULT_QWEN_BASE_URL)
    parser.add_argument("--qwen-vision-model", default="qwen-vl-plus")
    parser.add_argument("--qwen-text-model", default="qwen-plus")
    parser.add_argument("--prompt-dir", type=Path, default=DEFAULT_REFERENCE_PROMPT_DIR)
    parser.add_argument("--runninghub-prompt-file", type=Path, default=DEFAULT_RUNNINGHUB_PROMPT)
    parser.add_argument("--runninghub-endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--output-suffix", default="figurine")
    parser.add_argument("--aspect-ratio", default="21:9")
    parser.add_argument("--resolution", default="1k", choices=("1k", "2k", "4k"))
    parser.add_argument("--poll-interval", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--skip-runninghub", action="store_true")
    return parser.parse_args()


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


def apply_env_defaults(args: argparse.Namespace) -> None:
    if args.qwen_base_url == DEFAULT_QWEN_BASE_URL:
        args.qwen_base_url = os.environ.get("QWEN_BASE_URL", args.qwen_base_url).strip() or args.qwen_base_url
    if args.qwen_vision_model == "qwen-vl-plus":
        args.qwen_vision_model = os.environ.get("QWEN_VISION_MODEL", args.qwen_vision_model).strip() or args.qwen_vision_model
    if args.qwen_text_model == "qwen-plus":
        args.qwen_text_model = (
            os.environ.get("QWEN_TEXT_MODEL") or os.environ.get("QWEN_MODEL") or args.qwen_text_model
        ).strip() or args.qwen_text_model


def require_key(value: str, env_name: str) -> str:
    key = value.strip() or os.environ.get(env_name, "").strip()
    if not key:
        raise SystemExit(f"{env_name} is required. Pass --{env_name.lower().replace('_', '-')} or set the environment variable.")
    return key


def find_sample_image(source_dir: Path, sample_id: str) -> Path:
    for suffix in IMAGE_SUFFIXES:
        exact = source_dir / f"{sample_id}{suffix}"
        if exact.exists():
            return exact
    matches = sorted(
        path
        for path in source_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES and path.name.startswith(f"{sample_id}_")
    )
    if not matches:
        raise FileNotFoundError(f"No source image found for sample {sample_id} under {source_dir}")
    return matches[0]


def media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return "image/jpeg"


def encode_image_data_url(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type(path)};base64,{data}"


def qwen_chat(
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    timeout: int = 180,
) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        data=json.dumps({"model": model, "messages": messages}, ensure_ascii=False),
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    try:
        return str(payload["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Qwen response did not include choices[0].message.content: {payload}") from exc


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```").strip()
        stripped = stripped.removesuffix("```").strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(stripped[start : end + 1])


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_qwen_rule_pipeline(args: argparse.Namespace, api_key: str, image_path: Path, sample_dir: Path) -> Path:
    vision_prompt = (args.prompt_dir / "vision_prompt.txt").read_text(encoding="utf-8")
    schema_prompt = (args.prompt_dir / "schema_prompt.txt").read_text(encoding="utf-8")
    atomic_prompt_template = (args.prompt_dir / "extract_atomic_rules_prompt.txt").read_text(encoding="utf-8")

    visual_text = qwen_chat(
        api_key=api_key,
        base_url=args.qwen_base_url,
        model=args.qwen_vision_model,
        messages=[
            {"role": "system", "content": vision_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Analyze this character design sheet and return only valid JSON."},
                    {"type": "image_url", "image_url": {"url": encode_image_data_url(image_path)}},
                ],
            },
        ],
    )
    (sample_dir / "qwen_visual_features_raw.txt").write_text(visual_text, encoding="utf-8")
    visual_json = extract_json_object(visual_text)
    write_json(sample_dir / "qwen_visual_features.json", visual_json)

    schema_text = qwen_chat(
        api_key=api_key,
        base_url=args.qwen_base_url,
        model=args.qwen_text_model,
        messages=[{"role": "user", "content": schema_prompt + "\n" + json.dumps(visual_json, ensure_ascii=False, indent=2)}],
    )
    (sample_dir / "qwen_schema_raw.txt").write_text(schema_text, encoding="utf-8")
    schema_json = extract_json_object(schema_text)
    write_json(sample_dir / "qwen_schema.json", schema_json)

    normalized_rules = schema_json.get("normalized_rules") or schema_json
    atomic_prompt = atomic_prompt_template.replace(
        "{{INSERT_JSON_HERE}}",
        json.dumps(normalized_rules, ensure_ascii=False, indent=2),
    )
    atomic_text = qwen_chat(
        api_key=api_key,
        base_url=args.qwen_base_url,
        model=args.qwen_text_model,
        messages=[{"role": "user", "content": atomic_prompt}],
    )
    (sample_dir / "qwen_atomic_rules_raw.txt").write_text(atomic_text, encoding="utf-8")
    atomic_json = extract_json_object(atomic_text)
    if "atomic_rules" not in atomic_json:
        raise RuntimeError(f"Qwen atomic response did not include atomic_rules: {atomic_json}")

    atomic_path = sample_dir / f"{args.sample_id}_atomic_rules.json"
    write_json(atomic_path, {"code": args.sample_id, "atomic_rules": atomic_json["atomic_rules"]})
    return atomic_path


def run_runninghub(args: argparse.Namespace, image_path: Path, atomic_path: Path, sample_dir: Path) -> dict[str, Any]:
    runninghub_key = require_key("", "RUNNINGHUB_API_KEY")
    prompt = args.runninghub_prompt_file.read_text(encoding="utf-8-sig").strip()
    if not prompt:
        raise SystemExit(f"RunningHub prompt is empty: {args.runninghub_prompt_file}")

    original_suffix = image_path.suffix.lower() if image_path.suffix.lower() in IMAGE_SUFFIXES else ".jpg"
    shutil.copy2(image_path, sample_dir / f"{args.sample_id}_original{original_suffix}")
    atomic_output_path = sample_dir / f"{args.sample_id}_atomic_rules.json"
    if atomic_path.resolve() != atomic_output_path.resolve():
        shutil.copy2(atomic_path, atomic_output_path)
    (sample_dir / f"{args.sample_id}_runninghub_prompt.txt").write_text(prompt, encoding="utf-8")

    started = time.time()
    upload_payload = upload_image(runninghub_key, image_path)
    image_urls = [str(upload_payload["download_url"])]
    submit_response = submit_task(
        runninghub_key,
        args.runninghub_endpoint,
        image_urls,
        prompt,
        args.aspect_ratio,
        args.resolution,
    )
    task_id = str(submit_response["taskId"])
    final_response = wait_for_results(runninghub_key, task_id, args.poll_interval, args.timeout)
    downloaded = download_results(final_response.get("results") or [], sample_dir, args.sample_id, args.output_suffix)

    safe_upload = {key: value for key, value in upload_payload.items() if key != "download_url"}
    status = {
        "status": "succeeded" if downloaded else "no_image_url_found",
        "sample_id": args.sample_id,
        "task_id": task_id,
        "elapsed_seconds": round(time.time() - started, 2),
        "downloaded_images": [str(path) for path in downloaded],
        "image_metadata": [image_metadata(path) for path in downloaded],
    }
    write_json(sample_dir / f"{args.sample_id}_runninghub_upload.json", safe_upload)
    write_json(sample_dir / f"{args.sample_id}_runninghub_submit_response.json", submit_response)
    write_json(sample_dir / f"{args.sample_id}_runninghub_final_response.json", final_response)
    write_json(sample_dir / f"{args.sample_id}_status.json", status)
    return status


def main() -> None:
    args = parse_args()
    load_env_file(args.env_file)
    apply_env_defaults(args)
    qwen_key = require_key(args.qwen_api_key, "QWEN_API_KEY")
    image_path = find_sample_image(args.source_dir, args.sample_id)
    sample_dir = args.output_dir / args.sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)

    write_json(
        sample_dir / "request_preview.json",
        {
            "sample_id": args.sample_id,
            "source_image": str(image_path),
            "output_dir": str(sample_dir),
            "qwen_base_url": args.qwen_base_url,
            "qwen_vision_model": args.qwen_vision_model,
            "qwen_text_model": args.qwen_text_model,
            "runninghub_endpoint": args.runninghub_endpoint,
            "runninghub_prompt_file": str(args.runninghub_prompt_file),
            "skip_runninghub": args.skip_runninghub,
        },
    )

    atomic_path = run_qwen_rule_pipeline(args, qwen_key, image_path, sample_dir)
    status: dict[str, Any] = {"status": "qwen_only", "sample_id": args.sample_id, "atomic_rules": str(atomic_path)}
    if not args.skip_runninghub:
        status = run_runninghub(args, image_path, atomic_path, sample_dir)

    print(json.dumps({"status": "finished", "sample_dir": str(sample_dir), "result": status}, ensure_ascii=False))


if __name__ == "__main__":
    main()
