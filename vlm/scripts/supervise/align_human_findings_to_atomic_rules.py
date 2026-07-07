"""Generate deterministic candidates from human findings to atomic rules.

This is a pre-gold alignment helper. It does not rewrite gold data and does not
claim final semantic equivalence. It only proposes candidates that a later human
review or LLM-assisted text-only step can accept, reject, or refine.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("vlm/tmp/human_to_atomic_rule_alignment")

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "color",
    "colour",
    "has",
    "have",
    "is",
    "of",
    "the",
    "type",
    "value",
    "with",
}

TOKEN_ALIASES = {
    "bang": "bangs",
    "bows": "bow",
    "cloth": "clothing",
    "clothes": "clothing",
    "colour": "color",
    "eyes": "eye",
    "glasses": "glasses",
    "hat": "headwear",
    "hoodie": "hood",
    "ribbons": "ribbon",
    "shoe": "footwear",
    "shoes": "footwear",
    "sock": "legwear",
    "socks": "legwear",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Align human visual findings to atomic rule candidates.")
    parser.add_argument("--visual-findings", type=Path, required=True, help="human_visual_findings.csv")
    parser.add_argument(
        "--sample-config",
        type=Path,
        action="append",
        required=True,
        help="Qwen sample config JSON. Can be passed multiple times.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-score", type=float, default=0.18)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
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


def load_sample_registry(sample_configs: list[Path]) -> dict[tuple[str, str], list[dict[str, str]]]:
    registry: dict[tuple[str, str], list[dict[str, str]]] = {}
    for config_path in sample_configs:
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
        samples = data if isinstance(data, list) else data.get("samples", [])
        for sample in samples:
            sample_id = str(sample.get("sample_id", "")).strip()
            category = str(sample.get("category", "")).strip()
            if not sample_id:
                continue
            registry[(category, sample_id)] = load_atomic_rules(Path(sample["atomic_rules"]))
    return registry


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
        rules.append({"rule_id": rule_id, "atomic_value": str(value)})
    return rules


def tokens(text: str) -> set[str]:
    raw = re.split(r"[^A-Za-z0-9]+", text.lower())
    output: set[str] = set()
    for token in raw:
        if not token or token in STOPWORDS:
            continue
        output.add(TOKEN_ALIASES.get(token, token))
    return output


def finding_text(row: dict[str, str]) -> str:
    parts = [
        row.get("human_rule_name", ""),
        row.get("element_name", ""),
        row.get("feature_key", ""),
        row.get("attribute", ""),
        row.get("expected_value", ""),
        row.get("expected_from_2d", ""),
        row.get("observed_value", ""),
        row.get("observed_in_multiview", ""),
        row.get("issue_type", ""),
    ]
    return " ".join(part for part in parts if part)


def score_candidate(finding: dict[str, str], rule: dict[str, str]) -> tuple[float, str]:
    human_text = finding_text(finding)
    rule_text = f"{rule['rule_id']} {rule.get('atomic_value', '')}"
    human_tokens = tokens(human_text)
    rule_tokens = tokens(rule_text)
    if not human_tokens or not rule_tokens:
        return 0.0, "empty_tokens"

    overlap = len(human_tokens & rule_tokens)
    union = len(human_tokens | rule_tokens)
    jaccard = overlap / union if union else 0.0
    sequence = difflib.SequenceMatcher(None, human_text.lower(), rule_text.lower()).ratio()
    value_bonus = 0.0
    expected = (finding.get("expected_value") or finding.get("expected_from_2d") or "").lower()
    atomic_value = rule.get("atomic_value", "").lower()
    if expected and atomic_value and expected in atomic_value:
        value_bonus = 0.15
    score = round((jaccard * 0.65) + (sequence * 0.25) + value_bonus, 4)
    reason = f"token_overlap={overlap};jaccard={jaccard:.3f};sequence={sequence:.3f};value_bonus={value_bonus:.2f}"
    return score, reason


def candidate_type(score: float, human_tokens: set[str], rule_tokens: set[str]) -> str:
    if score >= 0.86:
        return "exact_match_candidate"
    if score >= 0.55:
        return "semantic_equivalent_candidate"
    if human_tokens <= rule_tokens or rule_tokens <= human_tokens:
        return "broader_or_narrower_candidate"
    if score >= 0.25:
        return "related_candidate"
    return "low_confidence_candidate"


def align_rows(
    findings: list[dict[str, str]],
    registry: dict[tuple[str, str], list[dict[str, str]]],
    top_k: int,
    min_score: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    review_queue: list[dict[str, Any]] = []

    for row in findings:
        sample_id = row.get("sample_id", "")
        category = row.get("category", "")
        finding_id = row.get("finding_id", "")
        rules = registry.get((category, sample_id)) or registry.get(("", sample_id)) or []
        if not rules:
            no_match = candidate_row(row, "", "", 0.0, "no_atomic_rules_for_sample", "no_match_candidate", True)
            candidates.append(no_match)
            review_queue.append(no_match)
            continue

        scored: list[dict[str, Any]] = []
        human_tokens = tokens(finding_text(row))
        for rule in rules:
            score, reason = score_candidate(row, rule)
            rule_tokens = tokens(f"{rule['rule_id']} {rule.get('atomic_value', '')}")
            if score >= min_score:
                scored.append(
                    candidate_row(
                        row,
                        rule["rule_id"],
                        rule.get("atomic_value", ""),
                        score,
                        reason,
                        candidate_type(score, human_tokens, rule_tokens),
                        score < 0.55,
                    )
                )
        scored.sort(key=lambda item: item["mapping_score"], reverse=True)
        kept = scored[:top_k]
        if not kept:
            no_match = candidate_row(row, "", "", 0.0, "no_candidate_above_min_score", "no_match_candidate", True)
            candidates.append(no_match)
            review_queue.append(no_match)
            continue
        candidates.extend(kept)
        for item in kept:
            if item["needs_review"] == "true" or item["candidate_match_type"] != "exact_match_candidate":
                review_queue.append(item)

        if finding_id and sum(1 for item in kept if item["mapping_score"] >= 0.55) > 1:
            for item in kept:
                item["warnings"] = append_warning(str(item.get("warnings", "")), "multiple_high_confidence_candidates")

    return candidates, review_queue


def candidate_row(
    finding: dict[str, str],
    atomic_rule_id: str,
    atomic_rule_value: str,
    score: float,
    reason: str,
    match_type: str,
    needs_review: bool,
) -> dict[str, Any]:
    return {
        "sample_id": finding.get("sample_id", ""),
        "category": finding.get("category", ""),
        "human_finding_id": finding.get("finding_id", ""),
        "human_rule_name": finding.get("human_rule_name") or finding.get("feature_key", ""),
        "human_element_name": finding.get("element_name") or finding.get("feature_key", ""),
        "human_attribute": finding.get("attribute", ""),
        "human_value": finding.get("expected_value") or finding.get("expected_from_2d", ""),
        "atomic_rule_id": atomic_rule_id,
        "atomic_rule_value": atomic_rule_value,
        "candidate_match_type": match_type,
        "mapping_score": score,
        "mapping_reason": reason,
        "needs_review": "true" if needs_review else "false",
        "warnings": "",
    }


def append_warning(current: str, warning: str) -> str:
    if not current:
        return warning
    if warning in current.split(";"):
        return current
    return current + ";" + warning


def summarize_candidates(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, int] = defaultdict(int)
    for row in candidates:
        by_type[str(row.get("candidate_match_type", ""))] += 1
    return dict(sorted(by_type.items()))


def main() -> None:
    args = parse_args()
    findings = read_csv(args.visual_findings)
    registry = load_sample_registry(args.sample_config)
    candidates, review_queue = align_rows(findings, registry, args.top_k, args.min_score)

    output_dir = args.output_dir
    columns = [
        "sample_id",
        "category",
        "human_finding_id",
        "human_rule_name",
        "human_element_name",
        "human_attribute",
        "human_value",
        "atomic_rule_id",
        "atomic_rule_value",
        "candidate_match_type",
        "mapping_score",
        "mapping_reason",
        "needs_review",
        "warnings",
    ]
    write_csv(output_dir / "human_to_atomic_rule_mapping_candidates.csv", candidates, columns)
    write_csv(output_dir / "mapping_review_queue.csv", review_queue, columns)

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "visual_findings": str(args.visual_findings),
        "sample_configs": [str(path) for path in args.sample_config],
        "findings": len(findings),
        "known_samples": len(registry),
        "candidate_rows": len(candidates),
        "review_queue_rows": len(review_queue),
        "candidate_type_counts": summarize_candidates(candidates),
    }
    write_json(output_dir / "summary.json", summary)
    print(json.dumps({"status": "finished", **summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
