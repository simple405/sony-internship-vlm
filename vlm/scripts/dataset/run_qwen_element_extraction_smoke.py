"""Run a small Qwen-VL element-extraction baseline on paired gold samples.

The script deliberately writes every artifact into the corresponding sample
folder instead of a detached results tree.  The human gold file is never
modified; predicted elements, raw model text, a redacted request preview, and
the deterministic evaluation are separate sibling files.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from PIL import Image

from vlm.scripts._paths import API_ENV_FILE, load_api_env
from vlm.scripts.dataset.element_extraction_schema import (
    ATOMIC_RULES_SCHEMA,
    ELEMENTS_SCHEMA,
    OUTPUT_SCHEMAS,
    convert_prediction_payload,
    normalize_model_response,
    scale_prediction_bboxes,
)
from vlm.scripts.dataset.evaluate_element_extraction_predictions import (
    EVALUATION_FILE,
    PREDICTION_FILE,
    evaluate_sample_dir,
    write_json,
)

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
RAW_RESPONSE_FILE = "qwen_element_prediction_raw.txt"
REQUEST_FILE = "qwen_element_prediction_request_redacted.json"
SUMMARY_FILE = "qwen_element_smoke_summary.json"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_ARTIFACT_PREFIX = Path(PREDICTION_FILE).stem
DEFAULT_PROMPT_VERSION = "paired_gold_bbox_smoke.v4"
DEFAULT_PROMPT = """你是动漫角色元素抽取器。只根据图中清晰可见内容，抽取可用于人工 gold 标注对齐的角色元素。

目标不是穷举物体，而是输出少量“带属性的核心身份元素”。没有固定最低数量；通常 4-10 个，复杂角色可更多，简单角色可更少。

必须遵守：
1. element 必须是具体中文短语，尽量包含颜色/图案/形态 + 物品类型，例如“深棕色短发”“白色衬衫与红色领结”“绿色带橙色条纹的手套”“蓝色绑带凉鞋”。
2. 禁止使用泛称作为 element：不要写“发型”“眼睛”“服装”“外套”“裤子”“鞋子”“手势”“配饰”。若看不清关键属性就省略。
3. 颜色按大色系写，不要卡色号；橙黄/黄橙可写黄色或橙色，金色/黄色按同类，深蓝/黑/深灰蓝在暗部可保守表达。
4. description 用一句中文描述可见事实，并复述 element 的关键颜色、形态和位置；不要写推测、风格评价或背景信息。
5. 复杂服装按人工标注常见层次拆分：外套、衬衫、马甲/背心、领带/领结、胸花/胸针、围裙、披风、护甲分别提取；不要把普通小装饰单独提取。
6. 鞋、袜、手套、绑带凉鞋：如果左右两侧在图中分离、bbox 可分开，输出左右两条，即使名字相同；不要额外再输出“一双”总项。
7. 非人类/兽化角色按大特征合并：身体主体+特殊眼睛可合并；同类端点可合并；不要把普通鼻子、嘴唇、眼白、眉毛单独提取。
8. 手持物、明显姿势、手势、表情只有在非常清晰且有角色识别意义时提取，例如“手持白色餐巾”“双手交叠于胸前”“右眼与表情”。
9. 不提取：背景、文字、水印、普通眉毛/鼻子/嘴、普通鞋、普通裤子、普通领口、纽扣、袖口、褶皱、高光、看不清的小装饰。
10. bbox 使用原图像素坐标 [x1,y1,x2,y2]，框住该元素可见区域；左右分开输出时分别框左右区域。

只返回 JSON 对象，严格使用：
{"elements":[{"element":"具体中文元素名","description":"一句中文可见事实描述","bbox":[0,0,0,0]}]}"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a bounded Qwen element-extraction smoke test on paired samples.")
    parser.add_argument("--paired-root", type=Path, default=Path("vlm/data/1-动漫标注结果导出_paired_samples"))
    parser.add_argument("--split-file", type=Path, default=Path("vlm/data/element_extraction_sft_export/test.jsonl"))
    parser.add_argument("--sample-id", action="append", default=[], help="May be passed more than once; overrides --split-file.")
    parser.add_argument("--offset", type=int, default=0, help="Skip this many selected records before applying --limit.")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--env-file", type=Path, default=API_ENV_FILE)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--max-tokens", type=int, default=1800)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--prompt-file", type=Path, help="Read the extraction prompt from a UTF-8 text file; overrides --prompt.")
    parser.add_argument("--prompt-version", default=DEFAULT_PROMPT_VERSION)
    parser.add_argument(
        "--output-schema",
        choices=OUTPUT_SCHEMAS,
        default=ELEMENTS_SCHEMA,
        help="Normalized prediction schema. atomic_rules.v1 writes code + atomic_rules with id/value/bbox.",
    )
    parser.add_argument(
        "--response-schema",
        choices=OUTPUT_SCHEMAS,
        default=None,
        help="Schema requested from the model. Defaults to --output-schema; may differ for deterministic conversion.",
    )
    parser.add_argument(
        "--bbox-mode",
        choices=("pixel", "normalized_1000"),
        default="pixel",
        help="Coordinate convention returned by the model; qwen3-vl-plus commonly uses normalized_1000.",
    )
    parser.add_argument(
        "--artifact-prefix",
        default=DEFAULT_ARTIFACT_PREFIX,
        help="Prediction artifact stem. Example: qwen_element_prediction_v2 writes qwen_element_prediction_v2.json.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Re-run samples that already have a prediction JSON.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def resolve_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        if not args.prompt_file.exists():
            raise SystemExit(f"prompt file not found: {args.prompt_file}")
        prompt = args.prompt_file.read_text(encoding="utf-8-sig").strip()
    else:
        prompt = str(args.prompt).strip()
    if not prompt:
        raise SystemExit("prompt is empty")
    return prompt


def artifact_files(prefix: str) -> dict[str, str]:
    stem = prefix.strip()
    if stem.endswith(".json"):
        stem = stem[:-5]
    if not stem or any(separator in stem for separator in ("/", "\\")) or stem in {".", ".."}:
        raise SystemExit(f"invalid --artifact-prefix: {prefix!r}")
    evaluation_stem = stem.replace("_prediction", "_evaluation", 1) if "_prediction" in stem else f"{stem}_evaluation"
    summary_stem = stem.replace("_prediction", "_smoke_summary", 1) if "_prediction" in stem else f"{stem}_smoke_summary"
    return {
        "prediction": f"{stem}.json",
        "raw": f"{stem}_raw.txt",
        "request": f"{stem}_request_redacted.json",
        "evaluation": f"{evaluation_stem}.json",
        "summary": f"{summary_stem}.json",
    }


def image_mime(path: Path) -> str:
    return {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}[path.suffix.lower()]


def image_data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{image_mime(path)};base64,{encoded}"


def requested_ids(args: argparse.Namespace) -> list[str]:
    if args.sample_id:
        selected = args.sample_id[args.offset :]
        return selected[: args.limit] if args.limit > 0 else selected
    if not args.split_file.exists():
        raise SystemExit(f"split file not found: {args.split_file}")
    ids = []
    for line_number, line in enumerate(args.split_file.read_text(encoding="utf-8-sig").splitlines(), start=1):
        try:
            sample_id = str(json.loads(line)["id"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise SystemExit(f"invalid split record {args.split_file}:{line_number}: {exc}") from exc
        ids.append(sample_id)
    selected = ids[args.offset :]
    return selected[: args.limit] if args.limit > 0 else selected


def sample_paths(paired_root: Path, sample_id: str) -> tuple[Path, Path]:
    sample_dir = paired_root / sample_id
    if not sample_dir.is_dir():
        raise FileNotFoundError(f"sample folder not found: {sample_dir}")
    images = [path for suffix in IMAGE_SUFFIXES for path in sample_dir.glob(f"*{suffix}")]
    if len(images) != 1:
        raise ValueError(f"{sample_dir}: expected exactly one source image, found {len(images)}")
    return sample_dir, images[0]


def call_qwen(*, api_key: str, base_url: str, model: str, image_path: Path, prompt: str, temperature: float, max_tokens: int, timeout: int) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "只输出严格 JSON，不要输出思维过程、Markdown 或解释。"},
            {"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": image_data_url(image_path)}}]},
        ],
    }
    response = requests.post(
        base_url.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        data=json.dumps(payload, ensure_ascii=False),
        timeout=timeout,
    )
    response.raise_for_status()
    body = response.json()
    try:
        return str(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Qwen response omitted choices[0].message.content") from exc


def process_sample(sample_id: str, *, args: argparse.Namespace, paired_root: Path, api_key: str, base_url: str, model: str) -> dict[str, Any]:
    sample_dir, image_path = sample_paths(paired_root, sample_id)
    artifact_names = args.artifact_files
    prediction_path = sample_dir / artifact_names["prediction"]
    if prediction_path.exists() and not args.overwrite:
        evaluation = evaluate_sample_dir(sample_dir, prediction_file=artifact_names["prediction"])
        write_json(sample_dir / artifact_names["evaluation"], evaluation)
        return {"sample_id": sample_id, "status": "skipped_existing", "evaluation": evaluation}

    request_preview = {
        "model": model,
        "base_url": base_url,
        "source_image": image_path.name,
        "prompt": args.prompt,
        "prompt_file": str(args.prompt_file) if args.prompt_file else None,
        "prompt_version": args.prompt_version,
        "output_schema": args.output_schema,
        "response_schema": args.response_schema,
        "bbox_mode": args.bbox_mode,
        "artifact_prefix": args.artifact_prefix,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "api_key": "redacted",
    }
    write_json(sample_dir / artifact_names["request"], request_preview)
    if args.dry_run:
        return {"sample_id": sample_id, "status": "dry_run"}

    started = time.monotonic()
    raw_text = call_qwen(
        api_key=api_key, base_url=base_url, model=model, image_path=image_path, prompt=args.prompt,
        temperature=args.temperature, max_tokens=args.max_tokens, timeout=args.timeout,
    )
    (sample_dir / artifact_names["raw"]).write_text(raw_text, encoding="utf-8")
    response_payload = normalize_model_response(raw_text, output_schema=args.response_schema, code=sample_id)
    with Image.open(image_path) as image:
        image_width, image_height = image.size
    scale_prediction_bboxes(response_payload, width=image_width, height=image_height, mode=args.bbox_mode)
    normalized = convert_prediction_payload(response_payload, output_schema=args.output_schema, code=sample_id)
    item_key = "atomic_rules" if args.output_schema == ATOMIC_RULES_SCHEMA else "elements"
    prediction = {
        "schema_version": (
            "element_extraction_atomic_rules.v1"
            if args.output_schema == ATOMIC_RULES_SCHEMA
            else "element_extraction_prediction.v1"
        ),
        **normalized,
        "sample_id": sample_id,
        "source_image": image_path.name,
        "metadata": {
            "model": model,
            "base_url": base_url,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "prompt_version": args.prompt_version,
            "output_schema": args.output_schema,
            "response_schema": args.response_schema,
            "bbox_mode": args.bbox_mode,
            "prompt_file": str(args.prompt_file) if args.prompt_file else None,
            "artifact_prefix": args.artifact_prefix,
        },
    }
    write_json(prediction_path, prediction)
    evaluation = evaluate_sample_dir(sample_dir, prediction_file=artifact_names["prediction"])
    write_json(sample_dir / artifact_names["evaluation"], evaluation)
    return {"sample_id": sample_id, "status": "ok", "element_count": len(normalized[item_key]), "evaluation": evaluation}


def main() -> None:
    args = parse_args()
    if args.offset < 0 or args.limit < 0 or args.workers < 1:
        raise SystemExit("--offset/--limit must be non-negative and --workers must be at least 1")
    args.prompt = resolve_prompt(args)
    args.response_schema = args.response_schema or args.output_schema
    args.artifact_files = artifact_files(args.artifact_prefix)
    load_api_env(args.env_file)
    base_url = args.base_url.strip() or os.environ.get("QWEN_BASE_URL", "").strip() or DEFAULT_BASE_URL
    model = args.model.strip() or os.environ.get("QWEN_VISION_MODEL", "").strip()
    api_key = os.environ.get("QWEN_API_KEY", "").strip()
    if not model:
        raise SystemExit("QWEN_VISION_MODEL is required in api.env or pass --model")
    if not args.dry_run and not api_key:
        raise SystemExit("QWEN_API_KEY is required in api.env")

    paired_root = args.paired_root.resolve()
    sample_ids = requested_ids(args)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=1 if args.dry_run else args.workers) as pool:
        futures = {pool.submit(process_sample, sample_id, args=args, paired_root=paired_root, api_key=api_key, base_url=base_url, model=model): sample_id for sample_id in sample_ids}
        for future in as_completed(futures):
            sample_id = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001 - retain individual failures for batch resume
                result = {"sample_id": sample_id, "status": "error", "error": str(exc)}
            print(json.dumps(result, ensure_ascii=False))
            results.append(result)

    completed = [result for result in results if result["status"] != "error"]
    evaluated = [result for result in results if result["status"] in {"ok", "skipped_existing"}]
    total_matches = sum(result["evaluation"]["match_count"] for result in evaluated)
    total_gold = sum(result["evaluation"]["gold_element_count"] for result in evaluated)
    total_predictions = sum(result["evaluation"]["prediction_element_count"] for result in evaluated)
    precision = total_matches / total_predictions if total_predictions else 0.0
    recall = total_matches / total_gold if total_gold else 0.0
    summary = {
        "schema_version": "qwen_element_smoke_summary.v1",
        "model": model,
        "prompt_version": args.prompt_version,
        "output_schema": args.output_schema,
        "response_schema": args.response_schema,
        "bbox_mode": args.bbox_mode,
        "prompt_file": str(args.prompt_file) if args.prompt_file else None,
        "artifact_prefix": args.artifact_prefix,
        "sample_count": len(sample_ids),
        "offset": args.offset,
        "success_count": len(completed),
        "evaluation_count": len(evaluated),
        "failure_count": len(results) - len(completed),
        "micro_precision": round(precision, 4),
        "micro_recall": round(recall, 4),
        "micro_f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
        "total_gold_elements": total_gold,
        "total_prediction_elements": total_predictions,
        "total_matches": total_matches,
        "results": sorted(results, key=lambda result: result["sample_id"]),
    }
    write_json(paired_root / args.artifact_files["summary"], summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["failure_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
