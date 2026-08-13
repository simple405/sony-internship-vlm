"""Run an image-only VLM supervision prototype for front-view samples.

The agent deliberately hides paired/silver JSON from Qwen inference. It first
extracts visual JSON from the original and generated images independently, then
compares the two images plus those extracted profiles to produce rule-level
verdicts. Existing silver JSON and review_v2 files remain available only as
offline teacher/evaluation references outside this script.
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

from vlm.scripts._http import direct_http_session
from vlm.scripts._paths import SUPERVISION_PROMPTS_DIR, VLM_ROOT, load_api_env
from vlm.scripts._validation import validate_path_component, validate_qwen_base_url
from vlm.scripts.generate.prompt_renderer import (
    CATEGORY_REQUIREMENTS,
    MERCHANDISE_LABELS,
)
from vlm.scripts.supervise.run_paired_front_view_review import (
    ALLOWED_LOCATIONS,
    ALLOWED_RESULTS,
    ReviewSample,
    build_batch_summary,
    compute_aggregate_counts,
    compute_overall_decision,
    discover_samples,
    extract_json_object,
    media_type,
    select_review_jobs,
    write_review_csv,
)


DEFAULT_INPUT_ROOT = VLM_ROOT / "data" / "front_view_generation_v2"
DEFAULT_OUTPUT_ROOT = VLM_ROOT / "tmp" / "sn6_image_only_agent_v0"
DEFAULT_EXTRACT_PROMPT_FILE = (
    SUPERVISION_PROMPTS_DIR / "front_view_visual_extraction_cn.txt"
)
DEFAULT_COMPARE_PROMPT_FILE = (
    SUPERVISION_PROMPTS_DIR / "front_view_image_only_compare_cn.txt"
)
DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_MODEL = "qwen-vl-max"
DEFAULT_AGENT_ROOT_NAME = "image_only_v0"
DEFAULT_SAMPLE_OUTPUT_PARENT = "_agent"
REVIEW_SAMPLE_OUTPUT_PARENT = "_review"
ALLOWED_VISIBILITIES = {"visible", "partial", "not_evaluable"}
HEAD_ONLY_CATEGORIES = {"head_key_chain", "cake_roll", "backpack"}


@dataclass(frozen=True)
class AgentPrompts:
    """Rendered prompt templates for one image-only agent run."""

    extract_prompt_file: Path
    extract_template: str
    compare_prompt_file: Path
    compare_template: str


def encode_image_data_url(path: Path) -> str:
    """Encode an image as a base64 data URL for an OpenAI-style request."""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type(path)};base64,{encoded}"


def build_multimodal_messages(
    prompt_text: str,
    image_paths: list[Path],
) -> list[dict[str, Any]]:
    """Build a single-user-turn message with text plus one or more images."""
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt_text}]
    for image_path in image_paths:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": encode_image_data_url(image_path)},
            }
        )
    return [{"role": "user", "content": content}]


def call_qwen_json(
    *,
    api_key: str,
    base_url: str,
    model: str,
    image_paths: list[Path],
    prompt_text: str,
    timeout: int,
    max_tokens: int = 5000,
    max_retries: int = 2,
) -> str:
    """Call Qwen-VL with one or more images and return raw text content."""
    base_url = validate_qwen_base_url(base_url)
    payload: dict[str, Any] = {
        "model": model,
        "messages": build_multimodal_messages(prompt_text, image_paths),
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    last_error: Exception | None = None
    with direct_http_session() as session:
        for attempt in range(max_retries + 1):
            try:
                response = session.post(
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


def build_extraction_prompt(
    template: str,
    *,
    image_role: str,
    category: str,
) -> str:
    """Render the visual extraction prompt for a source or generated image."""
    return (
        template.replace("{{IMAGE_ROLE}}", image_role)
        .replace("{{MERCHANDISE_CATEGORY}}", MERCHANDISE_LABELS.get(category, category))
        .replace("{{CATEGORY_KEY}}", category)
        .replace(
            "{{CATEGORY_REQUIREMENTS}}",
            CATEGORY_REQUIREMENTS.get(
                category,
                "Review visible identity features for the current merchandise category.",
            ),
        )
    )


def build_comparison_prompt(
    template: str,
    *,
    source_visual: dict[str, Any],
    generated_visual: dict[str, Any],
    category: str,
) -> str:
    """Render the two-image comparison prompt with extracted visual JSON."""
    return (
        template.replace("{{MERCHANDISE_CATEGORY}}", MERCHANDISE_LABELS.get(category, category))
        .replace("{{CATEGORY_KEY}}", category)
        .replace(
            "{{CATEGORY_REQUIREMENTS}}",
            CATEGORY_REQUIREMENTS.get(
                category,
                "Review visible identity features for the current merchandise category.",
            ),
        )
        .replace(
            "{{SOURCE_VISUAL_JSON}}",
            json.dumps(source_visual, ensure_ascii=False, indent=2),
        )
        .replace(
            "{{GENERATED_VISUAL_JSON}}",
            json.dumps(generated_visual, ensure_ascii=False, indent=2),
        )
    )


def normalize_confidence(value: Any) -> float:
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


def validate_visual_profile(
    raw_profile: Any,
    *,
    image_role: str,
    category: str,
) -> tuple[dict[str, Any], list[str]]:
    """Normalize extracted visual JSON while preserving inspectable evidence."""
    issues: list[str] = []
    profile = dict(raw_profile) if isinstance(raw_profile, dict) else {}
    if not isinstance(raw_profile, dict):
        issues.append(f"{image_role}_profile_not_object")
    elements = profile.get("elements")
    if not isinstance(elements, list):
        issues.append(f"{image_role}_elements_not_list")
        elements = []

    normalized: list[dict[str, Any]] = []
    for index, raw_element in enumerate(elements, start=1):
        element = dict(raw_element) if isinstance(raw_element, dict) else {}
        if not isinstance(raw_element, dict):
            issues.append(f"{image_role}_element_{index}_not_object")
        element["element_id"] = str(element.get("element_id") or f"e{index}")
        element["element"] = str(element.get("element") or "").strip()
        location = str(element.get("location") or "").strip().lower()
        if location not in ALLOWED_LOCATIONS:
            issues.append(f"{image_role}_invalid_location_{index}:{location}")
            location = ""
        element["location"] = location
        visibility = str(element.get("visibility") or "").strip()
        if visibility not in ALLOWED_VISIBILITIES:
            issues.append(f"{image_role}_invalid_visibility_{index}:{visibility}")
            visibility = "partial"
        element["visibility"] = visibility
        bbox = element.get("evidence_bbox")
        if bbox is not None:
            valid_bbox = isinstance(bbox, list) and len(bbox) == 4
            if valid_bbox:
                try:
                    valid_bbox = all(math.isfinite(float(value)) for value in bbox)
                except (TypeError, ValueError):
                    valid_bbox = False
            if not valid_bbox:
                issues.append(f"{image_role}_invalid_bbox_{index}")
                bbox = None
        element["evidence_bbox"] = bbox
        element["confidence"] = normalize_confidence(element.get("confidence"))
        normalized.append(element)

    return {
        "schema_version": "front_view_visual_profile.v1",
        "image_role": image_role,
        "category": category,
        "elements": normalized,
        "global_notes": str(profile.get("global_notes") or "").strip(),
        "qc_issues": issues,
    }, issues


def validate_agent_rules(raw_rules: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Normalize image-only comparator rules without using external gold JSON."""
    issues: list[str] = []
    if not isinstance(raw_rules, list):
        return [], ["rules_not_a_list"]

    aligned: list[dict[str, Any]] = []
    for index, raw_rule in enumerate(raw_rules, start=1):
        rule = dict(raw_rule) if isinstance(raw_rule, dict) else {}
        if not isinstance(raw_rule, dict):
            issues.append(f"rule_{index}_not_object")
        rule["rule_index"] = index
        rule["element"] = str(rule.get("element") or "").strip()
        result = str(rule.get("result") or "").strip()
        if result not in ALLOWED_RESULTS:
            issues.append(f"invalid_result_at_index_{index}:{result}")
            result = "review"
        rule["result"] = result
        location = str(rule.get("location") or "").strip().lower()
        if location:
            if location not in ALLOWED_LOCATIONS:
                issues.append(f"invalid_location_at_index_{index}:{location}")
                location = ""
        rule["location"] = location
        rule["confidence"] = normalize_confidence(rule.get("confidence"))
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
                bbox = None
        rule["evidence_bbox"] = bbox
        aligned.append(rule)
    return aligned, issues


def profile_for_comparison(profile: dict[str, Any]) -> dict[str, Any]:
    """Return a visual profile containing only positive source evidence."""
    filtered = dict(profile)
    elements = []
    for element in profile.get("elements") or []:
        if not isinstance(element, dict):
            continue
        if not str(element.get("element") or "").strip():
            continue
        if element.get("visibility") == "not_evaluable":
            continue
        elements.append(element)
    filtered["elements"] = elements
    return filtered


def apply_head_only_scope_rules(
    rules: list[dict[str, Any]],
    *,
    category: str,
) -> list[dict[str, Any]]:
    """Force body rules out of scope for head-only merchandise categories."""
    if category not in HEAD_ONLY_CATEGORIES:
        return rules
    adjusted: list[dict[str, Any]] = []
    for rule in rules:
        item = dict(rule)
        if item.get("location") != "body":
            adjusted.append(item)
            continue
        original_result = item.get("result")
        item["result"] = "out_of_scope"
        item["image_grounded"] = False
        item["description_correct"] = True
        item["issue_types"] = []
        item["evidence_bbox"] = None
        item["confidence"] = 1.0
        reason = str(item.get("reason") or "").strip()
        scope_note = (
            f"{category} is treated as head-only in this pilot; body rule was "
            f"converted from {original_result} to out_of_scope."
        )
        item["reason"] = f"{reason} {scope_note}".strip()
        adjusted.append(item)
    return adjusted


def resolve_agent_output_dir(
    sample: ReviewSample,
    sample_agent_root_name: str,
    sample_output_parent: str = DEFAULT_SAMPLE_OUTPUT_PARENT,
) -> Path:
    """Return the per-sample image-only agent output directory."""
    safe_name = validate_path_component(sample_agent_root_name, "sample agent root name")
    safe_parent = validate_sample_output_parent(sample_output_parent)
    return sample.generated_image_path.parent / safe_parent / safe_name


def validate_sample_output_parent(value: str) -> str:
    """Return the allowed per-sample output parent directory."""
    safe_parent = validate_path_component(value, "sample output parent")
    if safe_parent not in {DEFAULT_SAMPLE_OUTPUT_PARENT, REVIEW_SAMPLE_OUTPUT_PARENT}:
        raise ValueError(
            "sample output parent must be '_agent' or '_review': "
            f"{value!r}"
        )
    return safe_parent


def resolve_auxiliary_output_dir(
    sample: ReviewSample,
    output_root: Path,
    sample_agent_root_name: str,
) -> Path:
    """Return the batch-level prompt/request directory for one sample."""
    safe_name = validate_path_component(sample_agent_root_name, "sample agent root name")
    if sample.category:
        return output_root / "_sample_aux" / safe_name / sample.category / sample.sample_id
    return output_root / "_sample_aux" / safe_name / sample.sample_id


def sha256_file(path: Path) -> str:
    """Return a file SHA-256 digest."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    """Write indented UTF-8 JSON, replacing any existing artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def request_preview(
    sample: ReviewSample,
    prompts: AgentPrompts,
    output_dir: Path,
    *,
    source_prompt: str,
    generated_prompt: str,
    compare_prompt: str,
) -> dict[str, Any]:
    """Build a redacted request preview for the image-only agent run."""
    return {
        "schema_version": "front_view_image_only_agent_request.v1",
        "sample_id": sample.sample_id,
        "category": sample.category,
        "source_image_sha256": sha256_file(sample.original_image_path),
        "generated_image_sha256": sha256_file(sample.generated_image_path),
        "source_json_used_for_inference": False,
        "prompt_files": {
            "extract": str(prompts.extract_prompt_file),
            "compare": str(prompts.compare_prompt_file),
        },
        "prompt_sha256": {
            "source_extract": hashlib.sha256(source_prompt.encode("utf-8")).hexdigest(),
            "generated_extract": hashlib.sha256(generated_prompt.encode("utf-8")).hexdigest(),
            "compare": hashlib.sha256(compare_prompt.encode("utf-8")).hexdigest(),
        },
        "request": {
            "source_image_path": str(sample.original_image_path),
            "generated_image_path": str(sample.generated_image_path),
            "image_count": 2,
        },
        "output_dir": str(output_dir),
    }


def process_one(
    sample: ReviewSample,
    prompts: AgentPrompts,
    output_root: Path,
    *,
    dry_run: bool,
    api_key: str = "",
    base_url: str = "",
    model: str = "",
    timeout: int = 180,
    max_retries: int = 2,
    sample_agent_root_name: str = DEFAULT_AGENT_ROOT_NAME,
    sample_output_parent: str = DEFAULT_SAMPLE_OUTPUT_PARENT,
    call_fn: Callable[..., str] = call_qwen_json,
) -> dict[str, Any]:
    """Run extraction and comparison for one sample and persist artifacts."""
    category = sample.category or "dataset_figurine"
    output_dir = resolve_agent_output_dir(
        sample,
        sample_agent_root_name,
        sample_output_parent=sample_output_parent,
    )
    auxiliary_dir = resolve_auxiliary_output_dir(sample, output_root, sample_agent_root_name)
    source_prompt = build_extraction_prompt(
        prompts.extract_template,
        image_role="source_original",
        category=category,
    )
    generated_prompt = build_extraction_prompt(
        prompts.extract_template,
        image_role="generated_front_view",
        category=category,
    )
    dry_compare_prompt = build_comparison_prompt(
        prompts.compare_template,
        source_visual={"schema_version": "front_view_visual_profile.v1", "elements": []},
        generated_visual={"schema_version": "front_view_visual_profile.v1", "elements": []},
        category=category,
    )
    auxiliary_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    (auxiliary_dir / "source_extraction_prompt.txt").write_text(
        source_prompt,
        encoding="utf-8",
    )
    (auxiliary_dir / "generated_extraction_prompt.txt").write_text(
        generated_prompt,
        encoding="utf-8",
    )
    if dry_run:
        preview = request_preview(
            sample,
            prompts,
            output_dir,
            source_prompt=source_prompt,
            generated_prompt=generated_prompt,
            compare_prompt=dry_compare_prompt,
        )
        write_json(auxiliary_dir / "request_preview.json", preview)
        (auxiliary_dir / "compare_prompt.txt").write_text(
            dry_compare_prompt,
            encoding="utf-8",
        )
        status = {
            "schema_version": "front_view_image_only_agent_status.v1",
            "sample_id": sample.sample_id,
            "category": sample.category,
            "status": "dry_run",
        }
        write_json(output_dir / "status.json", status)
        return status

    started = time.time()
    raw_source = call_fn(
        api_key=api_key,
        base_url=base_url,
        model=model,
        image_paths=[sample.original_image_path],
        prompt_text=source_prompt,
        timeout=timeout,
        max_retries=max_retries,
    )
    (output_dir / "raw_source_visual_response.txt").write_text(
        str(raw_source),
        encoding="utf-8",
    )
    source_visual, source_issues = validate_visual_profile(
        extract_json_object(raw_source),
        image_role="source_original",
        category=category,
    )
    write_json(output_dir / "source_visual.json", source_visual)

    raw_generated = call_fn(
        api_key=api_key,
        base_url=base_url,
        model=model,
        image_paths=[sample.generated_image_path],
        prompt_text=generated_prompt,
        timeout=timeout,
        max_retries=max_retries,
    )
    (output_dir / "raw_generated_visual_response.txt").write_text(
        str(raw_generated),
        encoding="utf-8",
    )
    generated_visual, generated_issues = validate_visual_profile(
        extract_json_object(raw_generated),
        image_role="generated_front_view",
        category=category,
    )
    write_json(output_dir / "generated_visual.json", generated_visual)

    compare_prompt = build_comparison_prompt(
        prompts.compare_template,
        source_visual=profile_for_comparison(source_visual),
        generated_visual=generated_visual,
        category=category,
    )
    (auxiliary_dir / "compare_prompt.txt").write_text(
        compare_prompt,
        encoding="utf-8",
    )
    preview = request_preview(
        sample,
        prompts,
        output_dir,
        source_prompt=source_prompt,
        generated_prompt=generated_prompt,
        compare_prompt=compare_prompt,
    )
    write_json(auxiliary_dir / "request_preview.json", preview)

    raw_prediction = call_fn(
        api_key=api_key,
        base_url=base_url,
        model=model,
        image_paths=[sample.original_image_path, sample.generated_image_path],
        prompt_text=compare_prompt,
        timeout=timeout,
        max_retries=max_retries,
    )
    (output_dir / "raw_prediction_response.txt").write_text(
        str(raw_prediction),
        encoding="utf-8",
    )
    parsed_prediction = extract_json_object(raw_prediction)
    rules, rule_issues = validate_agent_rules(parsed_prediction.get("rules"))
    rules = apply_head_only_scope_rules(rules, category=category)
    aggregate_counts = compute_aggregate_counts(rules)
    qc_issues = source_issues + generated_issues + rule_issues
    overall_decision = compute_overall_decision(rules, qc_issues)
    extra_elements = parsed_prediction.get("extra_elements")
    if not isinstance(extra_elements, list):
        extra_elements = []

    prediction = {
        "schema_version": "front_view_image_only_agent_prediction.v1",
        "sample_id": sample.sample_id,
        "category": sample.category,
        "inputs": {
            "source_image": str(sample.original_image_path),
            "generated_image": str(sample.generated_image_path),
            "source_json_used_for_inference": False,
        },
        "source_visual": str(output_dir / "source_visual.json"),
        "generated_visual": str(output_dir / "generated_visual.json"),
        "rules": rules,
        "extra_elements": extra_elements,
        "aggregate_counts": aggregate_counts,
        "overall_decision": overall_decision,
        "qc_issues": qc_issues,
        "metadata": {
            "model": model,
            "elapsed_seconds": round(time.time() - started, 2),
            "source_extract_prompt_sha256": hashlib.sha256(
                source_prompt.encode("utf-8")
            ).hexdigest(),
            "generated_extract_prompt_sha256": hashlib.sha256(
                generated_prompt.encode("utf-8")
            ).hexdigest(),
            "compare_prompt_sha256": hashlib.sha256(
                compare_prompt.encode("utf-8")
            ).hexdigest(),
        },
    }
    write_json(output_dir / "prediction.json", prediction)
    write_review_csv(output_dir / "qc.csv", rules)

    status = {
        "schema_version": "front_view_image_only_agent_status.v1",
        "sample_id": sample.sample_id,
        "category": sample.category,
        "status": "succeeded",
        "overall_decision": overall_decision,
        "aggregate_counts": aggregate_counts,
        "qc_issue_count": len(qc_issues),
    }
    write_json(output_dir / "status.json", status)
    return status


def select_agent_jobs(
    samples: list[ReviewSample],
    *,
    jobs: list[str],
    sample_manifest: Path | None,
    requested_ids: list[str],
    limit: int,
    fallback_category: str,
) -> list[ReviewSample]:
    """Select image-only agent jobs from category/sample pairs or manifest input."""
    if jobs and (sample_manifest is not None or requested_ids):
        raise ValueError("--job cannot be combined with --sample-manifest or --sample-id")
    if jobs:
        by_key = {(sample.category, sample.sample_id): sample for sample in samples}
        selected: list[ReviewSample] = []
        for raw_job in jobs:
            if "/" not in raw_job:
                raise ValueError(f"--job must use category/sample_id: {raw_job}")
            category, sample_id = raw_job.split("/", 1)
            category = category.strip()
            sample_id = validate_path_component(sample_id.strip(), "sample ID")
            sample = by_key.get((category, sample_id))
            if sample is None:
                raise ValueError(f"Generated sample not found for {category}/{sample_id}")
            selected.append(sample)
        return selected
    return select_review_jobs(
        samples,
        sample_manifest=sample_manifest,
        requested_ids=requested_ids,
        limit=limit,
        fallback_category=fallback_category,
    )


def load_prompts(extract_prompt_file: Path, compare_prompt_file: Path) -> AgentPrompts:
    """Load and validate the two prompt templates."""
    if not extract_prompt_file.is_file():
        raise SystemExit(f"Extraction prompt not found: {extract_prompt_file}")
    if not compare_prompt_file.is_file():
        raise SystemExit(f"Compare prompt not found: {compare_prompt_file}")
    extract_template = extract_prompt_file.read_text(encoding="utf-8-sig").strip()
    compare_template = compare_prompt_file.read_text(encoding="utf-8-sig").strip()
    if not extract_template:
        raise SystemExit(f"Extraction prompt is empty: {extract_prompt_file}")
    if not compare_template:
        raise SystemExit(f"Compare prompt is empty: {compare_prompt_file}")
    return AgentPrompts(
        extract_prompt_file=extract_prompt_file,
        extract_template=extract_template,
        compare_prompt_file=compare_prompt_file,
        compare_template=compare_template,
    )


def parse_args() -> argparse.Namespace:
    """Parse image-only agent CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Run an image-only front-view supervision agent prototype."
    )
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--extract-prompt-file", type=Path, default=DEFAULT_EXTRACT_PROMPT_FILE)
    parser.add_argument("--compare-prompt-file", type=Path, default=DEFAULT_COMPARE_PROMPT_FILE)
    parser.add_argument("--sample-manifest", type=Path, default=None)
    parser.add_argument("--sample-id", action="append", default=[])
    parser.add_argument("--job", action="append", default=[])
    parser.add_argument("--category", default="dataset_figurine", choices=tuple(CATEGORY_REQUIREMENTS))
    parser.add_argument("--sample-agent-root-name", default=DEFAULT_AGENT_ROOT_NAME)
    parser.add_argument(
        "--sample-review-root-name",
        default="",
        help=(
            "Write per-sample image-only artifacts under _review/<name> "
            "instead of _agent/<sample-agent-root-name>."
        ),
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--model", default="")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--max-retries", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    """Run selected image-only agent samples and write batch outputs."""
    args = parse_args()
    if args.limit < 0:
        raise SystemExit("--limit must be >= 0")
    if args.workers < 1 or args.workers > 3:
        raise SystemExit("--workers must be between 1 and 3")
    if args.max_retries < 0:
        raise SystemExit("--max-retries must be >= 0")
    sample_output_parent = DEFAULT_SAMPLE_OUTPUT_PARENT
    sample_output_root_name = args.sample_agent_root_name
    if args.sample_review_root_name:
        sample_output_parent = REVIEW_SAMPLE_OUTPUT_PARENT
        sample_output_root_name = validate_path_component(
            args.sample_review_root_name,
            "sample review root name",
        )

    prompts = load_prompts(args.extract_prompt_file, args.compare_prompt_file)
    all_samples = discover_samples(args.input_root)
    samples = select_agent_jobs(
        all_samples,
        jobs=args.job,
        sample_manifest=args.sample_manifest,
        requested_ids=args.sample_id,
        limit=args.limit,
        fallback_category=args.category,
    )
    if not samples:
        raise SystemExit("No samples selected")

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
    status_by_sample: dict[str, dict[str, Any]] = {}

    def _run_sample(sample: ReviewSample) -> dict[str, Any]:
        return process_one(
            sample,
            prompts,
            args.output_root,
            dry_run=args.dry_run,
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout=args.timeout,
            max_retries=args.max_retries,
            sample_agent_root_name=sample_output_root_name,
            sample_output_parent=sample_output_parent,
        )

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_sample = {executor.submit(_run_sample, sample): sample for sample in samples}
        for future in as_completed(future_to_sample):
            sample = future_to_sample[future]
            try:
                status = future.result()
            except Exception as exc:
                status = {
                    "schema_version": "front_view_image_only_agent_status.v1",
                    "sample_id": sample.sample_id,
                    "category": sample.category,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                sample_dir = resolve_agent_output_dir(
                    sample,
                    sample_output_root_name,
                    sample_output_parent=sample_output_parent,
                )
                write_json(sample_dir / "status.json", status)
            status_by_sample[f"{sample.category}/{sample.sample_id}"] = status
            print(json.dumps(status, ensure_ascii=False), flush=True)

    statuses = [
        status_by_sample[f"{sample.category}/{sample.sample_id}"]
        for sample in samples
    ]
    summary = build_batch_summary(statuses)
    summary["schema_version"] = "front_view_image_only_agent_batch.v1"
    summary["selected_sample_ids"] = [sample.sample_id for sample in samples]
    summary["jobs"] = [
        {"category": sample.category, "sample_id": sample.sample_id}
        for sample in samples
    ]
    summary["dry_run"] = bool(args.dry_run)
    summary["sample_agent_root_name"] = sample_output_root_name
    summary["sample_output_parent"] = sample_output_parent
    write_json(args.output_root / "batch_summary.json", summary)
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
