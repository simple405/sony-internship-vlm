"""Summarize pre-gold supervision assets and blocked evaluation steps.

This script is deliberately descriptive: it inventories sample configs,
annotation CSVs, mapping candidates, verified gold, and Qwen prediction caches
when present. It does not require human gold data or Qwen API quota.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("vlm/tmp/pre_gold_asset_summary")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize pre-gold supervision assets.")
    parser.add_argument("--sample-config", type=Path, action="append", default=[], help="Sample config JSON.")
    parser.add_argument("--visual-findings", type=Path, help="human_visual_findings.csv")
    parser.add_argument("--atomic-rule-audit", type=Path, help="atomic_rule_audit.csv")
    parser.add_argument("--mapping-candidates", type=Path, help="human_to_atomic_rule_mapping_candidates.csv")
    parser.add_argument("--verified-gold", type=Path, help="verified_evaluation_gold.csv")
    parser.add_argument("--qwen-output-root", type=Path, default=Path("vlm/tmp/multicategory_supervision_review_v3"))
    parser.add_argument("--qwen-quota-blocked", action="store_true", help="Mark Qwen batch prediction as quota-blocked.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def read_csv_rows(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def read_sample_configs(paths: list[Path]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        raw_samples = data if isinstance(data, list) else data.get("samples", [])
        for sample in raw_samples:
            item = dict(sample)
            item["sample_config"] = str(path)
            samples.append(item)
    return samples


def qwen_prediction_inventory(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for summary_path in sorted(root.glob("*/*/summary.json")):
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        rows.append(
            {
                "category": summary.get("category", summary_path.parent.parent.name),
                "sample_id": summary.get("sample_id", summary_path.parent.name.split("_v3_")[0]),
                "output_dir": str(summary_path.parent),
                "model_name": summary.get("model_name", ""),
                "requested_rule_count": summary.get("requested_rule_count", ""),
                "returned_rule_count": summary.get("returned_rule_count", ""),
                "qc_pass": summary.get("qc_counts", {}).get("PASS", ""),
                "qc_warn": summary.get("qc_counts", {}).get("WARN", ""),
                "qc_fail": summary.get("qc_counts", {}).get("FAIL", ""),
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def category_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get("category", "")) for row in rows).items()))


def blocked_steps(args: argparse.Namespace, visual_rows: list[dict[str, str]], audit_rows: list[dict[str, str]], verified_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not visual_rows:
        rows.append({"step": "final coverage/generation quality metrics", "blocked_by": "human_visual_findings not received"})
    if not audit_rows:
        rows.append({"step": "atomic rule quality metrics", "blocked_by": "atomic_rule_audit not received"})
    if not verified_rows:
        rows.append({"step": "Qwen accuracy against verified gold", "blocked_by": "verified_evaluation_gold not built"})
    if args.qwen_quota_blocked:
        rows.append({"step": "expanded Qwen baseline prediction", "blocked_by": "Qwen API quota unavailable"})
    return rows


def main() -> None:
    args = parse_args()
    samples = read_sample_configs(args.sample_config)
    visual_rows = read_csv_rows(args.visual_findings)
    audit_rows = read_csv_rows(args.atomic_rule_audit)
    mapping_rows = read_csv_rows(args.mapping_candidates)
    verified_rows = read_csv_rows(args.verified_gold)
    qwen_rows = qwen_prediction_inventory(args.qwen_output_root)
    blocked = blocked_steps(args, visual_rows, audit_rows, verified_rows)

    output_dir = args.output_dir
    write_csv(
        output_dir / "sample_config_inventory.csv",
        samples,
        ["sample_config", "sample_id", "category", "source_image", "multiview_image", "atomic_rules"],
    )
    write_csv(
        output_dir / "qwen_prediction_inventory.csv",
        qwen_rows,
        ["category", "sample_id", "output_dir", "model_name", "requested_rule_count", "returned_rule_count", "qc_pass", "qc_warn", "qc_fail"],
    )
    write_csv(output_dir / "blocked_steps.csv", blocked, ["step", "blocked_by"])

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "sample_configs": [str(path) for path in args.sample_config],
        "samples": len(samples),
        "sample_category_counts": category_counts(samples),
        "visual_finding_rows": len(visual_rows),
        "atomic_rule_audit_rows": len(audit_rows),
        "mapping_candidate_rows": len(mapping_rows),
        "verified_gold_rows": len(verified_rows),
        "qwen_prediction_runs": len(qwen_rows),
        "qwen_quota_blocked": bool(args.qwen_quota_blocked),
        "blocked_steps": blocked,
    }
    write_json(output_dir / "summary.json", summary)
    print(json.dumps({"status": "finished", **summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
