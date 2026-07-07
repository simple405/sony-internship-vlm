"""Validate human supervision annotation CSV files.

This script checks the pre-gold human annotation inputs:

- human_visual_findings.csv from Stage 1 free visual review
- annotator_gold.csv from Stage 1 v3 rule-level review
- atomic_rule_audit.csv from Stage 2 atomic rule audit

It can run before real annotation data exists; pass only the files that are
available. Sample configs are optional but recommended because they let the
validator check sample_id and rule_id against atomic_rules.json.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("vlm/tmp/human_annotation_validation")

VISUAL_FINDINGS_COLUMNS = [
    "sample_id",
    "category",
    "finding_id",
    "view",
    "issue_type",
]

VISUAL_FINDINGS_OPTIONAL_COLUMNS = [
    "human_rule_name",
    "element_name",
    "attribute",
    "bbox_2d",
    "bbox_multiview",
    "visible",
    "status",
    "match_status",
    "expected_value",
    "observed_value",
    "feature_key",
    "expected_from_2d",
    "observed_in_multiview",
    "severity",
    "source_2d_evidence",
    "multiview_evidence",
    "reason",
    "annotator_id",
    "annotation_batch",
]

ANNOTATOR_GOLD_COLUMNS = [
    "sample_id",
    "rule_id",
    "value",
    "front_visible",
    "front_status",
    "side_visible",
    "side_status",
    "back_visible",
    "back_status",
    "result",
]

ATOMIC_RULE_AUDIT_COLUMNS = [
    "sample_id",
    "category",
    "rule_id",
    "rule_key",
    "atomic_value",
    "rule_validity",
    "corrected_value",
    "reason",
    "annotator_id",
    "annotation_batch",
]

VIEW_VALUES = {"front", "side", "back", "multiple", "all", "unknown"}
VISUAL_ISSUE_TYPES = {"wrong color", "wrong shape", "missing", "extra", "wrong invisible", "other"}
SEVERITY_VALUES = {"critical", "major", "minor", "unknown", ""}
OPTIONAL_VISIBLE_VALUES = {"visible", "invisible", "unknown", ""}
MATCH_STATUS_VALUES = {"correct", "wrong", "unsure", ""}
RULE_VALIDITY_VALUES = {"correct", "wrong_value", "missing_from_2d", "ambiguous", "out_of_scope", "duplicate"}
VISIBLE_VALUES = {"visible", "invisible"}
VISIBLE_STATUS_VALUES = {"correct", "wrong color", "wrong shape", "extra"}
INVISIBLE_STATUS_VALUES = {"correct", "wrong invisible"}
ERROR_STATUSES = {"wrong color", "wrong shape", "extra", "wrong invisible"}
RESULT_VALUES = {"correct", "wrong"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate human annotation CSV files.")
    parser.add_argument("--visual-findings", type=Path, help="human_visual_findings.csv")
    parser.add_argument("--annotator-gold", type=Path, help="annotator_gold.csv with v3 columns")
    parser.add_argument("--atomic-rule-audit", type=Path, help="atomic_rule_audit.csv")
    parser.add_argument(
        "--sample-config",
        type=Path,
        action="append",
        default=[],
        help="Qwen sample config JSON. Can be passed multiple times.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--fail-on-errors", action="store_true", help="Exit nonzero if FAIL rows are found.")
    return parser.parse_args()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
        return list(reader.fieldnames or []), rows


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_sample_registry(sample_configs: list[Path]) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for config_path in sample_configs:
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
        for sample in data.get("samples", []):
            sample_id = str(sample.get("sample_id", "")).strip()
            if not sample_id:
                continue
            rule_map = load_atomic_rule_map(Path(sample["atomic_rules"]))
            registry[sample_id] = {
                "category": str(sample.get("category", "")),
                "atomic_rules": str(sample.get("atomic_rules", "")),
                "rule_map": rule_map,
            }
    return registry


def load_atomic_rule_map(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    raw_rules = data.get("atomic_rules", data) if isinstance(data, dict) else data
    rule_map: dict[str, str] = {}
    if not isinstance(raw_rules, list):
        return rule_map
    for item in raw_rules:
        if not isinstance(item, dict):
            continue
        rule_id = str(item.get("rule_id") or item.get("id") or item.get("name") or "").strip()
        if not rule_id:
            continue
        value = item.get("value", "")
        rule_map[rule_id] = str(value)
    return rule_map


def missing_columns(header: list[str], required: list[str]) -> list[str]:
    return [column for column in required if column not in header]


def status(issues: list[str], warnings: list[str]) -> str:
    if issues:
        return "FAIL"
    if warnings:
        return "WARN"
    return "PASS"


def validate_known_sample(
    row: dict[str, str],
    registry: dict[str, dict[str, Any]],
    issues: list[str],
    warnings: list[str],
) -> None:
    sample_id = row.get("sample_id", "")
    if not registry or not sample_id:
        return
    sample = registry.get(sample_id)
    if sample is None:
        issues.append("unknown_sample_id")
        return
    category = row.get("category", "")
    if category and sample.get("category") and category != sample["category"]:
        warnings.append(f"category_mismatch_expected_{sample['category']}")


def validate_known_rule(
    row: dict[str, str],
    registry: dict[str, dict[str, Any]],
    issues: list[str],
    warnings: list[str],
) -> None:
    sample_id = row.get("sample_id", "")
    rule_id = row.get("rule_id", "")
    if not registry or not sample_id or not rule_id:
        return
    sample = registry.get(sample_id)
    if sample is None:
        issues.append("unknown_sample_id")
        return
    rule_map = sample.get("rule_map", {})
    if rule_map and rule_id not in rule_map:
        issues.append("rule_id_not_in_atomic_rules")
    atomic_value = row.get("atomic_value", "")
    if atomic_value and rule_id in rule_map and atomic_value != str(rule_map[rule_id]):
        warnings.append("atomic_value_differs_from_source")


def validate_visual_findings(path: Path, registry: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    header, rows = read_csv(path)
    report: list[dict[str, Any]] = []
    file_issues = missing_columns(header, VISUAL_FINDINGS_COLUMNS)
    seen: set[tuple[str, str]] = set()

    if file_issues:
        report.append(file_level_row(path, "FAIL", [f"missing_column:{item}" for item in file_issues], []))
        return report

    for index, row in enumerate(rows, start=2):
        issues: list[str] = []
        warnings: list[str] = []
        for column in VISUAL_FINDINGS_COLUMNS:
            if not row.get(column):
                issues.append(f"missing_{column}")
        if not (row.get("feature_key") or row.get("human_rule_name") or row.get("element_name")):
            issues.append("missing_feature_key_or_human_rule_name_or_element_name")
        validate_known_sample(row, registry, issues, warnings)
        if row.get("view") and row["view"] not in VIEW_VALUES:
            issues.append(f"invalid_view:{row['view']}")
        if row.get("issue_type") and row["issue_type"] not in VISUAL_ISSUE_TYPES:
            issues.append(f"invalid_issue_type:{row['issue_type']}")
        if row.get("severity", "") not in SEVERITY_VALUES:
            issues.append(f"invalid_severity:{row['severity']}")
        if row.get("visible", "") not in OPTIONAL_VISIBLE_VALUES:
            issues.append(f"invalid_visible:{row['visible']}")
        if row.get("match_status", "") not in MATCH_STATUS_VALUES:
            issues.append(f"invalid_match_status:{row['match_status']}")
        key = (row.get("sample_id", ""), row.get("finding_id", ""))
        if key in seen:
            issues.append("duplicate_finding_id_for_sample")
        seen.add(key)
        report.append(row_report(path, index, "human_visual_findings", row, issues, warnings))
    return report


def validate_annotator_gold(path: Path, registry: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    header, rows = read_csv(path)
    report: list[dict[str, Any]] = []
    file_issues = missing_columns(header, ANNOTATOR_GOLD_COLUMNS)
    seen: set[tuple[str, str]] = set()

    if file_issues:
        report.append(file_level_row(path, "FAIL", [f"missing_column:{item}" for item in file_issues], []))
        return report

    for index, row in enumerate(rows, start=2):
        issues: list[str] = []
        warnings: list[str] = []
        for column in ANNOTATOR_GOLD_COLUMNS:
            if not row.get(column):
                issues.append(f"missing_{column}")
        validate_known_rule(row, registry, issues, warnings)

        statuses: list[str] = []
        for view in ["front", "side", "back"]:
            visible = row.get(f"{view}_visible", "")
            view_status = row.get(f"{view}_status", "")
            statuses.append(view_status)
            if visible and visible not in VISIBLE_VALUES:
                issues.append(f"invalid_{view}_visible:{visible}")
            if visible == "visible" and view_status and view_status not in VISIBLE_STATUS_VALUES:
                issues.append(f"invalid_{view}_status_for_visible:{view_status}")
            if visible == "invisible" and view_status and view_status not in INVISIBLE_STATUS_VALUES:
                issues.append(f"invalid_{view}_status_for_invisible:{view_status}")

        expected_result = "wrong" if any(item in ERROR_STATUSES for item in statuses) else "correct"
        result = row.get("result", "")
        if result and result not in RESULT_VALUES:
            issues.append(f"invalid_result:{result}")
        elif result and result != expected_result:
            issues.append(f"result_mismatch_expected_{expected_result}")

        key = (row.get("sample_id", ""), row.get("rule_id", ""))
        if key in seen:
            issues.append("duplicate_rule_id_for_sample")
        seen.add(key)
        report.append(row_report(path, index, "annotator_gold", row, issues, warnings))
    return report


def validate_atomic_rule_audit(path: Path, registry: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    header, rows = read_csv(path)
    report: list[dict[str, Any]] = []
    file_issues = missing_columns(header, ATOMIC_RULE_AUDIT_COLUMNS)
    seen: set[tuple[str, str]] = set()

    if file_issues:
        report.append(file_level_row(path, "FAIL", [f"missing_column:{item}" for item in file_issues], []))
        return report

    for index, row in enumerate(rows, start=2):
        issues: list[str] = []
        warnings: list[str] = []
        for column in ["sample_id", "category", "rule_id", "atomic_value", "rule_validity"]:
            if not row.get(column):
                issues.append(f"missing_{column}")
        validate_known_rule(row, registry, issues, warnings)
        validity = row.get("rule_validity", "")
        if validity and validity not in RULE_VALIDITY_VALUES:
            issues.append(f"invalid_rule_validity:{validity}")
        if validity == "wrong_value" and not row.get("corrected_value"):
            issues.append("missing_corrected_value_for_wrong_value")
        if validity and validity != "correct" and not row.get("reason"):
            warnings.append("non_correct_without_reason")
        key = (row.get("sample_id", ""), row.get("rule_id", ""))
        if key in seen:
            issues.append("duplicate_rule_id_for_sample")
        seen.add(key)
        report.append(row_report(path, index, "atomic_rule_audit", row, issues, warnings))
    return report


def row_report(
    path: Path,
    row_number: int,
    schema_name: str,
    row: dict[str, str],
    issues: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "source_file": str(path),
        "schema": schema_name,
        "row_number": row_number,
        "sample_id": row.get("sample_id", ""),
        "rule_id": row.get("rule_id", ""),
        "finding_id": row.get("finding_id", ""),
        "qc_status": status(issues, warnings),
        "issues": ";".join(issues),
        "warnings": ";".join(warnings),
    }


def file_level_row(path: Path, qc_status: str, issues: list[str], warnings: list[str]) -> dict[str, Any]:
    return {
        "source_file": str(path),
        "schema": "",
        "row_number": "",
        "sample_id": "",
        "rule_id": "",
        "finding_id": "",
        "qc_status": qc_status,
        "issues": ";".join(issues),
        "warnings": ";".join(warnings),
    }


def main() -> None:
    args = parse_args()
    registry = load_sample_registry(args.sample_config)
    report: list[dict[str, Any]] = []

    inputs = [
        ("human_visual_findings", args.visual_findings, validate_visual_findings),
        ("annotator_gold", args.annotator_gold, validate_annotator_gold),
        ("atomic_rule_audit", args.atomic_rule_audit, validate_atomic_rule_audit),
    ]
    for _, path, validator in inputs:
        if path is None:
            continue
        if not path.exists():
            report.append(file_level_row(path, "FAIL", ["file_not_found"], []))
            continue
        report.extend(validator(path, registry))

    counts = Counter(row["qc_status"] for row in report)
    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "inputs_checked": sum(1 for _, path, _ in inputs if path is not None),
        "sample_configs": [str(path) for path in args.sample_config],
        "known_samples": len(registry),
        "rows_checked": len(report),
        "qc_counts": dict(sorted(counts.items())),
    }

    output_dir = args.output_dir
    write_csv(
        output_dir / "human_annotation_validation_report.csv",
        report,
        ["source_file", "schema", "row_number", "sample_id", "rule_id", "finding_id", "qc_status", "issues", "warnings"],
    )
    write_json(output_dir / "summary.json", summary)
    print(json.dumps({"status": "finished", **summary}, ensure_ascii=False))

    if args.fail_on_errors and counts.get("FAIL", 0):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
