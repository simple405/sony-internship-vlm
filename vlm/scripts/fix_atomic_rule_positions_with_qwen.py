"""Audit and fix atomic_rules *_position values with Qwen VL.

The script sends only samples that already contain position rules to Qwen VL.
Qwen sees the source image plus the position-rule subset, then returns corrected
values using the annotator/viewer left-right perspective.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from vlm.scripts._paths import API_ENV_FILE, load_api_env

DEFAULT_ROOT = Path("vlm/data/safebooru_2d")
DEFAULT_ATOMIC_ROOT = DEFAULT_ROOT / "atomic_rules"
DEFAULT_MANIFEST = DEFAULT_ROOT / "manifest.csv"
DEFAULT_REPORT_DIR = DEFAULT_ROOT / "reports" / "position_viewpoint_fix"
DEFAULT_MODEL = "qwen3-vl-plus"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
SUPPORTED_SUFFIXES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fix *_position atomic rules with Qwen VL.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--atomic-root", type=Path, default=DEFAULT_ATOMIC_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--env-file", type=Path, default=API_ENV_FILE)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0, help="Maximum samples to process; 0 means all.")
    parser.add_argument("--apply", action="store_true", help="Rewrite atomic_rules.json values. Default is audit only.")
    parser.add_argument(
        "--only-left-right",
        action="store_true",
        help="Only send samples whose *_position value currently contains left or right.",
    )
    parser.add_argument(
        "--min-age-seconds",
        type=int,
        default=120,
        help="Skip atomic_rules files modified more recently than this to avoid racing active extraction.",
    )
    return parser.parse_args()


def media_data_url(path: Path) -> str:
    mime = SUPPORTED_SUFFIXES.get(path.suffix.lower())
    if not mime:
        raise ValueError(f"Unsupported image suffix: {path}")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def parse_json_object(text: str) -> dict[str, Any]:
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


def read_manifest(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {str(row["post_id"]): row.get("image_path", "") for row in csv.DictReader(handle) if row.get("post_id")}


def atomic_files(root: Path, min_age_seconds: int) -> list[Path]:
    now = time.time()
    paths = [
        path
        for path in root.rglob("*.json")
        if path.name == "atomic_rules.json" or path.name.endswith("_atomic_rules.json")
    ]
    return sorted(path for path in paths if now - path.stat().st_mtime >= min_age_seconds)


def sample_id_for(path: Path, data: dict[str, Any]) -> str:
    return str(data.get("code") or data.get("sample_id") or path.parent.name)


def resolve_image_path(root: Path, sample_id: str, data: dict[str, Any], manifest_paths: dict[str, str], atomic_path: Path) -> Path | None:
    candidates: list[Path] = []
    for raw in (data.get("source_image"), manifest_paths.get(sample_id)):
        if raw:
            path = Path(str(raw))
            candidates.append(path if path.is_absolute() else Path.cwd() / path)
    for suffix in IMAGE_SUFFIXES:
        candidates.append(atomic_path.parent / f"{sample_id}_original{suffix}")
        candidates.append(root / "image" / f"{sample_id}{suffix}")
    image_dir = root / "image"
    if image_dir.exists():
        candidates.extend(sorted(path for path in image_dir.iterdir() if path.is_file() and path.name.startswith(f"{sample_id}_")))
    for candidate in candidates:
        if candidate.exists() and candidate.suffix.lower() in IMAGE_SUFFIXES:
            return candidate
    return None


def position_rules(data: dict[str, Any], *, only_left_right: bool) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    position_index = 0
    for atomic_index, rule in enumerate(data.get("atomic_rules", [])):
        if not isinstance(rule, dict):
            continue
        rule_id = str(rule.get("id", ""))
        value = rule.get("value", "")
        if not rule_id.lower().endswith("_position"):
            continue
        text_value = str(value)
        if only_left_right and not re.search(r"left|right", text_value, flags=re.IGNORECASE):
            continue
        rules.append({"position_index": position_index, "atomic_index": atomic_index, "id": rule_id, "value": text_value})
        position_index += 1
    return rules


def build_prompt(sample_id: str, rules: list[dict[str, Any]]) -> str:
    return (
        "你是动漫角色数据标注质检员。请只检查输入 atomic_rules 中 *_position 规则的 value 是否使用标注员/观察者视角。\n"
        "定义：图片左侧是 left，图片右侧是 right；不要使用角色自身的左右。\n"
        "只依据图片中清晰可见内容判断；无法确认时保持原 value 不变。\n"
        "不要新增、删除或重命名 rule_id；只允许修正 value。\n"
        "返回时必须保留每条输入规则的 position_index，用它来区分重复 rule_id。\n"
        "如果 value 不含 left/right 且语义已经清楚，例如 on_head、front、back、center、side，可以保持不变。\n"
        "返回严格 JSON，格式为：\n"
        "{\"updates\":[{\"position_index\":0,\"id\":\"rule_id\",\"old_value\":\"old\",\"corrected_value\":\"new\",\"changed\":false}]}\n\n"
        f"sample_id: {sample_id}\n"
        "position_rules:\n"
        f"{json.dumps(rules, ensure_ascii=False, indent=2)}"
    )


def call_qwen(
    api_key: str,
    base_url: str,
    model: str,
    image_path: Path,
    prompt: str,
    timeout: int,
    max_retries: int,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "你只能输出严格有效的 JSON，不要输出解释、Markdown 或思维链。"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": media_data_url(image_path)}},
                ],
            },
        ],
    }
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            return parse_json_object(str(response.json()["choices"][0]["message"]["content"]))
        except (requests.RequestException, KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt >= max_retries:
                break
            time.sleep(min(20, 2**attempt))
    raise RuntimeError(f"Qwen position audit failed after retries: {last_error}")


def apply_updates(data: dict[str, Any], rules: list[dict[str, Any]], updates: list[dict[str, Any]]) -> list[dict[str, str]]:
    by_position = {
        int(item["position_index"]): item
        for item in updates
        if isinstance(item, dict) and str(item.get("position_index", "")).isdigit()
    }
    changes: list[dict[str, str]] = []
    for fallback_index, rule_ref in enumerate(rules):
        update = by_position.get(int(rule_ref["position_index"]))
        if update is None and fallback_index < len(updates) and isinstance(updates[fallback_index], dict):
            update = updates[fallback_index]
        if update is None:
            continue
        atomic_index = int(rule_ref["atomic_index"])
        atomic_rules = data.get("atomic_rules", [])
        if atomic_index >= len(atomic_rules) or not isinstance(atomic_rules[atomic_index], dict):
            continue
        rule = atomic_rules[atomic_index]
        rule_id = str(rule.get("id", ""))
        old_value = str(rule.get("value", ""))
        if str(update.get("id", rule_id)) != rule_id or str(update.get("old_value", old_value)) != old_value:
            continue
        corrected = str(update.get("corrected_value", old_value)).strip()
        if corrected and corrected != old_value:
            rule["value"] = corrected
            changes.append({"id": rule_id, "old_value": old_value, "corrected_value": corrected})
    return changes


def main() -> None:
    args = parse_args()
    load_api_env(args.env_file)
    api_key = args.api_key or os.environ.get("QWEN_API_KEY", "")
    base_url = args.base_url or os.environ.get("QWEN_BASE_URL", DEFAULT_BASE_URL)
    if not api_key:
        raise SystemExit("QWEN_API_KEY is required")

    manifest_paths = read_manifest(args.manifest)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    jsonl_path = args.report_dir / f"position_viewpoint_fix_{timestamp}.jsonl"

    candidates: list[tuple[Path, dict[str, Any], str, Path, list[dict[str, str]]]] = []
    for path in atomic_files(args.atomic_root, args.min_age_seconds):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        rules = position_rules(data, only_left_right=args.only_left_right)
        if not rules:
            continue
        sample_id = sample_id_for(path, data)
        image_path = resolve_image_path(args.root, sample_id, data, manifest_paths, path)
        if image_path is None:
            continue
        candidates.append((path, data, sample_id, image_path, rules))

    if args.limit > 0:
        candidates = candidates[: args.limit]

    processed = changed_samples = changed_rules = errors = 0
    with jsonl_path.open("w", encoding="utf-8") as report:
        for path, data, sample_id, image_path, rules in candidates:
            record: dict[str, Any] = {
                "sample_id": sample_id,
                "atomic_path": str(path),
                "image_path": str(image_path),
                "rule_count": len(rules),
                "apply": args.apply,
            }
            try:
                response = call_qwen(
                    api_key,
                    base_url,
                    args.model,
                    image_path,
                    build_prompt(sample_id, rules),
                    args.timeout,
                    args.max_retries,
                )
                updates = response.get("updates", [])
                if not isinstance(updates, list):
                    raise ValueError("Qwen response updates must be a list")
                changes = apply_updates(data, rules, updates)
                if args.apply and changes:
                    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                record.update({"status": "ok", "updates": updates, "changes": changes})
                processed += 1
                if changes:
                    changed_samples += 1
                    changed_rules += len(changes)
            except Exception as exc:  # noqa: BLE001
                errors += 1
                record.update({"status": "error", "error_type": type(exc).__name__, "error": str(exc)})
            report.write(json.dumps(record, ensure_ascii=False) + "\n")
            report.flush()
            print(json.dumps(record, ensure_ascii=False), flush=True)

    summary = {
        "status": "ok" if errors == 0 else "error",
        "apply": args.apply,
        "candidate_samples": len(candidates),
        "processed": processed,
        "changed_samples": changed_samples,
        "changed_rules": changed_rules,
        "errors": errors,
        "report": str(jsonl_path),
    }
    summary_path = args.report_dir / f"position_viewpoint_fix_summary_{timestamp}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
