#!/usr/bin/env python3
"""Review a local ComfyUI result with the local Ollama Qwen-VL service."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


PROJECT_ROOT = Path("/home/intern/Supervised 2D to 3D")
DEFAULT_SAMPLE_DIR = PROJECT_ROOT / "vlm/data/SN_6期动漫数据标注/char_001"
OUTPUT_ROOT = PROJECT_ROOT / "vlm/experiments/comfyui_output/front_view_local"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare a source image and local ComfyUI result.")
    parser.add_argument("sample_dir", nargs="?", type=Path, default=DEFAULT_SAMPLE_DIR)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen36-vl:latest")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--identity-threshold", type=float, default=0.85)
    parser.add_argument(
        "--generated-image",
        type=Path,
        default=None,
        help="Review a tagged candidate instead of the fixed-path output.",
    )
    parser.add_argument(
        "--review-name",
        default=None,
        help="Optional review JSON filename; defaults beside the candidate.",
    )
    return parser.parse_args()


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.DOTALL | re.IGNORECASE)
    candidate = fenced.group(1) if fenced else stripped
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(candidate[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("Qwen review is not a JSON object")
    return value


def call_local_ollama(
    base_url: str,
    model: str,
    prompt: str,
    image_paths: list[Path],
    timeout: int,
) -> str:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [
                    base64.b64encode(path.read_bytes()).decode("ascii") for path in image_paths
                ],
            }
        ],
        "stream": False,
        "keep_alive": 0,
        "think": False,
        "format": "json",
        "options": {"temperature": 0.0, "num_predict": 2400},
    }
    session = requests.Session()
    session.trust_env = False
    response = session.post(
        base_url.rstrip("/") + "/api/chat",
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    result = response.json()
    try:
        return str(result["message"]["content"])
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"Ollama response is missing message.content: {result}") from exc


def load_sample(
    sample_dir: Path,
    generated_override: Path | None = None,
) -> tuple[str, Path, Path, dict[str, Any]]:
    sample_dir = sample_dir.resolve()
    annotations = sorted(sample_dir.glob("*.json"))
    if len(annotations) != 1:
        raise ValueError(f"Expected exactly one annotation JSON in {sample_dir}")
    annotation_path = annotations[0]
    annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
    sample_id = str(annotation["sample_id"])
    source = sample_dir / str(annotation["source_image"])
    generated = (
        generated_override.resolve()
        if generated_override is not None
        else OUTPUT_ROOT / sample_id / f"{sample_id}_front_view.png"
    )
    for path in (source, generated):
        if not path.is_file():
            raise FileNotFoundError(path)
    return sample_id, source, generated, annotation


def build_review_prompt(annotation: dict[str, Any]) -> str:
    elements = "\n".join(
        f"- {element['name']}: {element['value']}" for element in annotation["elements"]
    )
    return f"""/no_think
你是严格的动漫角色 2D 转 3D 商品监修员。第一张图是唯一参考原图，第二张图是待验收生成图。
只比较可见内容，不得因为提示词声称存在某元素就判定存在，也不得用常识补全不可见细节。

必须逐项检查这些 JSON 标注元素：
{elements}

标注语义澄清："黑色短裙与腰带"中的"腰带"专指腰部两条连续、平行的灰色横向装饰带；
不要求额外出现独立皮带、皮带扣或金属扣具。若待验图准确显示黑色腰裙区域和正好两条平行灰带，
该项应判 preserved，不得仅因灰带与裙腰连成一体而判 changed。
原图衬衫中央门襟两侧可见的细窄白色环状/褶边属于原有结构，不应误判为新增蕾丝或首饰；
仍须依据两张图的可见形态和尺度判断是否对应。

返回且只返回一个 JSON object，结构如下：
{{
  "gates": {{
    "front_view": true,
    "single_subject": true,
    "white_background": true,
    "three_dimensional": true,
    "no_text_watermark": true,
    "no_red_frame": true
  }},
  "elements": [
    {{"name": "必须原样复制标注 name", "status": "preserved|changed|missing", "evidence_cn": "可见证据"}}
  ],
  "identity_match": 0.0,
  "visual_quality": 0.0,
  "summary_cn": "简短结论"
}}

评分规则：identity_match 为 0 到 1；面部、发型、眼色、服装或标志配饰发生明显改变必须扣分。
three_dimensional 只有在生成图呈现明确的立体 PVC/树脂手办造型、实体材质、体积光影时才为 true；近似原图的平面线稿或赛璐璐插画必须为 false。
不得输出 Markdown 代码块或额外说明。"""


def normalize_review(
    raw: dict[str, Any], annotation: dict[str, Any], identity_threshold: float
) -> dict[str, Any]:
    expected_names = [str(element["name"]) for element in annotation["elements"]]
    gates = raw.get("gates")
    if not isinstance(gates, dict):
        gates = {}
    required_gates = [
        "front_view",
        "single_subject",
        "white_background",
        "three_dimensional",
        "no_text_watermark",
        "no_red_frame",
    ]
    normalized_gates = {name: gates.get(name) is True for name in required_gates}

    raw_elements = raw.get("elements")
    if not isinstance(raw_elements, list):
        raw_elements = []
    by_name = {
        str(item.get("name")): item
        for item in raw_elements
        if isinstance(item, dict) and item.get("name") is not None
    }
    normalized_elements = []
    for name in expected_names:
        item = by_name.get(name, {})
        status = str(item.get("status", "missing")).lower()
        if status not in {"preserved", "changed", "missing"}:
            status = "missing"
        normalized_elements.append(
            {
                "name": name,
                "status": status,
                "evidence_cn": str(item.get("evidence_cn", "模型未提供该项的可见证据")),
            }
        )

    try:
        identity_match = min(1.0, max(0.0, float(raw.get("identity_match", 0.0))))
    except (TypeError, ValueError):
        identity_match = 0.0
    try:
        visual_quality = min(1.0, max(0.0, float(raw.get("visual_quality", 0.0))))
    except (TypeError, ValueError):
        visual_quality = 0.0

    all_gates_pass = all(normalized_gates.values())
    all_elements_preserved = all(item["status"] == "preserved" for item in normalized_elements)
    passed = all_gates_pass and all_elements_preserved and identity_match >= identity_threshold
    return {
        "reviewed_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "gates": normalized_gates,
        "elements": normalized_elements,
        "identity_match": identity_match,
        "identity_threshold": identity_threshold,
        "visual_quality": visual_quality,
        "decision": "pass" if passed else "fail",
        "summary_cn": str(raw.get("summary_cn", "")),
        "reviewer": "local_qwen_vl",
        "review_note": "自动评估仅用于 smoke gate，不能替代人工最终批准。",
    }


def main() -> None:
    args = parse_args()
    sample_id, source, generated, annotation = load_sample(
        args.sample_dir,
        args.generated_image,
    )
    prompt = build_review_prompt(annotation)
    if args.generated_image is None:
        output_dir = OUTPUT_ROOT / sample_id
        stem = "qwen_review"
        review_path = output_dir / "review.json"
    else:
        output_dir = generated.parent
        stem = generated.stem
        review_path = output_dir / (
            args.review_name or f"{generated.stem}_review.json"
        )
    raw_path = output_dir / f"{stem}_raw.txt"
    request_path = output_dir / f"{stem}_request.json"

    for proxy_name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(proxy_name, None)
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = "127.0.0.1,localhost"

    atomic_json(
        request_path,
        {
            "base_url": args.base_url,
            "model": args.model,
            "image_paths": [str(source), str(generated)],
            "annotation_path": str(args.sample_dir.resolve() / f"{sample_id}.json"),
            "prompt_chars": len(prompt),
            "note": "Image bytes are local and omitted from this audit preview.",
        },
    )
    text = call_local_ollama(
        args.base_url,
        args.model,
        prompt,
        [source, generated],
        args.timeout,
    )
    atomic_text(raw_path, text.rstrip() + "\n")
    review = normalize_review(extract_json(text), annotation, args.identity_threshold)
    review["model"] = args.model
    review["source_image"] = str(source)
    review["generated_image"] = str(generated)
    atomic_json(review_path, review)
    print(json.dumps(review, ensure_ascii=False, indent=2))
    print(review_path)
    if review["decision"] != "pass":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
