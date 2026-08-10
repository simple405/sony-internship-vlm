"""Run a Qwen-VL reviewer baseline on paired front-view generation samples.

The reviewer reads each RunningHub-generated front-view image and its paired
specification JSON. The original 2D image is retained only as an audit
reference and is never included in the request payload, preview, or model
call. Outputs are written to ``vlm/tmp/paired_front_view_review_v1/``.

Usage:
    python -m vlm.scripts.supervise.run_paired_front_view_review --dry-run --limit 20
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[3]))

from vlm.scripts._paths import SUPERVISION_PROMPTS_DIR, VLM_ROOT, load_api_env
from vlm.scripts.generate.generate_paired_front_view import (
    DEFAULT_OUTPUT_ROOT as PILOT_GENERATION_ROOT,
    read_category_sample_manifest,
)
from vlm.scripts.generate.prompt_renderer import (
    CATEGORY_REQUIREMENTS,
    MERCHANDISE_LABELS,
)
from vlm.scripts.generate.runninghub_client import IMAGE_SUFFIXES
from vlm.scripts._validation import validate_path_component, validate_qwen_base_url
from vlm.scripts.supervise.postprocess_color_family_verdicts import (
    RULE_NAME as COLOR_FAMILY_RULE_NAME,
    extract_color_families,
    is_tolerated_family_set,
)


MAX_PILOT_SAMPLES = 20
DEFAULT_INPUT_ROOT = PILOT_GENERATION_ROOT
DEFAULT_OUTPUT_ROOT = VLM_ROOT / "tmp" / "paired_front_view_review_v1"
DEFAULT_FIVE_CATEGORY_OUTPUT_ROOT = (
    VLM_ROOT / "tmp" / "five_category_supervision_v1" / "review"
)
DEFAULT_PROMPT_FILE = SUPERVISION_PROMPTS_DIR / "paired_front_view_review_cn.txt"
DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_MODEL = "qwen-vl-max"
ALLOWED_RESULTS = {"pass", "partial", "fail", "not_evaluable", "review", "out_of_scope"}
ALLOWED_LOCATIONS = {"head", "body"}
COLOR_ISSUE_ALIASES = {"color", "wrong color", "颜色", "色彩", "色差"}
MICRO_DETAIL_KEYWORDS = [
    "宝石",
    "发夹",
    "发饰",
    "头饰",
    "领饰",
    "领结",
    "蝴蝶结",
    "纽扣",
    "扣",
    "横向装饰带",
    "装饰带",
    "腰带",
    "袖口",
    "折边",
    "边缘",
    "褶皱",
    "花纹",
    "纹路",
    "蕾丝",
    "高光",
    "链条",
    "木棍",
    "细长",
    "前端",
    "尖端",
    "嘴里",
    "叼着",
    "耳环",
    "小巧",
    "精致",
    "标志性配饰",
]


@dataclass(frozen=True)
class ReviewSample:
    """One complete Phase A sample ready for reviewer evaluation.

    Attributes:
        sample_id: Sample identifier and output directory name.
        generated_image_path: RunningHub-generated PVC front-view image.
        gold_path: Paired gold specification JSON.
        original_image_path: Original 2D source image, used only for audit context.
    """

    sample_id: str
    generated_image_path: Path
    gold_path: Path
    original_image_path: Path
    category: str = ""


def _find_generated_image(sample_dir: Path, sample_id: str) -> Path | None:
    """Find a generated front-view image in legacy or category naming."""
    for suffix in IMAGE_SUFFIXES:
        legacy = sample_dir / f"{sample_id}_q_front_view{suffix}"
        if legacy.is_file():
            return legacy
    for suffix in IMAGE_SUFFIXES:
        matches = sorted(sample_dir.glob(f"{sample_id}_*_front_view{suffix}"))
        if matches:
            return matches[0]
    return None


def _discover_sample_dir(sample_dir: Path, category: str) -> ReviewSample | None:
    """Return a review sample when a directory has generated/gold/original files."""
    sample_id = validate_path_component(sample_dir.name, "sample ID")
    generated = _find_generated_image(sample_dir, sample_id)
    gold = sample_dir / f"{sample_id}.json"
    if generated is None or not gold.is_file():
        return None
    original = None
    for suffix in IMAGE_SUFFIXES:
        candidate = sample_dir / f"{sample_id}_original{suffix}"
        if candidate.is_file():
            original = candidate
            break
    if original is None:
        return None
    return ReviewSample(sample_id, generated, gold, original, category=category)


def discover_samples(input_root: Path) -> list[ReviewSample]:
    """Find complete legacy or category-layout sample directories."""
    samples: list[ReviewSample] = []
    if not input_root.is_dir():
        return samples

    for path in sorted(input_root.iterdir(), key=lambda item: item.name):
        if not path.is_dir() or path.name.startswith("_"):
            continue
        if path.name in CATEGORY_REQUIREMENTS:
            for sample_dir in sorted(path.iterdir(), key=lambda item: item.name):
                if sample_dir.is_dir() and not sample_dir.name.startswith("_"):
                    sample = _discover_sample_dir(sample_dir, path.name)
                    if sample is not None:
                        samples.append(sample)
            continue
        sample = _discover_sample_dir(path, "")
        if sample is not None:
            samples.append(sample)
    return sorted(samples, key=lambda item: (item.category, item.sample_id))


def load_gold_elements(gold_path: Path) -> list[dict[str, Any]]:
    """Load and validate the paired gold element list.

    Args:
        gold_path: Path to the sample JSON file.

    Returns:
        The raw ordered list of element dictionaries.

    Raises:
        ValueError: If the JSON root is not a list or contains non-object rows.
    """
    payload = json.loads(gold_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Gold JSON root must be a list: {gold_path}")
    if any(not isinstance(item, dict) for item in payload):
        raise ValueError(f"Gold JSON entries must be objects: {gold_path}")
    return payload


def build_review_prompt(
    template: str,
    gold_elements: list[dict[str, Any]],
    *,
    category: str = "dataset_figurine",
) -> str:
    """Render the frozen prompt with a numbered gold element list.

    Args:
        template: Text containing ``{{GOLD_COUNT}}`` and ``{{GOLD_ELEMENTS}}``.
        gold_elements: Ordered gold element dictionaries.

    Returns:
        Rendered prompt text.
    """
    lines: list[str] = []
    for index, element in enumerate(gold_elements, start=1):
        lines.append(f"{index}. element: {element.get('element', '')}")
        lines.append(f"   description: {element.get('description', '')}")
        micro_hints = extract_micro_detail_hints(element)
        if micro_hints:
            lines.append(f"   micro_detail_hints: {', '.join(micro_hints)}")
    gold_block = "\n".join(lines)
    rendered = template
    if "{{MERCHANDISE_CATEGORY}}" in rendered:
        rendered = rendered.replace(
            "{{MERCHANDISE_CATEGORY}}",
            MERCHANDISE_LABELS.get(category, category),
        )
    if "{{CATEGORY_KEY}}" in rendered:
        rendered = rendered.replace("{{CATEGORY_KEY}}", category)
    if "{{CATEGORY_REQUIREMENTS}}" in rendered:
        rendered = rendered.replace(
            "{{CATEGORY_REQUIREMENTS}}",
            CATEGORY_REQUIREMENTS.get(category, "Review visible identity features for the current merchandise category."),
        )
    return (
        rendered.replace("{{GOLD_COUNT}}", str(len(gold_elements)))
        .replace("{{GOLD_ELEMENTS}}", gold_block)
    )


def resolve_sample_output_dir(
    sample: ReviewSample,
    output_root: Path,
    sample_review_root_name: str = "",
) -> Path:
    """Return the directory for per-sample data artifacts."""
    if sample_review_root_name:
        safe_name = validate_path_component(
            sample_review_root_name,
            "sample review root name",
        )
        return sample.generated_image_path.parent / "_review" / safe_name
    if sample.category:
        return output_root / sample.category / sample.sample_id
    return output_root / sample.sample_id


def resolve_sample_auxiliary_output_dir(
    sample: ReviewSample,
    output_root: Path,
    sample_review_root_name: str = "",
) -> Path:
    """Return the directory for request/prompt artifacts.

    In sample-review mode, keep generated-sample folders readable by writing
    only strongly data-bound files there and moving request previews/prompts
    up into the batch output root.
    """
    if not sample_review_root_name:
        return resolve_sample_output_dir(sample, output_root, "")
    safe_name = validate_path_component(
        sample_review_root_name,
        "sample review root name",
    )
    if sample.category:
        return output_root / "_sample_aux" / safe_name / sample.category / sample.sample_id
    return output_root / "_sample_aux" / safe_name / sample.sample_id


def extract_micro_detail_hints(element: dict[str, Any]) -> list[str]:
    """Extract visible small-detail hints from one gold element.

    The reviewer prompt is image-only; tiny accessories are often present but
    Qwen misses them unless the local region is explicitly named. These hints
    keep the request grounded in the gold JSON without adding the source image.
    """
    text = f"{element.get('element', '')} {element.get('description', '')}"
    hints: list[str] = []
    for keyword in MICRO_DETAIL_KEYWORDS:
        if keyword in text and keyword not in hints:
            hints.append(keyword)
    return hints


def _sha256(path: Path) -> str:
    """Return a file SHA-256 digest."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request_preview(
    sample: ReviewSample,
    prompt_file: Path,
    prompt_text: str,
    gold_element_count: int,
    output_dir: Path,
) -> dict[str, Any]:
    """Build a redacted request preview that contains only the generated image.

    Args:
        sample: Review sample. Its original image is deliberately not accessed.
        prompt_file: Frozen prompt template path.
        prompt_text: Fully rendered prompt.
        gold_element_count: Number of gold elements rendered into the prompt.
        output_dir: Per-sample output directory.

    Returns:
        JSON-serializable request metadata with one generated-image reference.
    """
    return {
        "schema_version": "paired_front_view_review_request.v1",
        "sample_id": sample.sample_id,
        "category": sample.category,
        "generated_image_sha256": _sha256(sample.generated_image_path),
        "prompt_file": str(prompt_file),
        "prompt_sha256": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
        "gold_element_count": gold_element_count,
        "source_image_used": False,
        "request": {
            "prompt": prompt_text,
            "image_path": str(sample.generated_image_path),
            "image_count": 1,
        },
        "output_dir": str(output_dir),
    }


def media_type(path: Path) -> str:
    """Return an image MIME type based on the file suffix."""
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def encode_image_data_url(path: Path) -> str:
    """Encode an image as a base64 data URL for an OpenAI-style request."""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type(path)};base64,{encoded}"


def build_messages(prompt_text: str, image_path: Path) -> list[dict[str, Any]]:
    """Build a single-user-turn message with exactly one text and one image."""
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_text},
                {
                    "type": "image_url",
                    "image_url": {"url": encode_image_data_url(image_path)},
                },
            ],
        }
    ]


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract a JSON object from bare, fenced, or prefixed model output.

    Args:
        text: Raw model response text.

    Returns:
        Parsed JSON object.

    Raises:
        json.JSONDecodeError: If no valid JSON object is found.
        TypeError: If the parsed JSON root is not an object.
    """
    stripped = str(text).strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline >= 0:
            stripped = stripped[first_newline + 1 :]
        else:
            stripped = stripped[3:]
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3].rstrip()

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as original_error:
        decoder = json.JSONDecoder()
        for start, character in enumerate(stripped):
            if character != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(stripped[start:])
                break
            except json.JSONDecodeError:
                continue
        else:
            raise original_error

    if not isinstance(parsed, dict):
        raise TypeError("Model response JSON root must be an object")
    return parsed


def call_qwen_review(
    *,
    api_key: str,
    base_url: str,
    model: str,
    image_path: Path,
    prompt_text: str,
    timeout: int,
    max_retries: int = 2,
) -> str:
    """Call the Qwen-VL OpenAI-compatible endpoint and return raw text."""
    base_url = validate_qwen_base_url(base_url)
    payload: dict[str, Any] = {
        "model": model,
        "messages": build_messages(prompt_text, image_path),
        "temperature": 0.0,
        "max_tokens": 4000,
    }
    payload["response_format"] = {"type": "json_object"}
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                base_url.rstrip("/") + "/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                data=json.dumps(payload, ensure_ascii=False),
                timeout=timeout,
                allow_redirects=False,
            )
            if response.status_code in {400, 401, 403}:
                response.raise_for_status()
            response.raise_for_status()
            result = response.json()
            break
        except requests.RequestException as exc:
            last_error = exc
            status_code = getattr(getattr(exc, "response", None), "status_code", 0)
            retryable = status_code == 429 or status_code >= 500 or status_code == 0
            if not retryable or attempt >= max_retries:
                raise
            time.sleep(min(30.0, 2.0**attempt))
    else:
        raise RuntimeError(f"Qwen request failed after retries: {last_error}")
    try:
        message = result["choices"][0]["message"]
        content = message.get("content", "")
        if isinstance(content, list):
            content = "".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict)
            )
        if str(content).strip():
            return str(content)
        reasoning = message.get("reasoning", "")
        if str(reasoning).strip():
            return str(reasoning)
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            f"Qwen response missing choices[0].message.content: {result}"
        ) from exc
    raise RuntimeError(f"Qwen response contained no text content: {result}")


def _confidence(value: Any) -> float:
    """Normalize a model confidence value to a finite float in [0, 1]."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(result):
        return 0.0
    return max(0.0, min(1.0, result))


def validate_and_align_rules(
    raw_rules: Any,
    gold_elements: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Force model rules to match gold count/order and allowed result values.

    Args:
        raw_rules: Model ``rules`` value, possibly malformed.
        gold_elements: Ordered gold element specifications.

    Returns:
        Aligned rules and QC issue strings. The aligned list always has one
        entry per gold element; unrecoverable entries become ``review``.
    """
    issues: list[str] = []
    if not isinstance(raw_rules, list):
        issues.append("rules_not_a_list")
        raw_rules = []
    if len(raw_rules) > len(gold_elements):
        issues.append("extra_rule_entries_beyond_gold_count")

    aligned: list[dict[str, Any]] = []
    for index, gold in enumerate(gold_elements, start=1):
        candidate = raw_rules[index - 1] if index - 1 < len(raw_rules) else None
        rule = dict(candidate) if isinstance(candidate, dict) else {}
        if candidate is None:
            issues.append(f"missing_rule_index_{index}")
        rule["rule_index"] = index
        rule["element"] = gold.get("element", "")
        result = str(rule.get("result", "")).strip()
        if result not in ALLOWED_RESULTS:
            issues.append(f"invalid_result_at_index_{index}:{result}")
            rule["result"] = "review"
        location = str(rule.get("location", "")).strip().lower()
        if location:
            if location not in ALLOWED_LOCATIONS:
                issues.append(f"invalid_location_at_index_{index}:{location}")
                rule["location"] = ""
            else:
                rule["location"] = location
        bbox = rule.get("evidence_bbox")
        if bbox is not None:
            valid_bbox = isinstance(bbox, list) and len(bbox) == 4
            if valid_bbox:
                try:
                    valid_bbox = all(math.isfinite(float(value)) for value in bbox)
                except (TypeError, ValueError):
                    valid_bbox = False
            if not valid_bbox:
                issues.append(f"invalid_evidence_bbox_at_index_{index}")
                rule["evidence_bbox"] = None
        rule["confidence"] = _confidence(rule.get("confidence"))
        aligned.append(rule)
    return aligned, issues


def _normalized_issue_types(value: Any) -> list[str]:
    """Return issue types as stripped strings while tolerating model variance."""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    return [part.strip() for part in str(value).replace("，", ",").split(",") if part.strip()]


def _is_color_issue(issue_type: str) -> bool:
    lowered = issue_type.strip().lower()
    return lowered in COLOR_ISSUE_ALIASES or "color" in lowered or "颜色" in lowered


def apply_color_family_tolerance(
    rules: list[dict[str, Any]],
    gold_elements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Downgrade color-only false failures inside tolerated adjacent color families.

    Example: gold says ``紫红色`` while Qwen describes the rendered area as
    ``粉红色``. This is a hue-name boundary, not a hard generation failure, so a
    color-only fail/partial/review becomes pass and is tagged in ``postprocess``.
    Non-color issues such as missing structure are preserved.
    """
    adjusted: list[dict[str, Any]] = []
    for index, rule in enumerate(rules):
        item = dict(rule)
        issue_types = _normalized_issue_types(item.get("issue_types"))
        if not any(_is_color_issue(issue) for issue in issue_types):
            item["issue_types"] = issue_types
            adjusted.append(item)
            continue

        gold = gold_elements[index] if index < len(gold_elements) else {}
        family_text = " ".join(
            str(part)
            for part in (
                gold.get("element", ""),
                gold.get("description", ""),
                item.get("observed_description", ""),
                item.get("reason", ""),
            )
        )
        families = extract_color_families(family_text)
        if not is_tolerated_family_set(families):
            item["issue_types"] = issue_types
            adjusted.append(item)
            continue

        remaining_issues = [issue for issue in issue_types if not _is_color_issue(issue)]
        item["issue_types"] = remaining_issues
        postprocess = dict(item.get("postprocess") or {})
        postprocess["color_family_tolerated"] = True
        postprocess["rule"] = COLOR_FAMILY_RULE_NAME
        postprocess["matched_color_families"] = sorted(families)
        postprocess["original_result"] = item.get("result")
        postprocess["original_issue_types"] = issue_types
        item["postprocess"] = postprocess
        if not remaining_issues and item.get("result") in {"fail", "partial", "review"}:
            item["result"] = "pass"
            item["description_correct"] = True
            reason = str(item.get("reason", "")).strip()
            suffix = (
                f"颜色处于允许的相邻色系边界（{', '.join(sorted(families))}），"
                "按色系容差不计为失败。"
            )
            item["reason"] = f"{reason} {suffix}".strip()
        adjusted.append(item)
    return adjusted


def compute_aggregate_counts(rules: list[dict[str, Any]]) -> dict[str, int]:
    """Count each rule result using the fixed five-value contract."""
    counts = {result: 0 for result in sorted(ALLOWED_RESULTS)}
    for rule in rules:
        result = rule.get("result", "review")
        if result not in counts:
            result = "review"
        counts[result] += 1
    return counts


def compute_overall_decision(rules: list[dict[str, Any]], qc_issues: list[str]) -> str:
    """Derive fail, review, or pass from aligned rule verdicts."""
    scoped_rules = [
        rule for rule in rules if rule.get("result") != "out_of_scope"
    ]
    if any(rule.get("result") == "fail" for rule in scoped_rules):
        return "fail"
    if qc_issues or any(rule.get("result") == "review" for rule in scoped_rules):
        return "review"
    if any(_confidence(rule.get("confidence")) < 0.6 for rule in scoped_rules):
        return "review"
    return "pass"


def _write_json(path: Path, payload: Any) -> None:
    """Write indented UTF-8 JSON, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_review_csv(path: Path, rules: list[dict[str, Any]]) -> None:
    """Write aligned rule verdicts as an Excel-compatible CSV."""
    columns = [
        "rule_index",
        "element",
        "result",
        "location",
        "image_grounded",
        "description_correct",
        "issue_types",
        "observed_description",
        "evidence_bbox",
        "confidence",
        "reason",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for rule in rules:
            row = {column: rule.get(column, "") for column in columns}
            row["issue_types"] = json.dumps(
                rule.get("issue_types", []), ensure_ascii=False
            )
            row["evidence_bbox"] = json.dumps(
                rule.get("evidence_bbox"), ensure_ascii=False
            )
            writer.writerow(row)


def process_one(
    sample: ReviewSample,
    gold_elements: list[dict[str, Any]],
    prompt_file: Path,
    prompt_template: str,
    output_root: Path,
    *,
    dry_run: bool,
    api_key: str = "",
    base_url: str = "",
    model: str = "",
    timeout: int = 180,
    call_fn: Callable[..., str] = call_qwen_review,
    max_retries: int = 2,
    sample_review_root_name: str = "",
    sample_qc_root_name: str = "",
) -> dict[str, Any]:
    """Render, optionally call, validate, and persist one sample review."""
    sample_dir = resolve_sample_output_dir(
        sample,
        output_root,
        sample_review_root_name,
    )
    auxiliary_dir = resolve_sample_auxiliary_output_dir(
        sample,
        output_root,
        sample_review_root_name,
    )
    prompt_text = build_review_prompt(
        prompt_template,
        gold_elements,
        category=sample.category or "dataset_figurine",
    )
    preview = request_preview(
        sample,
        prompt_file,
        prompt_text,
        len(gold_elements),
        sample_dir,
    )
    sample_dir.mkdir(parents=True, exist_ok=True)
    auxiliary_dir.mkdir(parents=True, exist_ok=True)
    _write_json(auxiliary_dir / "request_preview.json", preview)
    (auxiliary_dir / "review_prompt.txt").write_text(prompt_text, encoding="utf-8")

    if dry_run:
        status = {
            "schema_version": "paired_front_view_review_status.v1",
            "sample_id": sample.sample_id,
            "category": sample.category,
            "status": "dry_run",
        }
        _write_json(sample_dir / "status.json", status)
        return status

    started = time.time()
    raw_text = call_fn(
        api_key=api_key,
        base_url=base_url,
        model=model,
        image_path=sample.generated_image_path,
        prompt_text=prompt_text,
        timeout=timeout,
        max_retries=max_retries,
    )
    (sample_dir / "raw_response.txt").write_text(str(raw_text), encoding="utf-8")
    parsed = extract_json_object(raw_text)
    aligned_rules, qc_issues = validate_and_align_rules(
        parsed.get("rules"), gold_elements
    )
    aligned_rules = apply_color_family_tolerance(aligned_rules, gold_elements)
    aggregate_counts = compute_aggregate_counts(aligned_rules)
    overall_decision = compute_overall_decision(aligned_rules, qc_issues)
    raw_extra = parsed.get("extra_elements")
    extra_elements = raw_extra if isinstance(raw_extra, list) else []

    prediction = {
        "schema_version": "paired_front_view_review.v1",
        "sample_id": sample.sample_id,
        "category": sample.category,
        "inputs": {
            "generated_image": str(sample.generated_image_path),
            "gold_json": str(sample.gold_path),
            "source_image_used": False,
        },
        "rules": aligned_rules,
        "extra_elements": extra_elements,
        "aggregate_counts": aggregate_counts,
        "overall_decision": overall_decision,
        "qc_issues": qc_issues,
        "metadata": {
            "model": model,
            "review_prompt_sha256": hashlib.sha256(
                prompt_text.encode("utf-8")
            ).hexdigest(),
            "elapsed_seconds": round(time.time() - started, 2),
        },
    }
    _write_json(sample_dir / "prediction.json", prediction)
    write_review_csv(sample_dir / "qc.csv", aligned_rules)
    if sample_qc_root_name:
        sample_qc = (
            sample.generated_image_path.parent
            / "_review"
            / sample_qc_root_name
            / "qc.csv"
        )
        write_review_csv(sample_qc, aligned_rules)

    status = {
        "schema_version": "paired_front_view_review_status.v1",
        "sample_id": sample.sample_id,
        "category": sample.category,
        "status": "succeeded",
        "overall_decision": overall_decision,
        "aggregate_counts": aggregate_counts,
        "qc_issue_count": len(qc_issues),
    }
    _write_json(sample_dir / "status.json", status)
    return status


def enforce_pilot_scale_guard(
    requested_ids: list[str],
    limit: int,
    max_pilot_samples: int = MAX_PILOT_SAMPLES,
) -> None:
    """Block large implicit runs unless sample IDs were explicitly selected."""
    if not requested_ids and limit > max_pilot_samples:
        raise SystemExit(
            f"--limit must be <= {max_pilot_samples} for this pilot baseline. "
            "Pass --sample-id explicitly to review specific samples beyond the pilot."
        )


def select_review_samples(
    samples: list[ReviewSample],
    requested_ids: list[str],
    limit: int,
) -> list[ReviewSample]:
    """Select explicit IDs in caller order or the first sorted samples."""
    by_id = {sample.sample_id: sample for sample in samples}
    if requested_ids:
        missing = [sample_id for sample_id in requested_ids if sample_id not in by_id]
        if missing:
            raise ValueError(f"Unknown sample_id(s): {', '.join(missing)}")
        return [by_id[sample_id] for sample_id in dict.fromkeys(requested_ids)]
    return samples[:limit] if limit > 0 else samples



def select_review_jobs(
    samples: list[ReviewSample],
    *,
    sample_manifest: Path | None,
    requested_ids: list[str],
    limit: int,
    fallback_category: str,
) -> list[ReviewSample]:
    """Select category-aware review samples from a manifest or CLI options."""
    if sample_manifest is None:
        selected = select_review_samples(samples, requested_ids, limit)
        return [
            sample if sample.category else ReviewSample(
                sample.sample_id,
                sample.generated_image_path,
                sample.gold_path,
                sample.original_image_path,
                category=fallback_category,
            )
            for sample in selected
        ]

    by_key = {(sample.category, sample.sample_id): sample for sample in samples}
    by_id = {sample.sample_id: sample for sample in samples}
    selected: list[ReviewSample] = []
    for row in read_category_sample_manifest(sample_manifest):
        key = (row["category"], row["sample_id"])
        sample = by_key.get(key) or by_id.get(row["sample_id"])
        if sample is None:
            raise ValueError(
                f"Generated sample not found for {row['category']}/{row['sample_id']}"
            )
        if sample.category != row["category"]:
            sample = ReviewSample(
                sample.sample_id,
                sample.generated_image_path,
                sample.gold_path,
                sample.original_image_path,
                category=row["category"],
            )
        selected.append(sample)
    return selected

def build_batch_summary(statuses: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate sample decisions, rule verdicts, and the human-review queue."""
    overall_distribution = {"pass": 0, "fail": 0, "review": 0}
    verdict_distribution = {result: 0 for result in sorted(ALLOWED_RESULTS)}
    fail_or_review_ids: list[str] = []
    parse_failures: list[str] = []

    for status in statuses:
        if status.get("status") == "failed":
            parse_failures.append(str(status["sample_id"]))
            continue
        if status.get("status") != "succeeded":
            continue
        overall = str(status.get("overall_decision", "review"))
        overall_distribution[overall] = overall_distribution.get(overall, 0) + 1
        if overall in {"fail", "review"}:
            fail_or_review_ids.append(str(status["sample_id"]))
        for result, count in (status.get("aggregate_counts") or {}).items():
            verdict_distribution[result] = verdict_distribution.get(result, 0) + int(count)

    return {
        "schema_version": "paired_front_view_review_batch.v1",
        "sample_count": len(statuses),
        "overall_decision_distribution": overall_distribution,
        "verdict_distribution": verdict_distribution,
        "fail_or_review_sample_ids": fail_or_review_ids,
        "parse_failures": parse_failures,
    }


def parse_args() -> argparse.Namespace:
    """Parse reviewer CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Review paired front-view generations against gold JSON with Qwen VL."
    )
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--prompt-file", type=Path, default=DEFAULT_PROMPT_FILE)
    parser.add_argument("--sample-id", action="append", default=[])
    parser.add_argument("--sample-manifest", type=Path, default=None)
    parser.add_argument("--category", default="dataset_figurine", choices=tuple(CATEGORY_REQUIREMENTS))
    parser.add_argument("--sample-qc-root-name", default="")
    parser.add_argument("--limit", type=int, default=MAX_PILOT_SAMPLES)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--model", default="")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument(
        "--sample-review-root-name",
        default="",
        help=(
            "Write per-sample data artifacts under each generated sample's "
            "_review/<name>/ directory; request previews and prompts stay "
            "under --output-root/_sample_aux/<name>/."
        ),
    )
    return parser.parse_args()


def main() -> None:
    """Review selected pilot samples and write per-sample and batch outputs."""
    args = parse_args()
    if args.limit < 0:
        raise SystemExit("--limit must be >= 0")
    if args.workers < 1 or args.workers > 5:
        raise SystemExit("--workers must be between 1 and 5")
    if args.max_retries < 0:
        raise SystemExit("--max-retries must be >= 0")
    if args.sample_manifest is None:
        enforce_pilot_scale_guard(args.sample_id, args.limit)

    all_samples = discover_samples(args.input_root)
    samples = select_review_jobs(
        all_samples,
        sample_manifest=args.sample_manifest,
        requested_ids=args.sample_id,
        limit=args.limit,
        fallback_category=args.category,
    )
    if not samples:
        raise SystemExit("No samples selected")
    if not args.prompt_file.is_file():
        raise SystemExit(f"Prompt template not found: {args.prompt_file}")
    prompt_template = args.prompt_file.read_text(encoding="utf-8-sig").strip()
    if not prompt_template:
        raise SystemExit(f"Prompt template is empty: {args.prompt_file}")

    api_key = ""
    base_url = ""
    model = args.model.strip()
    if not args.dry_run:
        load_api_env()
        api_key = os.environ.get("QWEN_API_KEY", "").strip()
        if not api_key:
            raise SystemExit("QWEN_API_KEY is required in vlm/config/api.env or the environment.")
        base_url = validate_qwen_base_url(
            os.environ.get("QWEN_BASE_URL", "").strip() or DEFAULT_QWEN_BASE_URL
        )
        model = model or os.environ.get("QWEN_VISION_MODEL", "").strip() or DEFAULT_QWEN_MODEL

    args.output_root.mkdir(parents=True, exist_ok=True)
    statuses: list[dict[str, Any]] = []
    status_by_sample: dict[str, dict[str, Any]] = {}

    def _run_sample(sample: ReviewSample) -> dict[str, Any]:
        gold_elements = load_gold_elements(sample.gold_path)
        return process_one(
            sample,
            gold_elements,
            args.prompt_file,
            prompt_template,
            args.output_root,
            dry_run=args.dry_run,
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout=args.timeout,
            max_retries=args.max_retries,
            sample_review_root_name=args.sample_review_root_name,
            sample_qc_root_name=args.sample_qc_root_name,
        )

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_sample = {executor.submit(_run_sample, sample): sample for sample in samples}
        for future in as_completed(future_to_sample):
            sample = future_to_sample[future]
            try:
                status = future.result()
            except Exception as exc:
                status = {
                    "schema_version": "paired_front_view_review_status.v1",
                    "sample_id": sample.sample_id,
                    "category": sample.category,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                sample_dir = resolve_sample_output_dir(
                    sample,
                    args.output_root,
                    args.sample_review_root_name,
                )
                _write_json(sample_dir / "status.json", status)
            status_by_sample[f"{sample.category}/{sample.sample_id}"] = status
            print(json.dumps(status, ensure_ascii=False), flush=True)

    statuses = [
        status_by_sample[f"{sample.category}/{sample.sample_id}"]
        for sample in samples
    ]
    summary = build_batch_summary(statuses)
    summary["selected_sample_ids"] = [sample.sample_id for sample in samples]
    summary["jobs"] = [
        {"category": sample.category, "sample_id": sample.sample_id}
        for sample in samples
    ]
    summary["dry_run"] = bool(args.dry_run)
    _write_json(args.output_root / "batch_summary.json", summary)
    print(
        json.dumps(
            {
                "status": "finished",
                "selected": len(samples),
                "dry_run": args.dry_run,
                "output_root": str(args.output_root),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if summary["parse_failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
