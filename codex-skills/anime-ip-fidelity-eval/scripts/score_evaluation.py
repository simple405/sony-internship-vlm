#!/usr/bin/env python3
"""Validate anime-IP fidelity assessments and compute reproducible scores."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ELEMENT_FACTORS = {
    "preserved": 1.0,
    "partial": 0.5,
    "missing": 0.0,
    "contradicted": 0.0,
    "unverifiable": None,
}
SPEC_POINTS = {
    "front_view": 5.0,
    "full_body": 4.0,
    "single_subject": 3.0,
    "white_background": 2.0,
    "three_dimensional": 4.0,
    "no_extra_text_or_watermark": 2.0,
}
HALLUCINATION_PENALTIES = {"minor": 2.0, "major": 8.0, "critical": 20.0}


def bounded_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number from 0 to 1")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{field} must be a number from 0 to 1")
    return result


def score_record(record: dict[str, Any]) -> dict[str, Any]:
    sample_id = record.get("sample_id")
    if not isinstance(sample_id, str) or not sample_id.strip():
        raise ValueError("sample_id must be a non-empty string")

    assessments = record.get("element_assessments")
    if not isinstance(assessments, list) or not assessments:
        raise ValueError(f"{sample_id}: element_assessments must be a non-empty list")
    weighted_total = 0.0
    weight_total = 0.0
    has_unverifiable = False
    for index, assessment in enumerate(assessments):
        if not isinstance(assessment, dict):
            raise ValueError(f"{sample_id}: element_assessments[{index}] must be an object")
        name = assessment.get("name")
        evidence = assessment.get("evidence")
        status = assessment.get("status")
        weight = assessment.get("weight", 1)
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{sample_id}: element_assessments[{index}].name is empty")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(f"{sample_id}: element_assessments[{index}].evidence is empty")
        if status not in ELEMENT_FACTORS:
            raise ValueError(f"{sample_id}: invalid element status {status!r}")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or float(weight) <= 0:
            raise ValueError(f"{sample_id}: element weight must be positive")
        factor = ELEMENT_FACTORS[status]
        if factor is None:
            has_unverifiable = True
            continue
        weighted_total += float(weight) * factor
        weight_total += float(weight)
    if weight_total == 0:
        raise ValueError(f"{sample_id}: all elements are unverifiable")
    element_points = 60.0 * weighted_total / weight_total

    spec_checks = record.get("spec_checks")
    if not isinstance(spec_checks, dict):
        raise ValueError(f"{sample_id}: spec_checks must be an object")
    spec_points = 0.0
    critical_reasons: list[str] = []
    for key, points in SPEC_POINTS.items():
        value = spec_checks.get(key)
        if not isinstance(value, bool):
            raise ValueError(f"{sample_id}: spec_checks.{key} must be true or false")
        if value:
            spec_points += points
        elif key in {"front_view", "full_body", "single_subject", "three_dimensional"}:
            critical_reasons.append(f"failed_{key}")

    identity_match = bounded_number(record.get("identity_match"), "identity_match")
    visual_quality = bounded_number(record.get("visual_quality"), "visual_quality")
    if identity_match < 0.5:
        critical_reasons.append("identity_below_0.5")

    hallucinations = record.get("hallucinations", [])
    if not isinstance(hallucinations, list):
        raise ValueError(f"{sample_id}: hallucinations must be a list")
    hallucination_penalty = 0.0
    for index, hallucination in enumerate(hallucinations):
        if not isinstance(hallucination, dict):
            raise ValueError(f"{sample_id}: hallucinations[{index}] must be an object")
        description = hallucination.get("description")
        severity = hallucination.get("severity")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"{sample_id}: hallucinations[{index}].description is empty")
        if severity not in HALLUCINATION_PENALTIES:
            raise ValueError(f"{sample_id}: invalid hallucination severity {severity!r}")
        hallucination_penalty += HALLUCINATION_PENALTIES[severity]
        if severity == "critical":
            critical_reasons.append("critical_hallucination")

    identity_points = 15.0 * identity_match
    quality_points = 5.0 * visual_quality
    total = max(0.0, element_points + spec_points + identity_points + quality_points - hallucination_penalty)
    if critical_reasons or total < 70.0:
        label = "fail"
    elif total < 85.0 or has_unverifiable:
        label = "review"
    else:
        label = "pass"

    result = dict(record)
    result["scores"] = {
        "element_fidelity": round(element_points, 2),
        "output_specification": round(spec_points, 2),
        "identity_coherence": round(identity_points, 2),
        "visual_quality": round(quality_points, 2),
        "hallucination_penalty": round(hallucination_penalty, 2),
        "total": round(total, 2),
    }
    result["decision"] = {
        "label": label,
        "requires_human_review": label == "review" or has_unverifiable or bool(critical_reasons),
        "critical_reasons": sorted(set(critical_reasons)),
    }
    return result


def load_records(path: Path) -> tuple[list[dict[str, Any]], str]:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".jsonl":
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
        return records, "jsonl"
    payload = json.loads(text)
    if isinstance(payload, list):
        return payload, "json"
    if isinstance(payload, dict):
        return [payload], "single"
    raise ValueError("input must be a JSON object, array, or JSONL records")


def render(records: list[dict[str, Any]], mode: str) -> str:
    if mode == "jsonl":
        return "\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records) + "\n"
    payload: Any = records[0] if mode == "single" else records
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        records, mode = load_records(args.input)
        scored = [score_record(record) for record in records]
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    output_text = render(scored, mode)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text, encoding="utf-8", newline="\n")
        print(json.dumps({"records": len(scored), "output": str(args.output)}))
    else:
        print(output_text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
