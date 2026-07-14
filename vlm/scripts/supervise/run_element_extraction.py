"""Run source-2D character element extraction with Qwen VL.

This is a lightweight research runner for Stage 1 of the supervision-agent
pipeline. It reads the small SN_6 pilot dataset, sends only the 2D source image
to the model, and writes one normalized extracted-elements JSON per sample.

Examples:
    python -m vlm.scripts.supervise.run_element_extraction --sample-id char_001 --dry-run
    python -m vlm.scripts.supervise.run_element_extraction --limit 3
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[3]))


DEFAULT_DATA_ROOT = Path("vlm/data/SN_6期动漫数据标注")
DEFAULT_OUTPUT_ROOT = Path("vlm/data/element_extraction_results")
DEFAULT_PROMPT_TEMPLATE = Path("vlm/prompts/supervision/element_extraction_from_2d.txt")
DEFAULT_ENV_FILE = Path("vlm/config/api.env")
DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.7-plus"

VALID_CATEGORIES = {
    "hair",
    "face",
    "skin_body",
    "clothing",
    "footwear",
    "accessory",
    "headwear",
    "prop",
    "other",
}
VALID_CONFIDENCE = {"high", "medium", "low"}

CATEGORY_LABELS = {
    "hair": ("hair", "发型与发色"),
    "eyes": ("face", "眼睛与表情"),
    "head_accessories": ("headwear", "头部配饰"),
    "outfit": ("clothing", "服装结构"),
    "patterns": ("accessory", "图案与色块"),
    "props": ("prop", "道具"),
    "special_body_parts": ("skin_body", "特殊身体特征"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run source-2D character element extraction.")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--sample-id", default="", help="Run one sample, e.g. char_001.")
    parser.add_argument("--limit", type=int, default=0, help="Run the first N samples after filtering.")
    parser.add_argument("--prompt-template", type=Path, default=DEFAULT_PROMPT_TEMPLATE)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--qwen-api-key", default="")
    parser.add_argument("--qwen-base-url", default=DEFAULT_QWEN_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=4000)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true", help="Write prompt/request preview without calling Qwen.")
    parser.add_argument("--workers", type=int, default=6, help="Concurrent Qwen API calls (default 6).")
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


def require_value(cli_value: str, env_name: str, default: str = "") -> str:
    value = cli_value.strip() or os.environ.get(env_name, "").strip() or default
    if not value:
        raise SystemExit(f"{env_name} is required. Set it in {DEFAULT_ENV_FILE} or pass the CLI flag.")
    return value


def media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    raise SystemExit(f"Unsupported image suffix for {path}. Use jpg, jpeg, png, webp, or gif.")


def encode_image_data_url(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"Image not found: {path}")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type(path)};base64,{data}"


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


def discover_samples(data_root: Path, sample_id: str = "", limit: int = 0) -> list[dict[str, Any]]:
    if not data_root.exists():
        raise SystemExit(f"Data root not found: {data_root}")

    sample_dirs = sorted(path for path in data_root.iterdir() if path.is_dir())
    if sample_id:
        sample_dirs = [path for path in sample_dirs if path.name == sample_id]
        if not sample_dirs:
            raise SystemExit(f"Sample not found under {data_root}: {sample_id}")
    if limit > 0:
        sample_dirs = sample_dirs[:limit]

    samples = []
    for sample_dir in sample_dirs:
        json_path = sample_dir / f"{sample_dir.name}.json"
        if not json_path.exists():
            raise SystemExit(f"Missing sample JSON: {json_path}")
        sample = json.loads(json_path.read_text(encoding="utf-8-sig"))
        image_name = str(sample.get("source_image", "")).strip()
        image_path = sample_dir / image_name
        if sample.get("sample_id") != sample_dir.name:
            raise SystemExit(f"sample_id mismatch in {json_path}: {sample.get('sample_id')} != {sample_dir.name}")
        if not image_name or not image_path.exists():
            raise SystemExit(f"Missing source_image for {sample_dir.name}: {image_path}")
        samples.append({
            "sample_id": sample_dir.name,
            "json_path": json_path,
            "source_image": image_name,
            "image_path": image_path,
        })
    return samples


def build_prompt(template_path: Path, *, sample_id: str, source_image: str) -> str:
    template = template_path.read_text(encoding="utf-8")
    return template.replace("{{SAMPLE_ID}}", sample_id).replace("{{SOURCE_IMAGE}}", source_image)


def build_messages(prompt: str, image_path: Path) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": "你只能输出合法 JSON，并严格遵守用户给定的 schema。"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": encode_image_data_url(image_path)}},
            ],
        },
    ]


def qwen_vl_chat(
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    timeout: int,
) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    response = requests.post(
        base_url.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        data=json.dumps(payload, ensure_ascii=False),
        timeout=timeout,
    )
    response.raise_for_status()
    result = response.json()
    try:
        return str(result["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Qwen response missing choices[0].message.content: {result}") from exc


def normalize_category(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return text if text in VALID_CATEGORIES else "other"


def normalize_confidence(value: Any) -> str:
    text = str(value or "").strip().lower().replace("_", " ")
    if text in VALID_CONFIDENCE:
        return text
    if text in {"very high", "0.9", "0.95", "1.0"}:
        return "high"
    return "medium"


def normalize_elements(parsed: dict[str, Any], *, sample: dict[str, Any], model: str, elapsed_seconds: float) -> dict[str, Any]:
    raw_elements = parsed.get("elements")
    if not isinstance(raw_elements, list):
        raw_elements = parsed.get("extracted_elements")
    if not isinstance(raw_elements, list):
        raw_elements = parsed.get("atomic_rules")
    if not isinstance(raw_elements, list):
        raw_elements = elements_from_identity_features(parsed.get("identity_features", {}))
    if not isinstance(raw_elements, list):
        raw_elements = []

    normalized = []
    for index, raw in enumerate(raw_elements, start=1):
        if not isinstance(raw, dict):
            continue
        attributes = raw.get("attributes", {})
        if not isinstance(attributes, dict):
            attributes = {}
        name = str(raw.get("name", "")).strip()
        value = str(raw.get("value", raw.get("description", ""))).strip()
        if not name and not value:
            continue
        normalized.append({
            "element_id": f"{sample['sample_id']}_e{index:03d}",
            "name": name or value[:20],
            "value": value or name,
            "category": normalize_category(raw.get("category")),
            "attributes": {
                "color": str(attributes.get("color", "")).strip(),
                "material": str(attributes.get("material", "")).strip(),
                "shape": str(attributes.get("shape", "")).strip(),
                "location": str(attributes.get("location", "")).strip(),
            },
            "confidence": normalize_confidence(raw.get("confidence")),
        })

    return {
        "schema_version": "element_extraction.v1",
        "task": "source_2d_character_element_extraction",
        "sample_id": sample["sample_id"],
        "source_image": str(sample["image_path"]),
        "elements": normalized,
        "summary": {
            "element_count": len(normalized),
        },
        "metadata": {
            "model": model,
            "created_at": datetime.now().astimezone().isoformat(),
            "elapsed_seconds": round(elapsed_seconds, 2),
            "extraction_method": "observe_then_extract_main_elements",
        },
    }


def stringify_feature(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            if item in (None, "", [], {}):
                continue
            parts.append(f"{key}: {stringify_feature(item)}")
        return "；".join(part for part in parts if part)
    if isinstance(value, list):
        return "；".join(stringify_feature(item) for item in value if item not in (None, "", [], {}))
    if value is None:
        return ""
    return str(value).strip()


def elements_from_identity_features(identity_features: Any) -> list[dict[str, Any]]:
    if not isinstance(identity_features, dict):
        return []
    elements = []
    for key, (category, label) in CATEGORY_LABELS.items():
        value = identity_features.get(key)
        if isinstance(value, list):
            for item in value:
                text = stringify_feature(item)
                if not text:
                    continue
                item_type = item.get("type", "") if isinstance(item, dict) else ""
                elements.append({
                    "name": str(item_type or label).strip(),
                    "value": text,
                    "category": category,
                    "attributes": {
                        "color": "",
                        "material": "",
                        "shape": "",
                        "location": "",
                    },
                    "confidence": "medium",
                })
        else:
            text = stringify_feature(value)
            if not text:
                continue
            elements.append({
                "name": label,
                "value": text,
                "category": category,
                "attributes": {
                    "color": "",
                    "material": "",
                    "shape": "",
                    "location": "",
                },
                "confidence": "medium",
            })
    return elements


def write_request_preview(
    path: Path,
    *,
    model: str,
    base_url: str,
    image_path: Path,
    prompt: str,
    dry_run: bool,
) -> None:
    write_json(path, {
        "model": model,
        "base_url": base_url,
        "image_path": str(image_path),
        "prompt_chars": len(prompt),
        "response_format": {"type": "json_object"},
        "dry_run": dry_run,
        "note": "API key and image bytes are intentionally omitted.",
    })


def run_sample(
    *,
    sample: dict[str, Any],
    prompt_template: Path,
    output_root: Path,
    api_key: str,
    base_url: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
    dry_run: bool,
) -> dict[str, Any]:
    sample_dir = output_root / sample["sample_id"]
    sample_dir.mkdir(parents=True, exist_ok=True)
    prompt = build_prompt(prompt_template, sample_id=sample["sample_id"], source_image=sample["source_image"])

    prompt_path = sample_dir / "element_extraction_prompt.txt"
    request_path = sample_dir / "request_redacted.json"
    raw_path = sample_dir / "raw_response.txt"
    result_path = sample_dir / "extracted_elements.json"
    prompt_path.write_text(prompt, encoding="utf-8")
    write_request_preview(
        request_path,
        model=model,
        base_url=base_url,
        image_path=sample["image_path"],
        prompt=prompt,
        dry_run=dry_run,
    )

    if dry_run:
        return {
            "status": "dry_run",
            "sample_id": sample["sample_id"],
            "prompt_path": str(prompt_path),
            "request_path": str(request_path),
        }

    messages = build_messages(prompt, sample["image_path"])
    started = time.time()
    raw_text = qwen_vl_chat(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    elapsed_seconds = time.time() - started
    raw_path.write_text(raw_text, encoding="utf-8")
    parsed = extract_json_object(raw_text)
    normalized = normalize_elements(parsed, sample=sample, model=model, elapsed_seconds=elapsed_seconds)
    write_json(result_path, normalized)
    return {
        "status": "ok",
        "sample_id": sample["sample_id"],
        "result_path": str(result_path),
        "element_count": normalized["summary"]["element_count"],
    }


def main() -> None:
    args = parse_args()
    load_env_file(args.env_file)
    if not args.prompt_template.exists():
        raise SystemExit(f"Prompt template not found: {args.prompt_template}")

    samples = discover_samples(args.data_root, sample_id=args.sample_id, limit=args.limit)
    api_key = "" if args.dry_run else require_value(args.qwen_api_key, "QWEN_API_KEY")
    base_url = require_value(args.qwen_base_url, "QWEN_BASE_URL", DEFAULT_QWEN_BASE_URL)
    model = require_value(args.model, "QWEN_VISION_MODEL", DEFAULT_MODEL)

    results = []
    failures = 0

    def _run(sample: dict[str, Any]) -> dict[str, Any]:
        try:
            return run_sample(
                sample=sample,
                prompt_template=args.prompt_template,
                output_root=args.output_root,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                timeout=args.timeout,
                dry_run=args.dry_run,
            )
        except Exception as exc:  # noqa: BLE001
            result = {"status": "error", "sample_id": sample.get("sample_id", ""), "error": str(exc)}
            write_json(args.output_root / sample.get("sample_id", "unknown") / "error.json", result)
            return result

    workers = 1 if args.dry_run else args.workers
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_sample = {pool.submit(_run, s): s for s in samples}
        for future in as_completed(future_to_sample):
            result = future.result()
            if result.get("status") == "error":
                failures += 1
                print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
            else:
                print(json.dumps(result, ensure_ascii=False))
            results.append(result)

    summary = {
        "status": "ok" if failures == 0 else "error",
        "sample_count": len(samples),
        "failure_count": failures,
        "output_root": str(args.output_root),
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
