"""Post-process tolerated color-family false positives in pilot results.

This script is intentionally offline: it reads normalized pilot verification
JSON files, writes adjusted copies, and produces a before/after comparison
report. Raw model outputs are left untouched.

Example:
    python -m vlm.scripts.supervise.postprocess_color_family_verdicts
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from typing import Any


DEFAULT_POSITIVE_RESULTS = Path("vlm/data/pilot_results/positive_qwen37plus_balanced_frozen_c6/cov")
DEFAULT_NEGATIVE_RESULTS = Path("vlm/data/pilot_results/negative_qwen37plus_balanced_c6/cov")
DEFAULT_NEGATIVE_MANIFEST = Path("vlm/data/pilot_negative_examples/negative_manifest.json")
DEFAULT_OUTPUT_ROOT = Path("vlm/data/pilot_results/postprocessed_color_family")
DEFAULT_REPORT_PATH = Path("vlm/data/pilot_results/comparison_report.json")

RULE_NAME = "tolerated_color_family_v1"

COLOR_ALIASES: dict[str, str] = {
    "深蓝黑": "black",
    "深紫黑": "black",
    "蓝黑": "black",
    "紫黑": "black",
    "黑色": "black",
    "黑": "black",
    "深灰色": "dark_gray",
    "深灰": "dark_gray",
    "灰黑色": "dark_gray",
    "灰黑": "dark_gray",
    "灰褐色": "gray_brown",
    "灰棕色": "gray_brown",
    "灰棕": "gray_brown",
    "红棕色": "red_brown",
    "红棕": "red_brown",
    "深棕色": "dark_brown",
    "深棕": "dark_brown",
    "浅棕色": "light_brown",
    "浅棕": "light_brown",
    "棕色": "brown",
    "棕": "brown",
    "卡其色": "khaki",
    "卡其": "khaki",
    "驼色": "tan",
    "米棕色": "tan",
    "米棕": "tan",
    "玫红色": "rose",
    "玫红": "rose",
    "粉红色": "pink",
    "粉红": "pink",
    "浅粉色": "pink",
    "浅粉": "pink",
    "粉色": "pink",
    "粉": "pink",
    "鲜红色": "red",
    "鲜红": "red",
    "红色": "red",
    "红": "red",
    "银白色": "silver",
    "银白": "silver",
    "银色": "silver",
    "银": "silver",
    "浅灰色": "light_gray",
    "浅灰": "light_gray",
    "灰色": "gray",
    "灰": "gray",
    "白色": "white",
    "白": "white",
    "青绿色": "blue_green",
    "蓝绿色": "blue_green",
    "蓝绿": "blue_green",
    "青色": "cyan",
    "青": "cyan",
    "蓝色": "blue",
    "蓝": "blue",
    "黄绿色": "yellow_green",
    "黄绿": "yellow_green",
    "绿色": "green",
    "绿": "green",
    "紫红色": "purple_red",
    "紫红": "purple_red",
    "紫色": "purple",
    "紫": "purple",
    "黄色": "yellow",
    "黄": "yellow",
    "金色": "gold",
    "金": "gold",
    "橙色": "orange",
    "橙": "orange",
    "red-brown": "red_brown",
    "reddish brown": "red_brown",
    "dark brown": "dark_brown",
    "light brown": "light_brown",
    "gray-brown": "gray_brown",
    "grey-brown": "gray_brown",
    "dark gray": "dark_gray",
    "dark grey": "dark_gray",
    "light gray": "light_gray",
    "light grey": "light_gray",
    "rose": "rose",
    "pink": "pink",
    "red": "red",
    "brown": "brown",
    "khaki": "khaki",
    "tan": "tan",
    "black": "black",
    "gray": "gray",
    "grey": "gray",
    "white": "white",
    "silver": "silver",
    "blue-green": "blue_green",
    "cyan": "cyan",
    "blue": "blue",
    "yellow-green": "yellow_green",
    "green": "green",
}

TOLERATED_COLOR_GROUPS = [
    {"red", "pink", "rose", "red_brown"},
    {"red", "brown", "red_brown", "dark_brown", "light_brown", "khaki", "tan"},
    {"black", "dark_gray", "gray_brown", "dark_brown", "brown"},
    {"white", "silver", "light_gray", "gray"},
    {"blue", "cyan", "blue_green"},
    {"green", "yellow_green"},
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post-process tolerated color-family false positives.")
    parser.add_argument("--positive-results", type=Path, default=DEFAULT_POSITIVE_RESULTS)
    parser.add_argument("--negative-results", type=Path, default=DEFAULT_NEGATIVE_RESULTS)
    parser.add_argument("--negative-manifest", type=Path, default=DEFAULT_NEGATIVE_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def result_files(results_dir: Path) -> list[Path]:
    if not results_dir.exists():
        raise SystemExit(f"Results directory not found: {results_dir}")
    paths = []
    for path in sorted(results_dir.glob("*.json")):
        if path.name.endswith("_request_redacted.json") or path.name.endswith("_error.json"):
            continue
        try:
            payload = read_json(path)
        except json.JSONDecodeError:
            continue
        if payload.get("schema_version") == "pilot_verification.v1" and isinstance(payload.get("elements"), list):
            paths.append(path)
    return paths


def extract_color_families(text: str) -> set[str]:
    normalized = text.lower()
    families = set()
    occupied: list[range] = []
    for token, family in sorted(COLOR_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        search_from = 0
        lowered_token = token.lower()
        while True:
            start = normalized.find(lowered_token, search_from)
            if start == -1:
                break
            span = range(start, start + len(lowered_token))
            search_from = start + len(lowered_token)
            if any(start < existing.stop and span.stop > existing.start for existing in occupied):
                continue
            occupied.append(span)
            families.add(family)
            break
    return families


def is_tolerated_family_set(families: set[str]) -> bool:
    if len(families) < 2:
        return False
    if {"red", "brown"}.issubset(families) and "red_brown" not in families:
        return False
    if {"black", "brown"}.issubset(families) and families.isdisjoint({"dark_gray", "gray_brown", "dark_brown"}):
        return False
    return any(families.issubset(group) for group in TOLERATED_COLOR_GROUPS)


def should_downgrade_color_wrong(element: dict[str, Any]) -> tuple[bool, set[str]]:
    if str(element.get("verdict", "")).strip().lower() != "wrong":
        return False, set()
    if str(element.get("issue_type", "")).strip().lower() != "color":
        return False, set()

    judgment_text = " ".join([
        str(element.get("reason", "")),
        str(element.get("evidence", "")),
    ])
    families = extract_color_families(judgment_text)

    if len(families) < 2:
        fallback_text = " ".join([
            str(element.get("name", "")),
            str(element.get("expected_value", "")),
            judgment_text,
        ])
        families = extract_color_families(fallback_text)

    return is_tolerated_family_set(families), families


def recompute_summary(result: dict[str, Any]) -> None:
    elements = result.get("elements", [])
    result["summary"] = {
        "correct": sum(1 for item in elements if item.get("verdict") == "correct"),
        "wrong": sum(1 for item in elements if item.get("verdict") == "wrong"),
        "uncertain": sum(1 for item in elements if item.get("verdict") == "uncertain"),
    }


def adjusted_result(result: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    adjusted = deepcopy(result)
    downgraded = []
    for element in adjusted.get("elements", []):
        should_downgrade, families = should_downgrade_color_wrong(element)
        if not should_downgrade:
            continue
        original_verdict = element.get("verdict")
        original_issue_type = element.get("issue_type")
        element["verdict"] = "correct"
        element["issue_type"] = None
        element["postprocess"] = {
            "color_family_downgraded": True,
            "rule": RULE_NAME,
            "matched_color_families": sorted(families),
            "original_verdict": original_verdict,
            "original_issue_type": original_issue_type,
        }
        downgraded.append({
            "sample_id": adjusted.get("sample_id", ""),
            "element_id": element.get("element_id", ""),
            "name": element.get("name", ""),
            "matched_color_families": sorted(families),
            "reason": element.get("reason", ""),
            "evidence": element.get("evidence", ""),
        })

    recompute_summary(adjusted)
    metadata = adjusted.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["postprocess"] = {
            "rule": RULE_NAME,
            "color_family_downgraded_count": len(downgraded),
        }
    return adjusted, downgraded


def element_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for result in results:
        for element in result.get("elements", []):
            counts[str(element.get("verdict", "unknown"))] += 1
    return {
        "elements": sum(counts.values()),
        "correct": counts.get("correct", 0),
        "wrong": counts.get("wrong", 0),
        "uncertain": counts.get("uncertain", 0),
    }


def issue_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for result in results:
        for element in result.get("elements", []):
            if element.get("verdict") == "wrong":
                counts[str(element.get("issue_type") or "null")] += 1
    return dict(sorted(counts.items()))


def load_adjust_write(results_dir: Path, output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    before_results = []
    after_results = []
    downgraded_items = []
    for path in result_files(results_dir):
        result = read_json(path)
        adjusted, downgraded = adjusted_result(result)
        before_results.append(result)
        after_results.append(adjusted)
        downgraded_items.extend(downgraded)
        write_json(output_dir / path.name, adjusted)
    return before_results, after_results, downgraded_items


def target_element_id(negative_sample_id: str, mutated_element_index: int) -> str:
    return f"{negative_sample_id}_e{mutated_element_index:03d}"


def find_element(result_by_sample: dict[str, dict[str, Any]], sample_id: str, element_id: str) -> dict[str, Any] | None:
    result = result_by_sample.get(sample_id)
    if not result:
        return None
    for element in result.get("elements", []):
        if element.get("element_id") == element_id:
            return element
    return None


def manifest_aligned_metrics(results: list[dict[str, Any]], manifest_path: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    mutations = manifest.get("mutations", [])
    result_by_sample = {str(result.get("sample_id", "")): result for result in results}

    total = 0
    target_caught = 0
    issue_matched = 0
    caught_by_issue = Counter()
    total_by_issue = Counter()
    missed_targets = []
    issue_mismatches = []
    extra_wrong_elements = []

    for mutation in mutations:
        sample_id = str(mutation.get("negative_sample_id", ""))
        issue_type = str(mutation.get("expected_issue_type", ""))
        element_id = target_element_id(sample_id, int(mutation.get("mutated_element_index", 0)))
        total += 1
        total_by_issue[issue_type] += 1
        element = find_element(result_by_sample, sample_id, element_id)
        if not element:
            missed_targets.append({"sample_id": sample_id, "element_id": element_id, "reason": "result or element missing"})
            continue
        if element.get("verdict") == "wrong":
            target_caught += 1
            caught_by_issue[issue_type] += 1
            if element.get("issue_type") == issue_type:
                issue_matched += 1
            else:
                issue_mismatches.append({
                    "sample_id": sample_id,
                    "element_id": element_id,
                    "expected_issue_type": issue_type,
                    "actual_issue_type": element.get("issue_type"),
                })
        else:
            missed_targets.append({
                "sample_id": sample_id,
                "element_id": element_id,
                "expected_issue_type": issue_type,
                "actual_verdict": element.get("verdict"),
            })

        result = result_by_sample.get(sample_id, {})
        for candidate in result.get("elements", []):
            if candidate.get("element_id") == element_id:
                continue
            if candidate.get("verdict") == "wrong":
                extra_wrong_elements.append({
                    "sample_id": sample_id,
                    "element_id": candidate.get("element_id", ""),
                    "issue_type": candidate.get("issue_type"),
                    "reason": candidate.get("reason", ""),
                })

    return {
        "target_caught": target_caught,
        "target_total": total,
        "issue_matched": issue_matched,
        "caught_by_issue": {issue: caught_by_issue.get(issue, 0) for issue in sorted(total_by_issue)},
        "total_by_issue": dict(sorted(total_by_issue.items())),
        "extra_wrong_count": len(extra_wrong_elements),
        "extra_wrong_elements": extra_wrong_elements,
        "missed_targets": missed_targets,
        "issue_mismatches": issue_mismatches,
    }


def dataset_report(
    *,
    label: str,
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    downgraded_items: list[dict[str, Any]],
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    report = {
        "label": label,
        "samples": len(before),
        "before": {
            "verdict_counts": element_counts(before),
            "wrong_issue_counts": issue_counts(before),
        },
        "after": {
            "verdict_counts": element_counts(after),
            "wrong_issue_counts": issue_counts(after),
        },
        "downgraded_count": len(downgraded_items),
        "downgraded_items": downgraded_items,
    }
    if manifest_path is not None:
        report["manifest_aligned_before"] = manifest_aligned_metrics(before, manifest_path)
        report["manifest_aligned_after"] = manifest_aligned_metrics(after, manifest_path)
    return report


def main() -> None:
    args = parse_args()

    positive_output = args.output_root / args.positive_results.parent.name / args.positive_results.name
    negative_output = args.output_root / args.negative_results.parent.name / args.negative_results.name

    positive_before, positive_after, positive_downgraded = load_adjust_write(args.positive_results, positive_output)
    negative_before, negative_after, negative_downgraded = load_adjust_write(args.negative_results, negative_output)

    report = {
        "schema_version": "pilot_color_family_postprocess_report.v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "rule": RULE_NAME,
        "inputs": {
            "positive_results": str(args.positive_results),
            "negative_results": str(args.negative_results),
            "negative_manifest": str(args.negative_manifest),
        },
        "outputs": {
            "positive_adjusted_results": str(positive_output),
            "negative_adjusted_results": str(negative_output),
            "report_path": str(args.report_path),
        },
        "positive": dataset_report(
            label="positive_qwen37plus_balanced_frozen_c6",
            before=positive_before,
            after=positive_after,
            downgraded_items=positive_downgraded,
        ),
        "negative": dataset_report(
            label="negative_qwen37plus_balanced_c6",
            before=negative_before,
            after=negative_after,
            downgraded_items=negative_downgraded,
            manifest_path=args.negative_manifest,
        ),
    }
    write_json(args.report_path, report)
    print(json.dumps({
        "status": "ok",
        "rule": RULE_NAME,
        "positive_downgraded": len(positive_downgraded),
        "negative_downgraded": len(negative_downgraded),
        "report_path": str(args.report_path),
        "positive_adjusted_results": str(positive_output),
        "negative_adjusted_results": str(negative_output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
