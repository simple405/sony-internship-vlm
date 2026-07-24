"""Post-process tolerated color-family false positives in pilot results.

Why this script runs offline
-----------------------------
The main VLM verification pipeline flags any color mismatch as a "wrong" verdict.
However, adjacent color families (e.g. red vs. pink, or dark brown vs. black) are
perceptually similar and often represent a genuine ambiguity between the 2D source
image and the physical merchandise, rather than a manufacturing defect. Folding this
correction into the live pipeline would require the VLM to reason about color
semantics at call time, which is unreliable and adds latency.

Running this as an offline post-processing step instead means:
  1. The raw VLM output is always preserved and left untouched.
  2. The correction logic is deterministic and auditable.
  3. The exact set of tolerated families can be tuned and re-run without
     re-querying the model.
  4. The before/after comparison report makes the impact immediately visible.

This script reads normalized pilot verification JSON files (schema_version =
"pilot_verification.v1"), writes adjusted copies, and produces a before/after
comparison report. Raw model outputs are left untouched.

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
    """Parse CLI arguments for the color-family post-processing script.

    Returns:
        Parsed namespace with fields:
          positive_results   -- directory of positive-example pilot result JSONs
          negative_results   -- directory of negative-example pilot result JSONs
          negative_manifest  -- negative_manifest.json mapping mutations to samples
          output_root        -- root directory for adjusted output JSONs
          report_path        -- path for the before/after comparison report JSON
    """
    parser.add_argument("--positive-results", type=Path, default=DEFAULT_POSITIVE_RESULTS)
    parser.add_argument("--negative-results", type=Path, default=DEFAULT_NEGATIVE_RESULTS)
    parser.add_argument("--negative-manifest", type=Path, default=DEFAULT_NEGATIVE_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


def read_json(path: Path) -> Any:
    """Read and parse a UTF-8-with-BOM JSON file.

    Args:
        path: Absolute path to a JSON file.

    Returns:
        Parsed Python object (dict, list, etc.).
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    """Write payload as pretty-printed UTF-8 JSON (no ASCII escaping).

    Creates parent directories if they don't exist.

    Args:
        path: Destination file path.
        payload: Any JSON-serialisable value.
    """
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def result_files(results_dir: Path) -> list[Path]:
    """Find all valid pilot verification result JSON files in the results directory.

    Filters out request previews (_request_redacted.json) and error files
    (_error.json). Only includes files with schema_version="pilot_verification.v1"
    and a non-empty "elements" list.

    Args:
        results_dir: Directory containing pilot result JSON files.

    Returns:
        Sorted list of Path objects for valid result files.

    Raises:
        SystemExit: If results_dir does not exist.
    """
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
    """Extract canonical color family names from free-form text with overlap tracking.

    The overlap-tracking algorithm prevents double-counting when a long color
    phrase like "深蓝黑" (deep blue-black) contains multiple shorter color tokens.
    Example: "深蓝黑" should match only "深蓝黑"→black, not both "深蓝黑" and "蓝黑".

    Algorithm:
      1. Sort COLOR_ALIASES by token length descending (longest tokens first).
      2. For each token, search for all occurrences in the lowercased text.
      3. For each match, check if its character span overlaps with any previously-
         matched span in the `occupied` list.
      4. If no overlap, record the span as occupied and add the family to the result set.
      5. Break after the first non-overlapping match for this token (greedy left-to-right).

    This ensures that "红棕色 vs 红色" extracts {red_brown, red}, not just {red, red}.

    Args:
        text: Free-form text (may contain Chinese or English color terms).

    Returns:
        Set of canonical color family names (from COLOR_ALIASES values).
    """
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
    """Check if a set of color families represents a tolerated adjacent-color ambiguity.

    Special-case guards (why certain combinations are NOT tolerated):

    1. red + brown WITHOUT red_brown:
       If the model judgment text mentions both "red" and "brown" but NOT
       "red_brown" (reddish brown), this is likely describing two separate
       features (e.g. "red shirt, brown pants") rather than one ambiguous
       red-brown element. NOT tolerated because it's probably a multi-element
       judgment incorrectly written in a single element row.

    2. black + brown WITHOUT any gray/dark tone:
       If the model says "black" and "brown" but doesn't mention dark_gray,
       gray_brown, or dark_brown, this is likely a genuine error (black and
       brown are visually distinct unless mediated by a dark tone). Only
       tolerated if a transitional tone is mentioned.

    Tolerated groups (TOLERATED_COLOR_GROUPS):
      - {red, pink, rose, red_brown}: red-spectrum adjacency
      - {red, brown, red_brown, dark_brown, light_brown, khaki, tan}: brown-spectrum with red
      - {black, dark_gray, gray_brown, dark_brown, brown}: dark neutrals
      - {white, silver, light_gray, gray}: light neutrals
      - {blue, cyan, blue_green}: blue-spectrum
      - {green, yellow_green}: green-spectrum

    Args:
        families: Set of canonical color family names extracted from judgment text.

    Returns:
        True if the family set is entirely contained within one tolerated group
        and passes all special-case guards. False otherwise (hard color error).
    """
    if len(families) < 2:
        return False
    # Guard: red + brown must have red_brown to be tolerated
    if {"red", "brown"}.issubset(families) and "red_brown" not in families:
        return False
    # Guard: black + brown must have a dark-tone mediator to be tolerated
    if {"black", "brown"}.issubset(families) and families.isdisjoint({"dark_gray", "gray_brown", "dark_brown"}):
        return False
    return any(families.issubset(group) for group in TOLERATED_COLOR_GROUPS)


def should_downgrade_color_wrong(element: dict[str, Any]) -> tuple[bool, set[str]]:
    """Determine if a single element's "wrong color" verdict should be downgraded to "correct".

    Downgrade criteria:
      1. verdict == "wrong"
      2. issue_type == "color"
      3. Color families extracted from (reason + evidence) form a tolerated set.

    If the initial extraction from reason+evidence yields fewer than 2 families,
    falls back to extracting from (name + expected_value + reason + evidence) to
    catch cases where the color terms appear in the element name or expected_value
    rather than in the judgment text.

    Args:
        element: One element dict from result["elements"] (pilot_verification.v1 schema).

    Returns:
        Tuple (should_downgrade: bool, matched_families: set[str]).
        should_downgrade is True if the element passes all criteria.
        matched_families is the set of color family names extracted from the text.
    """
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
    """Recompute the result["summary"] verdict counts after adjusting elements.

    Counts are derived from the current state of result["elements"]. This is
    called after downgrading color-wrong elements to ensure the summary reflects
    the adjusted verdicts.

    Args:
        result: Result dict (pilot_verification.v1 schema) to update in-place.
    """
    elements = result.get("elements", [])
    result["summary"] = {
        "correct": sum(1 for item in elements if item.get("verdict") == "correct"),
        "wrong": sum(1 for item in elements if item.get("verdict") == "wrong"),
        "uncertain": sum(1 for item in elements if item.get("verdict") == "uncertain"),
    }


def adjusted_result(result: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Create an adjusted copy of a result with color-family downgrade applied.

    For each element that passes should_downgrade_color_wrong():
      - Change verdict from "wrong" to "correct"
      - Clear issue_type
      - Add postprocess metadata with original verdict, matched families, and rule name

    Recomputes the summary verdict counts after adjustment. Adds a postprocess
    metadata section to result["metadata"] recording the rule name and downgrade count.

    Args:
        result: Original result dict (pilot_verification.v1 schema).

    Returns:
        Tuple (adjusted_result, downgraded_items):
          adjusted_result  -- deep copy with color-family corrections applied
          downgraded_items -- list of item dicts for the comparison report
    """
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
    """Aggregate element-level verdict counts across all results.

    Args:
        results: List of result dicts (pilot_verification.v1 schema).

    Returns:
        Dict with keys: elements (total), correct, wrong, uncertain.
    """
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
    """Aggregate issue_type counts for all elements with verdict=="wrong".

    Args:
        results: List of result dicts (pilot_verification.v1 schema).

    Returns:
        Dict mapping issue_type strings to counts (sorted alphabetically).
        Includes "null" for elements with verdict=="wrong" but no issue_type.
    """
    counts = Counter()
    for result in results:
        for element in result.get("elements", []):
            if element.get("verdict") == "wrong":
                counts[str(element.get("issue_type") or "null")] += 1
    return dict(sorted(counts.items()))


def load_adjust_write(results_dir: Path, output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Load all result files from results_dir, adjust them, and write to output_dir.

    For each result file:
      1. Load the original JSON.
      2. Call adjusted_result() to produce the corrected version.
      3. Write the adjusted JSON to output_dir (preserving filename).
      4. Collect the original, adjusted, and downgraded items for the report.

    Args:
        results_dir: Directory containing original pilot result JSONs.
        output_dir: Directory where adjusted JSONs will be written.

    Returns:
        Tuple (before_results, after_results, downgraded_items):
          before_results    -- list of original result dicts
          after_results     -- list of adjusted result dicts
          downgraded_items  -- flat list of all downgraded element item dicts
    """
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
    """Build the element_id for a mutated element in a negative sample.

    Negative sample element IDs follow the convention: {sample_id}_e{index:03d}

    Args:
        negative_sample_id: Sample ID string from the negative manifest.
        mutated_element_index: 0-based element index (from mutation entry).

    Returns:
        Element ID string like "neg_sample_001_e002".
    """
    return f"{negative_sample_id}_e{mutated_element_index:03d}"


def find_element(result_by_sample: dict[str, dict[str, Any]], sample_id: str, element_id: str) -> dict[str, Any] | None:
    """Look up a single element dict by sample_id and element_id.

    Args:
        result_by_sample: Dict mapping sample_id -> result dict.
        sample_id: Sample ID to search.
        element_id: Element ID to search for within the sample's elements list.

    Returns:
        The element dict if found, or None if the sample or element is missing.
    """
    result = result_by_sample.get(sample_id)
    if not result:
        return None
    for element in result.get("elements", []):
        if element.get("element_id") == element_id:
            return element
    return None


def manifest_aligned_metrics(results: list[dict[str, Any]], manifest_path: Path) -> dict[str, Any]:
    """Compute negative-sample detection metrics aligned to the mutation manifest.

    The negative manifest lists every intentional mutation (expected issue).
    This function checks whether each mutation's target element was flagged as
    "wrong" by the model, and whether the issue_type matches the expected type.

    Metrics computed:
      - target_caught: count of mutations where target element verdict=="wrong"
      - target_total: total mutations in the manifest
      - issue_matched: count where both verdict=="wrong" AND issue_type matches
      - caught_by_issue: breakdown of target_caught by expected_issue_type
      - total_by_issue: breakdown of target_total by expected_issue_type
      - extra_wrong_count: count of non-target elements flagged as "wrong"
      - extra_wrong_elements: list of those elements (false positives)
      - missed_targets: list of mutations where target element was NOT flagged
      - issue_mismatches: list of mutations where target was caught but issue_type differs

    Args:
        results: List of result dicts (pilot_verification.v1 schema).
        manifest_path: Path to negative_manifest.json.

    Returns:
        Metrics dict with the structure described above.
    """
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
    """Build a before/after comparison report section for one dataset.

    Args:
        label: Human-readable label for the dataset (e.g. "positive_qwen37plus_balanced_frozen_c6").
        before: List of original result dicts.
        after: List of adjusted result dicts.
        downgraded_items: List of downgraded element item dicts.
        manifest_path: Optional path to negative_manifest.json (for negative datasets only).

    Returns:
        Report dict with keys: label, samples, before (verdict/issue counts),
        after (verdict/issue counts), downgraded_count, downgraded_items, and
        optionally manifest_aligned_before/after (if manifest_path is provided).
    """
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
    """Entry point: load positive and negative results, adjust, write outputs, print summary.

    Output files:
      - {output_root}/{positive_results.parent.name}/{positive_results.name}/*.json -- adjusted positive JSONs
      - {output_root}/{negative_results.parent.name}/{negative_results.name}/*.json -- adjusted negative JSONs
      - {report_path} -- comparison_report.json with before/after metrics
    """
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
