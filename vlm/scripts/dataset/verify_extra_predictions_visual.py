"""Verify strict extra predictions against the source image and bbox crop."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from vlm.scripts._paths import API_ENV_FILE, load_api_env
from vlm.scripts.dataset.element_extraction_schema import extract_json_payload, normalize_bbox
from vlm.scripts.supervise.qwen_vl_image_tool import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    build_messages,
    call_qwen,
)


DEFAULT_ROOT = Path("vlm/data/1-动漫标注结果导出_paired_samples")
DEFAULT_INPUT = DEFAULT_ROOT / "extra_prediction_calibration_holdout30_v1.jsonl"
DEFAULT_OUTPUT = DEFAULT_ROOT / "extra_prediction_visual_verification_holdout30_v1.jsonl"
DEFAULT_CROP_DIR = Path("vlm/tmp/extra_prediction_verifier_crops")

PROMPT_TEMPLATE = """你是动漫角色元素抽取评估员。第一张图是完整原图，第二张图是候选 bbox 的扩边裁剪。
只判断候选元素，不要补充新元素。候选如下：
{prediction}

人工 gold 元素：
{gold_elements}

同一模型对该图的其它预测（已排除当前候选）：
{other_predictions}

请返回且仅返回 JSON object：
{{
  "image_grounded": true/false,
  "description_correct": true/false,
  "duplicate": true/false,
  "conflict": true/false,
  "reason": "一句简短中文证据"
}}
判定规则：
- image_grounded：候选主体在原图或裁剪中清晰可见；
- description_correct：名称、颜色、形状、位置等描述没有实质错误；
- duplicate：候选只是重复同一视觉元素的另一条预测，不是复合 gold 的独立子元素；
- conflict：候选与图像可见属性或 gold 中同一对象的属性明显冲突。
不确定时对应布尔值填 false，并在 reason 说明。"""


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_number}: expected a JSON object")
        rows.append(payload)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    temporary.replace(path)


def row_key(row: dict[str, Any]) -> tuple[str, int]:
    return str(row.get("sample_id", "")), int(row.get("strict_extra_index", -1))


def merge_resume_rows(
    source_rows: list[dict[str, Any]], output_path: Path
) -> list[dict[str, Any]]:
    if not output_path.is_file():
        return source_rows
    previous = {row_key(row): row for row in read_jsonl(output_path)}
    merged: list[dict[str, Any]] = []
    for source in source_rows:
        old = previous.get(row_key(source), {})
        if isinstance(old.get("visual_verifier"), dict):
            source = {**source, "visual_verifier": old["visual_verifier"]}
        merged.append(source)
    return merged


def make_bbox_crop(
    image_path: Path,
    bbox: Any,
    output_path: Path,
    *,
    padding_ratio: float,
) -> list[int]:
    normalized = normalize_bbox(bbox)
    if normalized is None:
        raise ValueError(f"invalid prediction bbox: {bbox}")
    with Image.open(image_path) as image:
        width, height = image.size
        x1, y1, x2, y2 = normalized
        padding_x = max(16.0, (x2 - x1) * padding_ratio)
        padding_y = max(16.0, (y2 - y1) * padding_ratio)
        crop_box = [
            max(0, int(x1 - padding_x)),
            max(0, int(y1 - padding_y)),
            min(width, int(x2 + padding_x + 0.999)),
            min(height, int(y2 + padding_y + 0.999)),
        ]
        if crop_box[2] <= crop_box[0] or crop_box[3] <= crop_box[1]:
            raise ValueError(f"bbox lies outside image: {bbox} vs {width}x{height}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.crop(tuple(crop_box)).save(output_path, format="PNG")
    return crop_box


def parse_verdict(raw_text: str) -> dict[str, Any]:
    payload = extract_json_payload(raw_text)
    if not isinstance(payload, dict):
        raise ValueError("visual verifier response must be a JSON object")
    required = ("image_grounded", "description_correct", "duplicate", "conflict")
    for field in required:
        if type(payload.get(field)) is not bool:
            raise ValueError(f"visual verifier field {field} must be boolean")
    reason = str(payload.get("reason", "")).strip()
    image_grounded = payload["image_grounded"]
    description_correct = payload["description_correct"]
    duplicate = payload["duplicate"]
    conflict = payload["conflict"]
    return {
        "image_grounded": image_grounded,
        "description_correct": description_correct,
        "duplicate": duplicate,
        "conflict": conflict,
        "accepted_extra": image_grounded and description_correct and not duplicate and not conflict,
        "reason": reason,
    }


def build_prompt(row: dict[str, Any]) -> str:
    return PROMPT_TEMPLATE.format(
        prediction=json.dumps(row.get("prediction", {}), ensure_ascii=False),
        gold_elements=json.dumps(row.get("gold_elements", []), ensure_ascii=False),
        other_predictions=json.dumps(row.get("other_predictions", row.get("all_predictions", [])), ensure_ascii=False),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Visually verify unmatched element predictions with Qwen-VL.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--paired-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--crop-dir", type=Path, default=DEFAULT_CROP_DIR)
    parser.add_argument("--env-file", type=Path, default=API_ENV_FILE)
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--limit", type=int, default=10, help="Maximum API calls; 0 means all pending rows.")
    parser.add_argument("--padding-ratio", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=500)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.limit < 0:
        raise SystemExit("--limit cannot be negative")
    if args.padding_ratio < 0:
        raise SystemExit("--padding-ratio cannot be negative")
    load_api_env(args.env_file)
    api_key = os.environ.get("QWEN_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(f"QWEN_API_KEY is required in {args.env_file}")
    base_url = args.base_url.strip() or os.environ.get("QWEN_BASE_URL", "").strip() or DEFAULT_BASE_URL
    model = args.model.strip() or os.environ.get("QWEN_VISION_MODEL", "").strip() or DEFAULT_MODEL

    rows = read_jsonl(args.input)
    if not args.no_resume:
        rows = merge_resume_rows(rows, args.output)
    paired_root = args.paired_root.resolve()
    completed_calls = 0
    for row in rows:
        existing = row.get("visual_verifier")
        if isinstance(existing, dict) and existing.get("status") == "ok":
            continue
        if args.limit and completed_calls >= args.limit:
            break
        completed_calls += 1
        sample_id, extra_index = row_key(row)
        image_path = paired_root / str(row.get("source_image", ""))
        crop_path = args.crop_dir / sample_id / f"extra_{extra_index:03d}.png"
        try:
            crop_box = make_bbox_crop(
                image_path,
                row.get("prediction", {}).get("bbox"),
                crop_path,
                padding_ratio=args.padding_ratio,
            )
            messages = build_messages(build_prompt(row), [image_path, crop_path], want_json=False)
            raw_text = call_qwen(
                api_key=api_key,
                base_url=base_url,
                model=model,
                messages=messages,
                max_tokens=args.max_tokens,
                temperature=0.0,
                timeout=args.timeout,
                want_json=True,
            )
            verdict = parse_verdict(raw_text)
            row["visual_verifier"] = {
                "status": "ok",
                "model": model,
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "crop_box": crop_box,
                **verdict,
            }
        except Exception as exc:
            row["visual_verifier"] = {
                "status": "error",
                "model": model,
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "error": f"{type(exc).__name__}: {exc}",
            }
        write_jsonl(args.output, rows)

    ok_count = sum(
        1 for row in rows if isinstance(row.get("visual_verifier"), dict) and row["visual_verifier"].get("status") == "ok"
    )
    print(json.dumps({"output": str(args.output), "api_calls": completed_calls, "verified_ok": ok_count}, ensure_ascii=False))


if __name__ == "__main__":
    main()
