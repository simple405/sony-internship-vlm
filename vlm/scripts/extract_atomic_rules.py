"""Extract SN-7 atomic_rules.json files from design sheets with Qwen VL.

The runner is resumable: an existing successful result is never overwritten,
while failed samples receive an error.json and can be retried later. The default
pilot limit is 50; pass --limit 0 for all manifest rows after the pilot review.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image
import requests

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from vlm.scripts._http import direct_http_session
from vlm.scripts._dataset_manifest import (
    atomic_status_fields,
    CONSOLIDATED_MANIFEST,
    MANIFEST_COLUMNS,
    SN7_DATASET_ROOT,
    SN7_DATASET_ID,
    read_manifest_rows,
    resolve_manifest_image,
    update_dataset_fields,
)
from vlm.scripts._paths import API_ENV_FILE, load_api_env
from vlm.scripts._validation import (
    validate_path_component,
    validate_qwen_base_url,
)

DEFAULT_ROOT = SN7_DATASET_ROOT
DEFAULT_MANIFEST = CONSOLIDATED_MANIFEST
DEFAULT_OUTPUT = DEFAULT_ROOT / "atomic_rules"
DEFAULT_PROMPT = Path("vlm/prompts/supervision/atomic_rules_cn.txt")
DEFAULT_MODEL = "qwen3-vl-plus"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
SUPPORTED_SUFFIXES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
LINE_ART_ERROR_TYPE = "black_white_line_art"


def parse_args() -> argparse.Namespace:
    """Parse atomic-rules extraction arguments."""
    parser = argparse.ArgumentParser(description="Extract atomic rules from SN-7 design sheets.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--env-file", type=Path, default=API_ENV_FILE)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=50, help="Pilot size; 0 means all pending rows.")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=4000)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--new-only",
        action="store_true",
        help="Skip legacy rule files when selecting the pilot; useful for a new crawl batch.",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    """Return the SHA-256 digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON object without exposing a partially written destination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def media_data_url(path: Path) -> str:
    """Encode an image file as a data URL for Qwen."""
    mime = SUPPORTED_SUFFIXES.get(path.suffix.lower())
    if not mime:
        raise ValueError(f"Unsupported image suffix: {path}")
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError(f"Input image exceeds 64 MiB: {path}")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def is_probable_black_white_line_art(path: Path) -> bool:
    """Return whether an image is an obvious black/white line-art draft.

    The gate is intentionally conservative: it only blocks images that are both
    nearly colorless and dominated by white paper plus dark contour pixels.
    Colored character sheets and grayscale shaded artwork should continue to
    the VLM review instead of being rejected locally.
    """
    with Image.open(path) as image:
        image = image.convert("RGB")
        image.thumbnail((512, 512))
        pixels = list(image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata())
    if not pixels:
        return False
    total = len(pixels)
    near_gray = 0
    very_light = 0
    very_dark = 0
    midtone = 0
    chroma_values: list[int] = []
    for red, green, blue in pixels:
        high = max(red, green, blue)
        low = min(red, green, blue)
        chroma = high - low
        chroma_values.append(chroma)
        if chroma <= 12:
            near_gray += 1
        luminance = int(0.299 * red + 0.587 * green + 0.114 * blue)
        if luminance >= 238:
            very_light += 1
        elif luminance <= 45:
            very_dark += 1
        else:
            midtone += 1
    gray_ratio = near_gray / total
    white_ratio = very_light / total
    dark_ratio = very_dark / total
    midtone_ratio = midtone / total
    chroma_mean = sum(chroma_values) / total
    return (
        gray_ratio >= 0.985
        and chroma_mean <= 4.0
        and white_ratio >= 0.72
        and 0.015 <= dark_ratio <= 0.22
        and midtone_ratio <= 0.25
    )


def load_rows(path: Path) -> list[dict[str, str]]:
    """Load manifest rows that contain sample IDs."""
    return [
        row
        for row in read_manifest_rows(path, dataset_id=SN7_DATASET_ID)
        if row.get("post_id") or row.get("sample_id")
    ]


def resolve_image_path(row: dict[str, str], manifest_path: Path) -> Path:
    """Resolve a portable image path relative to its declaring manifest."""
    return resolve_manifest_image(manifest_path, row)


def parse_json(text: str) -> dict[str, Any]:
    """Parse a JSON object from plain or fenced model output."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("Qwen response must be a JSON object")
    return value


def snake_case(value: Any) -> str:
    """Normalize a rule name to snake_case."""
    text = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").strip()).strip("_").lower()
    return text or "unnamed_rule"


def normalize_rule_id(value: Any) -> str:
    """Return a rule id while preserving natural Chinese labels."""
    text = str(value or "").strip()
    if re.search(r"[\u4e00-\u9fff]", text):
        return re.sub(r"\s+", "", text)
    return snake_case(text)


def normalize_location(value: Any) -> str:
    """Normalize English or Chinese locations to the current JSON contract."""
    text = str(value or "").strip().lower()
    if text in {"head", "头部"}:
        return "头部"
    if text in {"body", "身体"}:
        return "身体"
    return text


def normalize_rules(raw: dict[str, Any], sample_id: str, image_path: Path, model: str, prompt_hash: str, elapsed: float) -> dict[str, Any]:
    """Normalize raw model rules to the atomic_rules.v1 contract."""
    if isinstance(raw.get("error"), dict):
        error_type = str(raw["error"].get("type", "")).strip() or "model_rejected_input"
        message = str(raw["error"].get("message", "")).strip()
        raise ValueError(f"{error_type}: {message}")
    rules = raw.get("atomic_rules", raw.get("rules", []))
    if not isinstance(rules, list):
        raise ValueError("atomic_rules must be a list")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in rules:
        if not isinstance(item, dict):
            continue
        rule_id = normalize_rule_id(item.get("id", item.get("rule_id", item.get("name"))))
        if rule_id in seen:
            continue
        if "value" not in item:
            continue
        location = normalize_location(item.get("location", ""))
        if location not in {"头部", "身体"}:
            raise ValueError(f"Rule {rule_id!r} must include location=头部 or location=身体")
        seen.add(rule_id)
        value = item["value"]
        if not isinstance(value, (str, int, float, bool)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        normalized.append({"id": rule_id, "location": location, "value": value})
    return {
        "schema_version": "atomic_rules.v1",
        "code": sample_id,
        "source_image": str(image_path),
        "atomic_rules": normalized,
        "metadata": {
            "model": model,
            "prompt_sha256": prompt_hash,
            "image_sha256": sha256(image_path),
            "created_at": datetime.now().astimezone().isoformat(),
            "elapsed_seconds": round(elapsed, 2),
        },
    }


def messages(prompt: str, image_path: Path) -> list[dict[str, Any]]:
    """Build the Qwen request messages for one image."""
    return [
        {"role": "system", "content": "你只能输出严格有效的 JSON，不要输出解释、Markdown 或思维链。"},
        {"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": media_data_url(image_path)}},
        ]},
    ]


def call_qwen(api_key: str, base_url: str, model: str, prompt: str, image_path: Path, args: argparse.Namespace) -> tuple[str, int, float]:
    """Call Qwen and return raw text, attempts, and elapsed time."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages(prompt, image_path),
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "response_format": {"type": "json_object"},
    }
    last_error: Exception | None = None
    started = time.time()
    with direct_http_session() as session:
        for attempt in range(args.max_retries + 1):
            try:
                response = session.post(
                    base_url.rstrip("/") + "/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=args.timeout,
                    allow_redirects=False,
                )
                if response.status_code in {401, 403, 400}:
                    response.raise_for_status()
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                return str(content), attempt, time.time() - started
            except (requests.RequestException, KeyError, IndexError, TypeError) as exc:
                last_error = exc
                if attempt >= args.max_retries:
                    break
                time.sleep(min(30.0, 2.0**attempt))
    raise RuntimeError(f"Qwen request failed after retries: {last_error}")


def classify_rejection(message: str) -> str:
    """Classify extraction failures for retry and audit reports."""
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
        LINE_ART_ERROR_TYPE,
        "line-art",
        "线条稿",
    )
    return "content_policy_or_provider_rejection" if any(marker in lowered for marker in content_markers) else "runtime_error"


def process_row(row: dict[str, str], prompt: str, prompt_hash: str, args: argparse.Namespace, api_key: str, base_url: str) -> dict[str, Any]:
    """Process one manifest row into an atomic_rules result."""
    sample_id = validate_path_component(str(row["post_id"]), "sample ID")
    image_path = resolve_image_path(row, args.manifest)
    sample_dir = args.output_root / sample_id
    result_path = sample_dir / "atomic_rules.json"
    legacy_path = sample_dir / f"{sample_id}_atomic_rules.json"
    if legacy_path.exists() and not result_path.exists() and not args.overwrite:
        legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
        normalized = normalize_rules(legacy, sample_id, image_path, "legacy_import", "legacy", 0.0)
        normalized["metadata"]["source"] = str(legacy_path)
        write_json_atomic(result_path, normalized)
        (sample_dir / "error.json").unlink(missing_ok=True)
        return {"status": "imported", "sample_id": sample_id, "rule_count": len(normalized["atomic_rules"]), "result_path": str(result_path)}
    if result_path.exists() and not args.overwrite:
        (sample_dir / "error.json").unlink(missing_ok=True)
        return {"status": "skipped", "sample_id": sample_id, "result_path": str(result_path)}
    sample_dir.mkdir(parents=True, exist_ok=True)
    (sample_dir / "request_redacted.json").write_text(json.dumps({
        "model": args.model, "base_url": base_url, "image_path": str(image_path),
        "prompt_sha256": prompt_hash, "temperature": args.temperature,
        "max_tokens": args.max_tokens, "api_key_included": False,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (sample_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    if args.dry_run:
        return {"status": "dry_run", "sample_id": sample_id}
    if not image_path.exists():
        raise FileNotFoundError(image_path)
    if is_probable_black_white_line_art(image_path):
        raise ValueError(f"{LINE_ART_ERROR_TYPE}: obvious black/white line-art input")
    raw_text, attempts, elapsed = call_qwen(api_key, base_url, args.model, prompt, image_path, args)
    (sample_dir / "raw_response.txt").write_text(raw_text, encoding="utf-8")
    result = normalize_rules(parse_json(raw_text), sample_id, image_path, args.model, prompt_hash, elapsed)
    result["metadata"]["attempts"] = attempts + 1
    write_json_atomic(result_path, result)
    (sample_dir / "error.json").unlink(missing_ok=True)
    return {"status": "ok", "sample_id": sample_id, "rule_count": len(result["atomic_rules"]), "result_path": str(result_path)}


def main() -> None:
    """Run the atomic-rules extraction batch."""
    args = parse_args()
    if args.limit < 0 or args.workers < 1 or args.max_retries < 0:
        raise SystemExit("--limit and --max-retries must be >= 0; --workers must be >= 1")
    load_api_env(args.env_file)
    prompt = args.prompt.read_text(encoding="utf-8")
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    base_url = validate_qwen_base_url(os.environ.get("QWEN_BASE_URL", DEFAULT_BASE_URL))
    api_key = os.environ.get("QWEN_API_KEY", "").strip()
    if not args.dry_run and not api_key:
        raise SystemExit("QWEN_API_KEY is required for a live extraction run")
    rows = load_rows(args.manifest)
    seen_ids: set[str] = set()
    for row in rows:
        sample_id = validate_path_component(str(row["post_id"]), "sample ID")
        if sample_id in seen_ids:
            raise ValueError(f"Duplicate sample ID in manifest: {sample_id}")
        seen_ids.add(sample_id)
        row["post_id"] = sample_id

    def has_result(row: dict[str, str]) -> bool:
        sample_dir = args.output_root / str(row["post_id"])
        return (sample_dir / "atomic_rules.json").exists()

    pending = [row for row in rows if args.overwrite or not has_result(row)]
    if args.new_only:
        pending = [
            row for row in pending
            if not (args.output_root / str(row["post_id"]) / f"{row['post_id']}_atomic_rules.json").exists()
        ]
    if args.limit > 0:
        pending = pending[:args.limit]
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers if not args.dry_run else 1)) as pool:
        futures = {pool.submit(process_row, row, prompt, prompt_hash, args, api_key, base_url): row for row in pending}
        for future in as_completed(futures):
            row = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                sample_id = validate_path_component(str(row["post_id"]), "sample ID")
                sample_dir = args.output_root / sample_id
                sample_dir.mkdir(parents=True, exist_ok=True)
                error = {
                    "schema_version": "atomic_rules_error.v1",
                    "status": "error",
                    "stage": "qwen_atomic_rules",
                    "sample_id": sample_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "rejection_type": classify_rejection(str(exc)),
                }
                write_json_atomic(sample_dir / "error.json", error)
                result = error
            print(json.dumps(result, ensure_ascii=False))
            results.append(result)
    summary = {
        "status": "ok" if not any(item["status"] == "error" for item in results) else "error",
        "requested": len(pending),
        "success": sum(item["status"] == "ok" for item in results),
        "skipped": sum(item["status"] == "skipped" for item in results),
        "errors": sum(item["status"] == "error" for item in results),
        "pilot_limit": args.limit,
    }
    args.output_root.mkdir(parents=True, exist_ok=True)
    write_json_atomic(args.output_root / "extraction_summary.json", summary)
    if not args.dry_run and args.manifest.resolve() == CONSOLIDATED_MANIFEST.resolve():
        update_dataset_fields(
            CONSOLIDATED_MANIFEST,
            SN7_DATASET_ID,
            {
                str(row["post_id"]): atomic_status_fields(
                    args.output_root,
                    str(row["post_id"]),
                )
                for row in rows
            },
            MANIFEST_COLUMNS,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
