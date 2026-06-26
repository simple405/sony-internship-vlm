"""Generate a 3D-style figurine design image with Wan from 2D + atomic_rules."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from dashscope.aigc.image_generation import ImageGeneration


DEFAULT_DATASET = Path("vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20")
DEFAULT_METADATA = DEFAULT_DATASET / "metadata.jsonl"
DEFAULT_ATOMIC_DIR = DEFAULT_DATASET / "atomic_rules"
DEFAULT_OUTPUT_ROOT = DEFAULT_DATASET / "generated_3d"
DEFAULT_TEMPLATE = Path("vlm/prompts/generation/wan_3d_figurine_from_atomic_rules.txt")
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate one 3D figurine design image with Wan.")
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--atomic-dir", type=Path, default=DEFAULT_ATOMIC_DIR)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--clean-output-root",
        type=Path,
        default=None,
        help="Default: <output-root>/<model>/dataset_figurine.",
    )
    parser.add_argument("--product-suffix", default="figurine")
    parser.add_argument("--skip-clean-output", action="store_true")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--sample-id", default="", help="Sample post_id/code. If omitted, choose the first valid sample.")
    parser.add_argument("--model", default="wan2.7-image-pro")
    parser.add_argument("--size", default="1328*1328")
    parser.add_argument("--n", type=int, default=1)
    parser.add_argument("--seed", type=int, default=3186795)
    parser.add_argument("--extra-guidance", default="", help="Additional sample-specific generation constraints.")
    parser.add_argument("--guidance-file", type=Path, default=None, help="Optional text file with extra guidance.")
    parser.add_argument("--dry-run", action="store_true", help="Write prompt/request files without calling the API.")
    parser.add_argument("--keep-debug-files", action="store_true", help="Keep per-sample prompt/request/response/status files.")
    parser.add_argument("--wait-timeout", type=int, default=600)
    return parser.parse_args()


def require_api_key() -> str:
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("DASHSCOPE_API_KEY is not set in this process.")
    return api_key


def load_metadata_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def sample_code(row: dict[str, Any]) -> str:
    return str(row.get("post_id") or row.get("code") or "").strip()


def atomic_path(atomic_dir: Path, code: str) -> Path:
    return atomic_dir / code / f"{code}_atomic_rules.json"


def atomic_original_path(atomic_dir: Path, code: str) -> Path | None:
    sample_dir = atomic_dir / code
    for suffix in IMAGE_SUFFIXES:
        path = sample_dir / f"{code}_original{suffix}"
        if path.exists():
            return path
    return None


def choose_sample(rows: list[dict[str, Any]], atomic_dir: Path, requested_code: str) -> tuple[dict[str, Any], Path, Path]:
    for row in rows:
        code = sample_code(row)
        if requested_code and code != requested_code:
            continue
        image_path = atomic_original_path(atomic_dir, code) or Path(str(row.get("image_path") or ""))
        rules_path = atomic_path(atomic_dir, code)
        if code and image_path.exists() and rules_path.exists() and rules_path.stat().st_size > 0:
            return row, image_path, rules_path
    if requested_code:
        raise FileNotFoundError(f"No valid sample found for sample id {requested_code!r}.")
    raise FileNotFoundError("No valid sample with image and atomic_rules was found.")


def format_atomic_rules(rules: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for rule in rules:
        rule_id = str(rule.get("id", "")).strip()
        value = rule.get("value")
        if not rule_id:
            continue
        if isinstance(value, bool):
            value_text = "true" if value else "false"
        else:
            value_text = str(value).strip()
        if value_text:
            lines.append(f"- {rule_id}: {value_text}")
    return "\n".join(lines)


def load_extra_guidance(extra_guidance: str, guidance_file: Path | None) -> str:
    guidance_parts: list[str] = []
    if guidance_file:
        guidance_parts.append(guidance_file.read_text(encoding="utf-8-sig").strip())
    if extra_guidance.strip():
        guidance_parts.append(extra_guidance.strip())
    return "\n".join(part for part in guidance_parts if part)


def build_prompt(template_path: Path, rules_path: Path, extra_guidance: str = "") -> tuple[str, dict[str, Any]]:
    doc = json.loads(rules_path.read_text(encoding="utf-8-sig"))
    rules = doc.get("atomic_rules", [])
    if not isinstance(rules, list) or not rules:
        raise ValueError(f"{rules_path} has no usable atomic_rules.")
    template = template_path.read_text(encoding="utf-8-sig")
    prompt = template.replace("{{ATOMIC_RULES}}", format_atomic_rules(rules))
    if extra_guidance:
        prompt = f"{prompt.rstrip()}\n\nAdditional sample-specific guidance:\n{extra_guidance}\n"
    return prompt, doc


def response_to_dict(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    if hasattr(response, "__dict__"):
        return json.loads(json.dumps(response, default=lambda value: getattr(value, "__dict__", str(value))))
    return json.loads(json.dumps(response, default=str))


def extract_image_urls(response_dict: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    output = response_dict.get("output") or {}
    if isinstance(output, dict):
        choices = output.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message") or {}
                content = message.get("content") if isinstance(message, dict) else None
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict):
                            url = item.get("image") or item.get("url") or item.get("image_url")
                            if url:
                                urls.append(str(url))
        for key in ("results", "images"):
            items = output.get(key)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        url = item.get("url") or item.get("image_url") or item.get("image")
                        if url:
                            urls.append(str(url))
                    elif isinstance(item, str):
                        urls.append(item)
        result = output.get("result")
        if isinstance(result, dict):
            url = result.get("url") or result.get("image_url") or result.get("image")
            if url:
                urls.append(str(url))
    return urls


def sanitize_response_for_log(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            lowered = key.lower()
            if lowered in {"headers"}:
                sanitized[key] = {
                    header_key: header_value
                    for header_key, header_value in item.items()
                    if str(header_key).lower() in {"x-request-id", "content-type", "date"}
                } if isinstance(item, dict) else "<redacted>"
                continue
            if lowered in {"signature", "ossaccesskeyid", "authorization"}:
                sanitized[key] = "<redacted>"
                continue
            sanitized[key] = sanitize_response_for_log(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_response_for_log(item) for item in value]
    if isinstance(value, str) and value.startswith("http"):
        parsed = urlparse(value)
        if parsed.query:
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?<redacted>"
    return value


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


def suffix_from_url(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return suffix
    return ".png"


def export_clean_sample(
    clean_output_root: Path,
    code: str,
    image_path: Path,
    rules_path: Path,
    generated_image_path: Path,
    product_suffix: str,
) -> dict[str, str]:
    clean_dir = clean_output_root / code
    clean_dir.mkdir(parents=True, exist_ok=True)

    original_suffix = image_path.suffix.lower() if image_path.suffix.lower() in IMAGE_SUFFIXES else ".jpg"
    generated_suffix = (
        generated_image_path.suffix.lower()
        if generated_image_path.suffix.lower() in IMAGE_SUFFIXES
        else ".png"
    )
    original_out = clean_dir / f"{code}_original{original_suffix}"
    generated_out = clean_dir / f"{code}_{product_suffix}{generated_suffix}"
    rules_out = clean_dir / f"{code}_atomic_rules.json"

    shutil.copy2(image_path, original_out)
    if generated_image_path.resolve() != generated_out.resolve():
        shutil.copy2(generated_image_path, generated_out)
    shutil.copy2(rules_path, rules_out)

    return {
        "clean_dir": str(clean_dir),
        "original": str(original_out),
        "generated": str(generated_out),
        "atomic_rules": str(rules_out),
    }


def append_run_log(output_root: Path, model: str, status: dict[str, Any]) -> Path:
    log_path = output_root / model / "generation_runs.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(status, ensure_ascii=False) + "\n")
    return log_path


def main() -> None:
    args = parse_args()
    rows = load_metadata_rows(args.metadata)
    row, image_path, rules_path = choose_sample(rows, args.atomic_dir, args.sample_id)
    code = sample_code(row)
    extra_guidance = load_extra_guidance(args.extra_guidance, args.guidance_file)
    prompt, rules_doc = build_prompt(args.template, rules_path, extra_guidance)
    clean_output_root = args.clean_output_root or (args.output_root / args.model / "dataset_figurine")

    debug_dir = args.output_root / args.model / "_debug" / code
    prompt_path = debug_dir / f"{code}_wan_3d_figurine_prompt.txt"
    request_path = debug_dir / f"{code}_wan_3d_figurine_request.json"
    response_path = debug_dir / f"{code}_wan_3d_figurine_response.json"
    status_path = debug_dir / f"{code}_wan_3d_figurine_status.json"

    messages = [
        {
            "role": "user",
            "content": [
                {"image": str(image_path)},
                {"text": prompt},
            ],
        }
    ]
    request_payload = {
        "model": args.model,
        "messages": messages,
        "parameters": {
            "size": args.size,
            "n": args.n,
            "seed": args.seed,
        },
        "sample_id": code,
        "image_path": str(image_path),
        "atomic_rules_path": str(rules_path),
        "atomic_rules_count": len(rules_doc.get("atomic_rules", [])),
        "extra_guidance": extra_guidance,
    }

    if args.keep_debug_files or args.dry_run:
        debug_dir.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")
        request_path.write_text(json.dumps(request_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.dry_run:
        if args.keep_debug_files:
            status_path.write_text(
                json.dumps({"status": "dry_run", "sample_id": code, "debug_dir": str(debug_dir)}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        print(f"Dry run written to {debug_dir}")
        return

    api_key = require_api_key()
    start_time = time.time()
    response = ImageGeneration.call(
        model=args.model,
        api_key=api_key,
        messages=messages,
        size=args.size,
        n=args.n,
        seed=args.seed,
    )
    response_dict = response_to_dict(response)

    status_code = response_dict.get("status_code")
    if status_code and int(status_code) >= 400:
        error_status = {"status": "api_error", "sample_id": code, "status_code": status_code}
        if args.keep_debug_files:
            response_path.write_text(
                json.dumps(sanitize_response_for_log(response_dict), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            error_status["response_path"] = str(response_path)
            status_path.write_text(json.dumps(error_status, ensure_ascii=False, indent=2), encoding="utf-8")
        append_run_log(args.output_root, args.model, error_status)
        raise RuntimeError(f"DashScope returned status_code={status_code}. Use --keep-debug-files to save full response details.")

    urls = extract_image_urls(response_dict)
    downloaded: list[str] = []
    for index, url in enumerate(urls, start=1):
        suffix = suffix_from_url(url)
        if args.keep_debug_files:
            image_out = debug_dir / f"{code}_wan_3d_figurine_{index}{suffix}"
        elif not args.skip_clean_output and index == 1:
            image_out = clean_output_root / code / f"{code}_{args.product_suffix}{suffix}"
        else:
            image_out = args.output_root / args.model / "_images" / code / f"{code}_wan_3d_figurine_{index}{suffix}"
        download_url(url, image_out)
        downloaded.append(str(image_out))

    clean_sample: dict[str, str] | None = None
    if downloaded and not args.skip_clean_output:
        clean_sample = export_clean_sample(
            clean_output_root,
            code,
            image_path,
            rules_path,
            Path(downloaded[0]),
            args.product_suffix,
        )

    if args.keep_debug_files:
        response_path.write_text(
            json.dumps(sanitize_response_for_log(response_dict), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    status = {
        "status": "succeeded" if downloaded else "no_image_url_found",
        "sample_id": code,
        "model": args.model,
        "elapsed_seconds": round(time.time() - start_time, 2),
        "downloaded_images": downloaded,
        "clean_sample": clean_sample,
    }
    if args.keep_debug_files:
        status["debug_dir"] = str(debug_dir)
        status["prompt_path"] = str(prompt_path)
        status["request_path"] = str(request_path)
        status["response_path"] = str(response_path)
        status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    status["run_log"] = str(append_run_log(args.output_root, args.model, status))
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
