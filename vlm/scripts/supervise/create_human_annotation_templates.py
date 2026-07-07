"""Create CSV templates for pre-gold human annotation workflow.

The templates are generated from Qwen sample config files and each sample's
atomic_rules.json. They can be sent to annotators or used as import contracts
before real annotation data comes back.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("vlm/tmp/human_annotation_templates")

VISUAL_FINDINGS_COLUMNS = [
    "sample_id",
    "category",
    "finding_id",
    "human_rule_name",
    "element_name",
    "attribute",
    "view",
    "bbox_2d",
    "bbox_multiview",
    "visible",
    "status",
    "match_status",
    "issue_type",
    "feature_key",
    "expected_value",
    "observed_value",
    "expected_from_2d",
    "observed_in_multiview",
    "severity",
    "source_2d_evidence",
    "multiview_evidence",
    "matched_rule_id",
    "reason",
    "annotator_id",
    "annotation_batch",
]

ANNOTATOR_GOLD_COLUMNS = [
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
    "evidence",
    "annotator_id",
    "annotation_batch",
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create human annotation CSV templates.")
    parser.add_argument(
        "--sample-config",
        type=Path,
        action="append",
        required=True,
        help="Qwen sample config JSON. Can be passed multiple times.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--per-sample",
        action="store_true",
        help="Also write templates under output_dir/by_sample/{category}/{sample_id}/.",
    )
    return parser.parse_args()


def read_sample_configs(paths: list[Path]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        raw_samples = data if isinstance(data, list) else data.get("samples", [])
        for sample in raw_samples:
            sample_id = str(sample.get("sample_id", "")).strip()
            category = str(sample.get("category", "")).strip()
            key = (category, sample_id)
            if not sample_id or key in seen:
                continue
            seen.add(key)
            samples.append(sample)
    return samples


def load_atomic_rules(path: Path) -> list[dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    raw_rules = data.get("atomic_rules", data) if isinstance(data, dict) else data
    rules: list[dict[str, str]] = []
    if not isinstance(raw_rules, list):
        return rules
    for item in raw_rules:
        if not isinstance(item, dict):
            continue
        rule_id = str(item.get("rule_id") or item.get("id") or item.get("name") or "").strip()
        if not rule_id:
            continue
        value = item.get("value", "")
        rules.append(
            {
                "rule_id": rule_id,
                "rule_key": rule_id,
                "atomic_value": str(value),
            }
        )
    return rules


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def template_rows(samples: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    visual_rows: list[dict[str, Any]] = []
    gold_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []

    for sample in samples:
        sample_id = str(sample["sample_id"])
        category = str(sample.get("category", ""))
        rules = load_atomic_rules(Path(sample["atomic_rules"]))
        manifest.append(
            {
                "sample_id": sample_id,
                "category": category,
                "source_image": sample.get("source_image", ""),
                "multiview_image": sample.get("multiview_image", ""),
                "atomic_rules": sample.get("atomic_rules", ""),
                "rule_count": len(rules),
            }
        )
        visual_rows.append(
            {
                "sample_id": sample_id,
                "category": category,
                "finding_id": "",
                "severity": "unknown",
            }
        )
        for rule in rules:
            gold_rows.append(
                {
                    "sample_id": sample_id,
                    "category": category,
                    "rule_id": rule["rule_id"],
                    "value": rule["atomic_value"],
                }
            )
            audit_rows.append(
                {
                    "sample_id": sample_id,
                    "category": category,
                    "rule_id": rule["rule_id"],
                    "rule_key": rule["rule_key"],
                    "atomic_value": rule["atomic_value"],
                }
            )
    return visual_rows, gold_rows, audit_rows, manifest


def write_per_sample_templates(output_dir: Path, samples: list[dict[str, Any]]) -> None:
    for sample in samples:
        sample_id = str(sample["sample_id"])
        category = str(sample.get("category", ""))
        visual_rows, gold_rows, audit_rows, _ = template_rows([sample])
        sample_dir = output_dir / "by_sample" / category / sample_id
        write_csv(sample_dir / "human_visual_findings.csv", visual_rows, VISUAL_FINDINGS_COLUMNS)
        write_csv(sample_dir / "annotator_gold.csv", gold_rows, ANNOTATOR_GOLD_COLUMNS)
        write_csv(sample_dir / "atomic_rule_audit.csv", audit_rows, ATOMIC_RULE_AUDIT_COLUMNS)


def main() -> None:
    args = parse_args()
    samples = read_sample_configs(args.sample_config)
    visual_rows, gold_rows, audit_rows, manifest = template_rows(samples)
    output_dir = args.output_dir

    write_csv(output_dir / "human_visual_findings_template.csv", visual_rows, VISUAL_FINDINGS_COLUMNS)
    write_csv(output_dir / "annotator_gold_template.csv", gold_rows, ANNOTATOR_GOLD_COLUMNS)
    write_csv(output_dir / "atomic_rule_audit_template.csv", audit_rows, ATOMIC_RULE_AUDIT_COLUMNS)
    write_csv(
        output_dir / "template_manifest.csv",
        manifest,
        ["sample_id", "category", "source_image", "multiview_image", "atomic_rules", "rule_count"],
    )
    if args.per_sample:
        write_per_sample_templates(output_dir, samples)

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "sample_configs": [str(path) for path in args.sample_config],
        "samples": len(samples),
        "visual_template_rows": len(visual_rows),
        "gold_template_rows": len(gold_rows),
        "audit_template_rows": len(audit_rows),
        "per_sample": bool(args.per_sample),
        "outputs": [
            "human_visual_findings_template.csv",
            "annotator_gold_template.csv",
            "atomic_rule_audit_template.csv",
            "template_manifest.csv",
        ],
    }
    write_json(output_dir / "summary.json", summary)
    print(json.dumps({"status": "finished", **summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
