"""Build verified evaluation gold from human annotations.

The verified gold is intentionally narrower than raw human annotations:
it only includes annotator_gold rows whose atomic rule has been audited as
`rule_validity=correct`. This prevents incorrect atomic_rules from polluting
Qwen review accuracy.

The script supports a dry-run state before human data is available. If input
CSV files are omitted, it writes empty outputs with stable headers and a summary.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("vlm/tmp/verified_evaluation_gold")

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

VERIFIED_GOLD_COLUMNS = [
    "sample_id",
    "category",
    "rule_id",
    "value",
    "front_visible",
    "front_status",
    "side_visible",
    "side_status",
    "back_visible",
    "back_status",
    "result",
    "issue_type",
    "confidence",
    "reason",
    "audit_rule_validity",
    "audit_reason",
]

EXCLUDED_GOLD_COLUMNS = VERIFIED_GOLD_COLUMNS + ["exclude_reason"]

ATOMIC_RULE_QUALITY_COLUMNS = [
    "sample_id",
    "category",
    "rule_id",
    "atomic_value",
    "rule_validity",
    "corrected_value",
    "reason",
]

COVERAGE_GAP_COLUMNS = [
    "sample_id",
    "category",
    "finding_id",
    "view",
    "issue_type",
    "feature_key",
    "expected_from_2d",
    "observed_in_multiview",
    "severity",
    "gap_reason",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build verified Qwen evaluation gold.")
    parser.add_argument("--annotator-gold", type=Path, help="Stage 1 annotator_gold.csv")
    parser.add_argument("--atomic-rule-audit", type=Path, help="Stage 2 atomic_rule_audit.csv")
    parser.add_argument("--visual-findings", type=Path, help="Optional human_visual_findings.csv")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--include-unaudited",
        action="store_true",
        help="Include gold rows missing from atomic_rule_audit with audit_rule_validity=unaudited.",
    )
    return parser.parse_args()


def read_csv(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def audit_index(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    index: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (row.get("sample_id", ""), row.get("rule_id", ""))
        if key[0] and key[1] and key not in index:
            index[key] = row
    return index


def build_verified_rows(
    gold_rows: list[dict[str, str]],
    audit_rows: list[dict[str, str]],
    include_unaudited: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    audits = audit_index(audit_rows)
    verified: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for row in gold_rows:
        key = (row.get("sample_id", ""), row.get("rule_id", ""))
        audit = audits.get(key)
        if audit is None:
            if include_unaudited:
                verified.append(verified_row(row, {"rule_validity": "unaudited", "reason": ""}))
            else:
                excluded.append({**verified_row(row, {"rule_validity": "unaudited", "reason": ""}), "exclude_reason": "missing_audit"})
            continue

        validity = audit.get("rule_validity", "")
        if validity == "correct":
            verified.append(verified_row(row, audit))
        else:
            excluded.append({**verified_row(row, audit), "exclude_reason": f"rule_validity_{validity or 'blank'}"})
    return verified, excluded


def verified_row(row: dict[str, str], audit: dict[str, str]) -> dict[str, Any]:
    category = row.get("category") or audit.get("category", "")
    return {
        "sample_id": row.get("sample_id", ""),
        "category": category,
        "rule_id": row.get("rule_id", ""),
        "value": row.get("value") or audit.get("atomic_value", ""),
        "front_visible": row.get("front_visible", ""),
        "front_status": row.get("front_status", ""),
        "side_visible": row.get("side_visible", ""),
        "side_status": row.get("side_status", ""),
        "back_visible": row.get("back_visible", ""),
        "back_status": row.get("back_status", ""),
        "result": row.get("result", ""),
        "issue_type": row.get("issue_type", ""),
        "confidence": row.get("confidence", ""),
        "reason": row.get("reason", ""),
        "audit_rule_validity": audit.get("rule_validity", ""),
        "audit_reason": audit.get("reason", ""),
    }


def atomic_rule_quality_rows(audit_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "sample_id": row.get("sample_id", ""),
            "category": row.get("category", ""),
            "rule_id": row.get("rule_id", ""),
            "atomic_value": row.get("atomic_value", ""),
            "rule_validity": row.get("rule_validity", ""),
            "corrected_value": row.get("corrected_value", ""),
            "reason": row.get("reason", ""),
        }
        for row in audit_rows
    ]


def coverage_gap_rows(visual_rows: list[dict[str, str]], audit_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Emit Stage 1 findings as candidate coverage gaps.

    Until there is an explicit finding-to-rule mapping column, this output is a
    triage list rather than a strict coverage metric. A later converter can add
    matched_rule_id and suppress matched findings.
    """
    if not visual_rows:
        return []
    audited_samples = {row.get("sample_id", "") for row in audit_rows}
    gaps: list[dict[str, Any]] = []
    for row in visual_rows:
        sample_id = row.get("sample_id", "")
        gaps.append(
            {
                "sample_id": sample_id,
                "category": row.get("category", ""),
                "finding_id": row.get("finding_id", ""),
                "view": row.get("view", ""),
                "issue_type": row.get("issue_type", ""),
                "feature_key": row.get("feature_key", ""),
                "expected_from_2d": row.get("expected_from_2d", ""),
                "observed_in_multiview": row.get("observed_in_multiview", ""),
                "severity": row.get("severity", ""),
                "gap_reason": "needs_rule_mapping" if sample_id in audited_samples else "sample_not_in_rule_audit",
            }
        )
    return gaps


def main() -> None:
    args = parse_args()
    gold_rows = read_csv(args.annotator_gold)
    audit_rows = read_csv(args.atomic_rule_audit)
    visual_rows = read_csv(args.visual_findings)

    verified, excluded = build_verified_rows(gold_rows, audit_rows, args.include_unaudited)
    rule_quality = atomic_rule_quality_rows(audit_rows)
    coverage_gaps = coverage_gap_rows(visual_rows, audit_rows)

    output_dir = args.output_dir
    write_csv(output_dir / "verified_evaluation_gold.csv", verified, VERIFIED_GOLD_COLUMNS)
    write_csv(output_dir / "excluded_gold_rows.csv", excluded, EXCLUDED_GOLD_COLUMNS)
    write_csv(output_dir / "atomic_rule_quality_report.csv", rule_quality, ATOMIC_RULE_QUALITY_COLUMNS)
    write_csv(output_dir / "coverage_gap_report.csv", coverage_gaps, COVERAGE_GAP_COLUMNS)

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "annotator_gold": str(args.annotator_gold or ""),
        "atomic_rule_audit": str(args.atomic_rule_audit or ""),
        "visual_findings": str(args.visual_findings or ""),
        "gold_rows": len(gold_rows),
        "audit_rows": len(audit_rows),
        "visual_finding_rows": len(visual_rows),
        "verified_gold_rows": len(verified),
        "excluded_gold_rows": len(excluded),
        "coverage_gap_rows": len(coverage_gaps),
        "audit_validity_counts": dict(sorted(Counter(row.get("rule_validity", "") for row in audit_rows).items())),
        "outputs": [
            "verified_evaluation_gold.csv",
            "excluded_gold_rows.csv",
            "atomic_rule_quality_report.csv",
            "coverage_gap_report.csv",
        ],
    }
    write_json(output_dir / "summary.json", summary)
    print(json.dumps({"status": "finished", **summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
