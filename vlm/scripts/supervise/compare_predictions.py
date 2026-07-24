"""
Compare Predictions with Evaluation Gold
=========================================

This module implements event-level matching logic between Qwen VL model predictions
and human-verified gold labels for anime IP merchandise supervision.

The core evaluation approach:
- Qwen VL predictions are loaded from per-sample CSV files (flattened format v3).
- Human-annotated gold labels are loaded from a shared evaluation gold CSV.
- Both sources are converted to a normalized "event" representation
  (one event = one issue detected on one view of one sample).
- Events are matched (strict or relaxed) to compute acceptance quality metrics:
    precision = TP / (TP + FP)  — how accurate the model's flags are
    recall    = TP / (TP + FN)  — how many real issues the model catches
    F1        = harmonic mean of precision and recall

Dual-lane separation:
- Lane A (annotation_acceptance): counted in main metrics.
  Issue types: "wrong color", "wrong material", "wrong shape", "paired box completion".
- Lane B (design_quality): data is preserved in the pipeline but excluded from
  the acceptance precision/recall/F1 numbers computed here.

Typical usage (CLI):
    python -m vlm.scripts.supervise.compare_predictions \\
        --dataset-root vlm/data/.../<dataset> \\
        --gold-csv vlm/data/mock_gold/mock_evaluation_gold.csv \\
        --output-dir vlm/data/comparison_results
"""

import csv
import json
from pathlib import Path
from typing import List, Dict, Any, Tuple, Set
from collections import defaultdict


# Acceptance issue types (Lane A)
ACCEPTANCE_ISSUE_TYPES = {
    "wrong color",
    "wrong material",
    "wrong shape",
    "paired box completion",
}


def load_predictions(sample_dir: Path) -> List[Dict[str, Any]]:
    """
    Load Qwen VL model predictions from a sample directory.

    Args:
        sample_dir: Path to sample directory containing qwen_prediction_flattened_v3.csv

    Returns:
        List of prediction rows (dicts), empty list if file not found
    """
    pred_csv = sample_dir / "qwen_prediction_flattened_v3.csv"
    if not pred_csv.exists():
        return []

    rows = []
    with open(pred_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def load_gold(gold_csv: Path) -> List[Dict[str, Any]]:
    """
    Load human-verified evaluation gold labels from a shared CSV file.

    Args:
        gold_csv: Path to the evaluation gold CSV (may contain rows for multiple samples)

    Returns:
        List of gold label rows (dicts), empty list if file not found
    """
    if not gold_csv.exists():
        return []

    rows = []
    with open(gold_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def _parse_confidence(value: Any) -> float:
    """
    Parse a confidence value from either a numeric or string representation.

    String confidence levels are mapped to representative float scores:
        "high" / "very_high" -> 0.95
        "medium"             -> 0.75
        "low"                -> 0.50
        unknown string       -> 1.0  (treat unknown as fully confident)

    Args:
        value: Raw confidence value from a prediction row (int, float, or str)

    Returns:
        Normalized float confidence in [0, 1]
    """
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = value.lower()
        if value in ("high", "very_high"):
            return 0.95
        elif value in ("medium",):
            return 0.75
        elif value in ("low",):
            return 0.5
        else:
            return 1.0
    return 1.0


def extract_prediction_events(
    predictions: List[Dict[str, Any]],
    sample_id: str,
    category: str
) -> List[Dict[str, Any]]:
    """
    Convert raw Qwen VL prediction rows into normalized acceptance events (Lane A only).

    Each prediction row may represent up to three views (front, side, back). This
    function expands each row into one event per view that has an acceptance issue,
    filtering out views that are "correct" or have design-quality-only issues.

    Args:
        predictions: Raw prediction rows loaded from qwen_prediction_flattened_v3.csv
        sample_id:   Identifier for the merchandise sample being evaluated
        category:    Product category (e.g., "figure", "plushie")

    Returns:
        List of normalized event dicts, each containing:
            sample_id, category, view, issue_type, rule_id, attribute,
            element_name, confidence, reason
    """
    events = []

    for pred in predictions:
        rule_id = pred["rule_id"]
        value = pred["value"]

        # Extract status for each view (front, side, back)
        front_status = pred.get("front_status", "correct")
        side_status = pred.get("side_status", "correct")
        back_status = pred.get("back_status", "correct")

        # Only process acceptance-level issues (Lane A), skip design-quality issues (Lane B)
        view_statuses = [
            ("front", front_status),
            ("side", side_status),
            ("back", back_status),
        ]

        for view, status in view_statuses:
            if status in ACCEPTANCE_ISSUE_TYPES:
                events.append({
                    "sample_id": sample_id,
                    "category": category,
                    "view": view,
                    "issue_type": status,
                    "rule_id": rule_id,
                    "attribute": _infer_attribute(rule_id, status),
                    "element_name": rule_id,
                    "confidence": _parse_confidence(pred.get("confidence", 1.0)),
                    "reason": pred.get("reason", ""),
                })

    return events


def extract_gold_events(
    gold_rows: List[Dict[str, Any]],
    sample_id: str,
    category: str
) -> List[Dict[str, Any]]:
    """
    Filter and normalize gold label rows into acceptance events (Lane A only).

    Iterates over all rows in the gold CSV and selects those belonging to the
    given sample_id and category that represent acceptance-level issues.

    Args:
        gold_rows: All rows loaded from the evaluation gold CSV
        sample_id: The sample identifier to filter on
        category:  The product category to filter on

    Returns:
        List of normalized gold event dicts for the specified sample/category,
        each containing: sample_id, category, view, issue_type, rule_id,
        attribute, element_name, confidence, reason
    """
    events = []

    for row in gold_rows:
        if row["sample_id"] != sample_id:
            continue
        if row["category"] != category:
            continue

        issue_type = row.get("issue_type", "")
        if issue_type not in ACCEPTANCE_ISSUE_TYPES:
            continue

        events.append({
            "sample_id": sample_id,
            "category": category,
            "view": row.get("view", "unknown"),
            "issue_type": issue_type,
            "rule_id": row.get("rule_id", ""),
            "attribute": row.get("attribute", ""),
            "element_name": row.get("element_name", ""),
            "confidence": float(row.get("confidence", 1.0)),
            "reason": row.get("reason", ""),
        })

    return events


def _infer_attribute(rule_id: str, issue_type: str) -> str:
    """
    Infer the affected attribute category from a rule_id and issue_type.

    The issue_type takes priority; if the issue_type doesn't indicate a specific
    attribute, the rule_id string is scanned for known keywords as a fallback.

    Args:
        rule_id:    Rule identifier string (e.g., "hair_color", "fabric_material")
        issue_type: Detected issue type string (e.g., "wrong color")

    Returns:
        One of "color", "material", "shape", or "other"
    """
    if issue_type == "wrong color":
        return "color"
    elif issue_type == "wrong material":
        return "material"
    elif issue_type == "wrong shape":
        return "shape"
    elif "color" in rule_id:
        return "color"
    elif "material" in rule_id or "fabric" in rule_id:
        return "material"
    elif "type" in rule_id or "style" in rule_id or "shape" in rule_id:
        return "shape"
    else:
        return "other"


def event_key(event: Dict[str, Any], strict: bool = True) -> Tuple:
    """
    Generate a hashable matching key for an event.

    Two matching modes are supported:

    strict=True  (default, exact match):
        Key = (sample_id, category, issue_type, rule_id, view)
        Requires the prediction to name the exact same rule and view as gold.

    strict=False (relaxed match):
        Key = (sample_id, category, issue_type, element_name)
        Allows a match even if the specific view differs, as long as the
        element and issue type agree.

    Args:
        event:  Normalized event dict (prediction or gold)
        strict: If True, use exact-match key; if False, use relaxed key

    Returns:
        Tuple that uniquely identifies the event at the chosen granularity
    """
    if strict:
        return (
            event["sample_id"],
            event["category"],
            event["issue_type"],
            event.get("rule_id", ""),
            event.get("view", ""),
        )
    else:
        return (
            event["sample_id"],
            event["category"],
            event["issue_type"],
            event.get("element_name", ""),
        )


def match_events(
    pred_events: List[Dict[str, Any]],
    gold_events: List[Dict[str, Any]],
    strict: bool = True
) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """
    Match prediction events against gold events using a greedy 1-to-1 strategy.

    Events are grouped by their matching key (see event_key()). For each key
    bucket, predictions and gold entries are paired positionally: the first
    prediction matches the first gold, the second matches the second, etc.
    Any surplus predictions become false positives (FP); any surplus gold
    entries become false negatives (FN).

    Args:
        pred_events:  List of normalized prediction events
        gold_events:  List of normalized gold events
        strict:       If True, use exact-match keys; if False, use relaxed keys

    Returns:
        matched:          List of (pred_event, gold_event) pairs — true positives (TP)
        unmatched_preds:  Prediction events with no gold counterpart — false positives (FP)
        unmatched_gold:   Gold events with no prediction counterpart — false negatives (FN)
    """
    # Group prediction events by their matching key for O(1) bucket lookup
    pred_keys = defaultdict(list)
    for pred in pred_events:
        key = event_key(pred, strict)
        pred_keys[key].append(pred)

    # Group gold events by the same key scheme
    gold_keys = defaultdict(list)
    for gold in gold_events:
        key = event_key(gold, strict)
        gold_keys[key].append(gold)

    matched = []
    unmatched_preds = []
    unmatched_gold = []

    # Iterate over the union of all keys that appear in either predictions or gold
    all_keys = set(pred_keys.keys()) | set(gold_keys.keys())

    for key in all_keys:
        preds = pred_keys.get(key, [])
        golds = gold_keys.get(key, [])

        # Greedy 1:1 positional pairing within each bucket
        for i, pred in enumerate(preds):
            if i < len(golds):
                # Both a prediction and a gold exist at index i — this is a TP
                matched.append((pred, golds[i]))
            else:
                # More predictions than gold entries — surplus predictions are FP
                unmatched_preds.append(pred)

        for i, gold in enumerate(golds):
            if i >= len(preds):
                # More gold entries than predictions — surplus gold entries are FN
                unmatched_gold.append(gold)

    return matched, unmatched_preds, unmatched_gold


def compute_metrics(
    matched: List[Dict],
    unmatched_preds: List[Dict],
    unmatched_gold: List[Dict]
) -> Dict[str, float]:
    """
    Compute acceptance precision, recall, and F1 from event match counts.

    Definitions:
        TP (true positive)  — matched prediction/gold pairs
        FP (false positive) — predictions flagged by the model but absent in gold
        FN (false negative) — issues present in gold that the model missed

        precision = TP / (TP + FP)  — fraction of model flags that are correct
        recall    = TP / (TP + FN)  — fraction of real issues the model detected
        F1        = 2 * P * R / (P + R)  — harmonic mean, balances P and R

    Edge cases: if the denominator is zero, the metric is returned as 0.0.

    Args:
        matched:          List of TP (pred, gold) pairs from match_events()
        unmatched_preds:  List of FP prediction events
        unmatched_gold:   List of FN gold events

    Returns:
        Dict with keys: "tp", "fp", "fn", "precision", "recall", "f1"
    """
    tp = len(matched)   # correctly flagged issues
    fp = len(unmatched_preds)  # model over-flagged (false alarms)
    fn = len(unmatched_gold)   # model missed these issues

    # Precision: of all flags raised by the model, how many were real?
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    # Recall: of all real issues in gold, how many did the model find?
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    # F1: harmonic mean — penalizes large imbalances between precision and recall
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def compare_predictions_for_sample(
    sample_dir: Path,
    gold_events: List[Dict[str, Any]],
    sample_id: str,
    category: str,
    strict: bool = True
) -> Dict[str, Any]:
    """
    Run the full prediction-vs-gold comparison pipeline for a single sample.

    Steps:
        1. Load Qwen VL predictions from the sample directory.
        2. Extract acceptance events from predictions (Lane A only).
        3. Filter gold events to those belonging to this sample.
        4. Match prediction events against gold events (strict or relaxed).
        5. Compute precision/recall/F1 for the sample.

    Args:
        sample_dir:   Path to the sample directory (must contain flattened CSV)
        gold_events:  All gold events loaded from the shared evaluation gold CSV
        sample_id:    Identifier for this sample (used for gold filtering and output)
        category:     Product category string
        strict:       If True, use exact-match key; if False, use relaxed key

    Returns:
        Dict with sample metadata, event counts, metrics, and per-event details.
        Returns {"error": "No predictions found"} if no prediction file exists.
    """

    predictions = load_predictions(sample_dir)
    if not predictions:
        return {"error": "No predictions found"}

    # 提取 events
    pred_events = extract_prediction_events(predictions, sample_id, category)
    sample_gold_events = [g for g in gold_events if g["sample_id"] == sample_id]

    # 匹配
    matched, unmatched_preds, unmatched_gold = match_events(
        pred_events, sample_gold_events, strict
    )

    # 计算指标
    metrics = compute_metrics(matched, unmatched_preds, unmatched_gold)

    return {
        "sample_id": sample_id,
        "category": category,
        "num_predictions": len(predictions),
        "num_pred_events": len(pred_events),
        "num_gold_events": len(sample_gold_events),
        "matched": len(matched),
        "unmatched_preds": len(unmatched_preds),
        "unmatched_gold": len(unmatched_gold),
        "metrics": metrics,
        "matched_details": [
            {
                "rule_id": m[0]["rule_id"],
                "issue_type": m[0]["issue_type"],
                "view": m[0]["view"],
            }
            for m in matched
        ],
        "unmatched_pred_details": [
            {
                "rule_id": p["rule_id"],
                "issue_type": p["issue_type"],
                "view": p["view"],
            }
            for p in unmatched_preds
        ],
        "unmatched_gold_details": [
            {
                "rule_id": g["rule_id"],
                "issue_type": g["issue_type"],
                "view": g["view"],
            }
            for g in unmatched_gold
        ],
    }


def compare_all_samples(
    dataset_root: Path,
    gold_csv: Path,
    strict: bool = True
) -> Dict[str, Any]:
    """
    Run the prediction-vs-gold comparison across the entire dataset.

    Walks all category subdirectories under dataset_root, then all sample
    subdirectories within each category. For each sample it calls
    compare_predictions_for_sample() and accumulates TP/FP/FN counts
    for macro-averaged overall metrics.

    Args:
        dataset_root: Root directory of the pilot dataset; expected layout:
                          dataset_root/<category>/<sample_id>/
        gold_csv:     Path to the shared evaluation gold CSV
        strict:       Passed through to compare_predictions_for_sample()

    Returns:
        Dict containing:
            total_samples     — number of samples processed
            total_tp/fp/fn    — cumulative counts across all samples
            overall_precision — micro-averaged precision over all events
            overall_recall    — micro-averaged recall over all events
            overall_f1        — micro-averaged F1 over all events
            per_sample_results — list of per-sample result dicts
    """

    gold_events = load_gold(gold_csv)
    if not gold_events:
        return {"error": f"No gold events found in {gold_csv}"}

    results = []
    total_tp = 0
    total_fp = 0
    total_fn = 0

    # Iterate all category directories (e.g., "figure", "plushie") under the dataset root
    for category_dir in sorted(dataset_root.iterdir()):
        if not category_dir.is_dir():
            continue
        category = category_dir.name

        for sample_dir in sorted(category_dir.iterdir()):
            if not sample_dir.is_dir():
                continue
            sample_id = sample_dir.name

            result = compare_predictions_for_sample(
                sample_dir, gold_events, sample_id, category, strict
            )
            results.append(result)

            if "metrics" in result:
                total_tp += result["metrics"]["tp"]
                total_fp += result["metrics"]["fp"]
                total_fn += result["metrics"]["fn"]

    # Compute overall (micro-averaged) metrics by summing TP/FP/FN across all samples.
    # Micro-averaging weights each event equally regardless of which sample it came from.
    overall_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    overall_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    overall_f1 = (
        2 * overall_precision * overall_recall / (overall_precision + overall_recall)
        if (overall_precision + overall_recall) > 0
        else 0.0
    )

    return {
        "total_samples": len(results),
        "total_tp": total_tp,
        "total_fp": total_fp,
        "total_fn": total_fn,
        "overall_precision": overall_precision,
        "overall_recall": overall_recall,
        "overall_f1": overall_f1,
        "per_sample_results": results,
    }


def write_comparison_report(
    comparison_result: Dict[str, Any],
    output_path: Path
):
    """
    Write the full comparison results to a JSON report file.

    Args:
        comparison_result: Dict returned from compare_all_samples() containing
                           overall metrics and per-sample details
        output_path:       Path where the JSON report should be written
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(comparison_result, f, indent=2, ensure_ascii=False)

    print(f"Comparison report written to: {output_path}")


def write_matched_events_csv(
    comparison_result: Dict[str, Any],
    output_path: Path
):
    """
    Write a flat CSV file of all matched and unmatched events across all samples.

    Each row represents one event and carries a match_status label:
        "matched" — TP: prediction was correctly flagged and matched to a gold entry
        "fp"      — FP: prediction flagged an issue that was not in gold
        "fn"      — FN: gold had an issue that the model missed

    This CSV is useful for manual error analysis (e.g., filtering by category
    or issue type to find systematic model weaknesses).

    Args:
        comparison_result: Dict returned from compare_all_samples()
        output_path:       Destination path for the output CSV (utf-8-sig encoding
                           for Excel compatibility)
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if "per_sample_results" not in comparison_result:
        print("No per_sample_results to write")
        return

    rows = []
    for result in comparison_result["per_sample_results"]:
        if "matched_details" not in result:
            continue

        sample_id = result["sample_id"]
        category = result["category"]

        # Matched events
        for detail in result["matched_details"]:
            rows.append({
                "sample_id": sample_id,
                "category": category,
                "match_status": "matched",
                "rule_id": detail["rule_id"],
                "issue_type": detail["issue_type"],
                "view": detail["view"],
            })

        # Unmatched predictions (FP)
        for detail in result["unmatched_pred_details"]:
            rows.append({
                "sample_id": sample_id,
                "category": category,
                "match_status": "fp",
                "rule_id": detail["rule_id"],
                "issue_type": detail["issue_type"],
                "view": detail["view"],
            })

        # Unmatched gold (FN)
        for detail in result["unmatched_gold_details"]:
            rows.append({
                "sample_id": sample_id,
                "category": category,
                "match_status": "fn",
                "rule_id": detail["rule_id"],
                "issue_type": detail["issue_type"],
                "view": detail["view"],
            })

    if rows:
        fieldnames = ["sample_id", "category", "match_status", "rule_id", "issue_type", "view"]
        with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    print(f"Matched events CSV written to: {output_path}")


def main():
    """
    CLI entry point for the prediction comparison tool.

    Parses command-line arguments, runs the full dataset comparison, writes
    a JSON report and a matched-events CSV, then prints overall acceptance
    metrics (precision, recall, F1) to stdout.

    Arguments:
        --dataset-root  Path to the pilot dataset root directory
        --gold-csv      Path to the evaluation gold CSV file
        --output-dir    Directory where report JSON and events CSV are written
        --strict        Use exact-match keys (default; flag is a no-op since
                        strict=True is the default)
        --relaxed       Switch to relaxed matching (overrides --strict)
    """
    import argparse

    parser = argparse.ArgumentParser(description="Compare predictions with evaluation gold")
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path("vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/multi_view试标数据集"),
        help="试标数据集根目录"
    )
    parser.add_argument(
        "--gold-csv",
        type=Path,
        default=Path("vlm/data/mock_gold/mock_evaluation_gold.csv"),
        help="Evaluation gold CSV 文件"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("vlm/data/comparison_results"),
        help="输出目录"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=True,
        help="使用 exact match (sample_id + category + issue_type + rule_id + view)"
    )
    parser.add_argument(
        "--relaxed",
        action="store_true",
        help="使用 relaxed match (sample_id + category + issue_type + element_name)"
    )

    args = parser.parse_args()

    strict = not args.relaxed

    comparison_result = compare_all_samples(args.dataset_root, args.gold_csv, strict)

    # 写入报告
    report_path = args.output_dir / "comparison_report.json"
    write_comparison_report(comparison_result, report_path)

    # 写入匹配事件 CSV
    events_csv_path = args.output_dir / "matched_events.csv"
    write_matched_events_csv(comparison_result, events_csv_path)

    # 打印总体指标
    print("\n" + "=" * 60)
    print("Overall Acceptance Metrics (Lane A)")
    print("=" * 60)
    print(f"Total samples: {comparison_result['total_samples']}")
    print(f"TP: {comparison_result['total_tp']}")
    print(f"FP: {comparison_result['total_fp']}")
    print(f"FN: {comparison_result['total_fn']}")
    print(f"Precision: {comparison_result['overall_precision']:.4f}")
    print(f"Recall: {comparison_result['overall_recall']:.4f}")
    print(f"F1: {comparison_result['overall_f1']:.4f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
