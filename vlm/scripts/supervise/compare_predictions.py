"""
Compare Predictions with Evaluation Gold

实现 event-level 匹配逻辑，计算 acceptance precision/recall/F1。

双 lane 分离：
- Lane A (annotation_acceptance): 只统计 wrong color/material/shape/paired box completion
- Lane B (design_quality): 保留但不纳入主指标
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
    """加载 Qwen 预测结果"""
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
    """加载 evaluation gold"""
    if not gold_csv.exists():
        return []

    rows = []
    with open(gold_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def _parse_confidence(value: Any) -> float:
    """解析 confidence 值，处理字符串情况"""
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
    从 Qwen 预测中提取 acceptance events (Lane A)

    一个 prediction 可能对应多个 view events
    """
    events = []

    for pred in predictions:
        rule_id = pred["rule_id"]
        value = pred["value"]

        # 提取各 view 的 status
        front_status = pred.get("front_status", "correct")
        side_status = pred.get("side_status", "correct")
        back_status = pred.get("back_status", "correct")

        # 只处理 acceptance 范围内的问题
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
    从 gold 中提取 acceptance events (Lane A)
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
    """从 rule_id 推断 attribute"""
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
    生成 event 的匹配 key

    strict=True: exact match (sample_id + category + issue_type + rule_id + view)
    strict=False: relaxed match (sample_id + category + issue_type + element_name)
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
    匹配 prediction events 和 gold events

    Returns:
        matched: List of (pred_event, gold_event) tuples
        unmatched_preds: List of prediction events without gold match
        unmatched_gold: List of gold events without prediction match
    """
    pred_keys = defaultdict(list)
    for pred in pred_events:
        key = event_key(pred, strict)
        pred_keys[key].append(pred)

    gold_keys = defaultdict(list)
    for gold in gold_events:
        key = event_key(gold, strict)
        gold_keys[key].append(gold)

    matched = []
    unmatched_preds = []
    unmatched_gold = []

    # 匹配
    all_keys = set(pred_keys.keys()) | set(gold_keys.keys())

    for key in all_keys:
        preds = pred_keys.get(key, [])
        golds = gold_keys.get(key, [])

        # 简单 1:1 匹配
        for i, pred in enumerate(preds):
            if i < len(golds):
                matched.append((pred, golds[i]))
            else:
                unmatched_preds.append(pred)

        for i, gold in enumerate(golds):
            if i >= len(preds):
                unmatched_gold.append(gold)

    return matched, unmatched_preds, unmatched_gold


def compute_metrics(
    matched: List[Dict],
    unmatched_preds: List[Dict],
    unmatched_gold: List[Dict]
) -> Dict[str, float]:
    """计算 acceptance metrics"""
    tp = len(matched)
    fp = len(unmatched_preds)
    fn = len(unmatched_gold)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
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
    """对比单个样本的预测和 gold"""

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
    """对比所有样本"""

    gold_events = load_gold(gold_csv)
    if not gold_events:
        return {"error": f"No gold events found in {gold_csv}"}

    results = []
    total_tp = 0
    total_fp = 0
    total_fn = 0

    # 遍历所有品类和样本
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

    # 总体指标
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
    """写入对比报告"""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(comparison_result, f, indent=2, ensure_ascii=False)

    print(f"Comparison report written to: {output_path}")


def write_matched_events_csv(
    comparison_result: Dict[str, Any],
    output_path: Path
):
    """写入匹配事件 CSV"""
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
    """CLI 入口"""
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
