"""Analyze human feedback filled into human_review_queue.csv."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_REPORT_ROOT = Path(
    "vlm/data/safebooru_2d/japanese_anime_turnaround_pilot_20/reports/supervision_review/runs"
)
HIGH_RISK_DECISIONS = {"rejected", "needs_revision", "human_review_required"}
NON_MODEL_DECISIONS = {"", "unknown", "not_reviewed"}


def parse_args() -> argparse.Namespace:
    # Note 1: The analyzer is intentionally file-based. It never opens images,
    # calls VLM APIs, or contacts RunningHub; it only summarizes reviewer CSVs.
    parser = argparse.ArgumentParser(description="Analyze filled human_review_queue.csv feedback.")
    parser.add_argument("--human-review-csv", type=Path, help="Path to a filled human_review_queue.csv.")
    parser.add_argument("--run-dir", type=Path, help="Run directory containing tables/human_review_queue.csv.")
    parser.add_argument("--output-dir", type=Path, help="Directory for feedback_summary outputs.")
    return parser.parse_args()


def resolve_input(args: argparse.Namespace) -> Path:
    # Note 2: Support both an exact CSV path and a run directory so maintainers
    # can use whichever path they already have open while reviewing outputs.
    if args.human_review_csv:
        return args.human_review_csv
    if args.run_dir:
        return args.run_dir / "tables" / "human_review_queue.csv"
    candidates = sorted(
        DEFAULT_REPORT_ROOT.glob("*/tables/human_review_queue.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise SystemExit("No human_review_queue.csv found. Pass --human-review-csv or --run-dir.")
    return candidates[0]


def read_csv(path: Path) -> list[dict[str, str]]:
    # Note 3: utf-8-sig keeps compatibility with Excel-edited CSVs on Windows.
    # DictReader also makes the script resilient to column reordering.
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def split_labels(value: str) -> list[str]:
    # Note 4: Reviewers may separate labels with semicolons, commas, or Chinese
    # punctuation. Normalizing all of them avoids overfitting to one editing style.
    normalized = value.replace("，", ";").replace(",", ";").replace("、", ";")
    return [item.strip() for item in normalized.split(";") if item.strip()]


def normalized_decision(value: str) -> str:
    return (value or "").strip().lower()


def safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def decision_accuracy(rows: list[dict[str, str]], prediction_column: str) -> tuple[int, int]:
    # Note 5: Dry-run rows usually have decision=not_reviewed, so they are not
    # counted as model predictions. This prevents placeholder runs from looking
    # like failed or successful agents.
    correct = 0
    total = 0
    for row in rows:
        human_decision = normalized_decision(row.get("human_decision", ""))
        predicted = normalized_decision(row.get(prediction_column, ""))
        if not human_decision or human_decision == "unclear" or predicted in NON_MODEL_DECISIONS:
            continue
        total += 1
        if predicted == human_decision:
            correct += 1
    return correct, total


def high_risk_recall(rows: list[dict[str, str]]) -> tuple[int, int]:
    caught = 0
    total = 0
    for row in rows:
        human_decision = normalized_decision(row.get("human_decision", ""))
        predicted = normalized_decision(row.get("decision", ""))
        if human_decision not in HIGH_RISK_DECISIONS:
            continue
        if predicted in NON_MODEL_DECISIONS:
            continue
        total += 1
        if predicted in HIGH_RISK_DECISIONS:
            caught += 1
    return caught, total


def false_reject_rate(rows: list[dict[str, str]]) -> tuple[int, int]:
    false_rejects = 0
    total_approved = 0
    for row in rows:
        human_decision = normalized_decision(row.get("human_decision", ""))
        predicted = normalized_decision(row.get("decision", ""))
        if human_decision != "approved" or predicted in NON_MODEL_DECISIONS:
            continue
        total_approved += 1
        if predicted == "rejected":
            false_rejects += 1
    return false_rejects, total_approved


def label_counter(rows: list[dict[str, str]], column: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(split_labels(row.get(column, "")))
    return counts


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_summary(rows: list[dict[str, str]], input_path: Path) -> dict[str, Any]:
    labeled_rows = [row for row in rows if normalized_decision(row.get("human_decision", ""))]
    agent_correct, agent_total = decision_accuracy(labeled_rows, "decision")
    expected_correct, expected_total = decision_accuracy(labeled_rows, "expected_decision")
    high_caught, high_total = high_risk_recall(labeled_rows)
    false_rejects, human_approved_total = false_reject_rate(labeled_rows)
    human_decisions = Counter(normalized_decision(row.get("human_decision", "")) for row in labeled_rows)
    human_decisions.pop("", None)
    return {
        "input_csv": str(input_path),
        "total_rows": len(rows),
        "labeled_rows": len(labeled_rows),
        "agent_decision_accuracy": safe_rate(agent_correct, agent_total),
        "agent_decision_accuracy_count": {"correct": agent_correct, "total": agent_total},
        "expected_decision_accuracy": safe_rate(expected_correct, expected_total),
        "expected_decision_accuracy_count": {"correct": expected_correct, "total": expected_total},
        "high_risk_recall": safe_rate(high_caught, high_total),
        "high_risk_recall_count": {"caught": high_caught, "total": high_total},
        "false_reject_rate": safe_rate(false_rejects, human_approved_total),
        "false_reject_rate_count": {"false_rejects": false_rejects, "human_approved_total": human_approved_total},
        "human_decision_counts": dict(sorted(human_decisions.items())),
    }


def finding_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    counters = {
        "correct_findings": label_counter(rows, "correct_findings"),
        "missed_findings": label_counter(rows, "missed_findings"),
        "false_positive_findings": label_counter(rows, "false_positive_findings"),
    }
    output: list[dict[str, Any]] = []
    for feedback_type, counter in counters.items():
        for finding_type, count in counter.most_common():
            output.append({"feedback_type": feedback_type, "finding_type": finding_type, "count": count})
    return output


def write_markdown(path: Path, summary: dict[str, Any], finding_counts: list[dict[str, Any]]) -> None:
    # Note 6: Markdown is kept short on purpose. The JSON and CSV outputs remain
    # the detailed machine-readable artifacts for later analysis.
    lines = [
        "# 人工反馈分析",
        "",
        "## 概览",
        "",
        f"- input_csv: {summary['input_csv']}",
        f"- total_rows: {summary['total_rows']}",
        f"- labeled_rows: {summary['labeled_rows']}",
        f"- agent_decision_accuracy: {summary['agent_decision_accuracy']}",
        f"- expected_decision_accuracy: {summary['expected_decision_accuracy']}",
        f"- high_risk_recall: {summary['high_risk_recall']}",
        f"- false_reject_rate: {summary['false_reject_rate']}",
        "",
        "## 人工决策分布",
        "",
    ]
    for decision, count in summary["human_decision_counts"].items():
        lines.append(f"- {decision}: {count}")
    lines.extend(["", "## Finding 反馈 Top", ""])
    for row in finding_counts[:30]:
        lines.append(f"- {row['feedback_type']} / {row['finding_type']}: {row['count']}")
    if not finding_counts:
        lines.append("- 暂无 finding 反馈。")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    input_path = resolve_input(args)
    if not input_path.exists():
        raise SystemExit(f"human review CSV does not exist: {input_path}")
    output_dir = args.output_dir or (input_path.parent.parent / "feedback_analysis")
    rows = read_csv(input_path)
    summary = build_summary(rows, input_path)
    counts = finding_rows(rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "feedback_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_csv(output_dir / "finding_feedback_counts.csv", counts, ["feedback_type", "finding_type", "count"])
    write_markdown(output_dir / "feedback_report.md", summary, counts)
    print(json.dumps({"status": "finished", "output_dir": str(output_dir), **summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
