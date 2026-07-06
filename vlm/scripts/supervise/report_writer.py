"""Write CSV and Markdown reports for offline supervision runs."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from vlm.scripts.supervise.review_schemas import ReviewResult, RunSummary, to_jsonable
from vlm.scripts.supervise.export_human_review_workbook import export_workbook


SUMMARY_COLUMNS = [
    # Note 1: Keep this column order stable. Humans will open these CSV files in
    # Excel, and downstream feedback scripts can rely on predictable headers.
    "sample_id",
    "category",
    "decision",
    "expected_decision",
    "review_status",
    "score",
    "risk_level",
    "confidence",
    "requires_human_review",
    "finding_count",
    "high_count",
    "critical_count",
    "source_image_path",
    "generated_image_path",
    "result_json_path",
    "needs_human_confirmation",
    "reviewer_note",
]

FINDING_COLUMNS = [
    # Note 2: findings.csv is empty in dry-run, but keeping the header now makes
    # the report contract stable before real VLM findings are introduced.
    "sample_id",
    "category",
    "finding_id",
    "type",
    "dimension",
    "severity",
    "confidence",
    "source_region",
    "generated_region",
    "problem_cn",
    "suggestion_cn",
]

HUMAN_QUEUE_COLUMNS = [
    # Note 3: Blank human_* columns are intentional. They turn the generated CSV
    # into a review worksheet without requiring a separate labeling tool.
    "sample_id",
    "category",
    "decision",
    "expected_decision",
    "score",
    "primary_issue",
    "agent_summary",
    "source_image_path",
    "generated_image_path",
    "human_decision",
    "human_notes",
    "correct_findings",
    "missed_findings",
    "false_positive_findings",
]


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    # Note 4: utf-8-sig writes a BOM so Chinese text opens correctly in Excel on
    # Windows. newline="" lets the csv module control row endings cleanly.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def result_summary_row(result: ReviewResult, result_json_path: Path | None = None) -> dict[str, Any]:
    # Note 5: This function flattens one nested result.json into one spreadsheet
    # row. Keep calculation here instead of duplicating count logic in callers.
    metadata = result.metadata or {}
    seed_case = metadata.get("seed_case") or {}
    findings = result.findings or []
    high_count = sum(1 for finding in findings if finding.severity == "high")
    critical_count = sum(1 for finding in findings if finding.severity == "critical")
    return {
        "sample_id": result.sample_id,
        "category": result.category,
        "decision": result.decision,
        "expected_decision": seed_case.get("expected_decision", ""),
        "review_status": result.review_status,
        "score": result.score,
        "risk_level": result.risk_level,
        "confidence": result.confidence,
        "requires_human_review": result.requires_human_review,
        "finding_count": len(findings),
        "high_count": high_count,
        "critical_count": critical_count,
        "source_image_path": metadata.get("source_image_path", ""),
        "generated_image_path": metadata.get("generated_image_path", ""),
        "result_json_path": str(result_json_path or metadata.get("result_json_path", "")),
        "needs_human_confirmation": seed_case.get("needs_human_confirmation", ""),
        "reviewer_note": seed_case.get("reviewer_note", ""),
    }


def finding_rows(result: ReviewResult) -> list[dict[str, Any]]:
    # Note 6: A result can have multiple findings, so this table is one-to-many
    # relative to review_summary.csv. That shape supports failure-type ranking.
    rows = []
    for finding in result.findings:
        rows.append(
            {
                "sample_id": result.sample_id,
                "category": result.category,
                "finding_id": finding.finding_id,
                "type": finding.type,
                "dimension": finding.dimension,
                "severity": finding.severity,
                "confidence": finding.confidence,
                "source_region": finding.source_region,
                "generated_region": finding.generated_region,
                "problem_cn": finding.problem_cn,
                "suggestion_cn": finding.suggestion_cn,
            }
        )
    return rows


def human_queue_row(result: ReviewResult) -> dict[str, Any]:
    # Note 7: In dry-run there are no model findings, so expected_findings from
    # the seed case become the primary issue hint for the human reviewer.
    metadata = result.metadata or {}
    seed_case = metadata.get("seed_case") or {}
    primary_issue = ""
    if result.findings:
        primary_issue = result.findings[0].type
    elif seed_case.get("expected_findings"):
        primary_issue = ";".join(seed_case.get("expected_findings") or [])
    return {
        "sample_id": result.sample_id,
        "category": result.category,
        "decision": result.decision,
        "expected_decision": seed_case.get("expected_decision", ""),
        "score": result.score,
        "primary_issue": primary_issue,
        "agent_summary": result.summary_cn,
        "source_image_path": metadata.get("source_image_path", ""),
        "generated_image_path": metadata.get("generated_image_path", ""),
        "human_decision": "",
        "human_notes": "",
        "correct_findings": "",
        "missed_findings": "",
        "false_positive_findings": "",
    }


def write_markdown_report(
    path: Path,
    *,
    summary: RunSummary,
    results: list[ReviewResult],
    errors: list[dict[str, Any]],
    skipped_pairs: list[dict[str, Any]],
) -> None:
    # Note 8: The Markdown report is a lightweight index, not the source of
    # truth. Detailed, machine-readable data stays in result.json and CSV files.
    path.parent.mkdir(parents=True, exist_ok=True)
    by_category = Counter(result.category for result in results)
    by_decision = Counter(result.decision for result in results)
    lines = [
        "# 监修报告",
        "",
        "## 本次运行概览",
        "",
        f"- run_id: {summary.run_id}",
        f"- review_status: {summary.review_status}",
        f"- total_pairs: {summary.total_pairs}",
        f"- processed: {summary.processed}",
        f"- skipped_existing: {summary.skipped_existing}",
        f"- skipped_pairs: {summary.skipped_pairs}",
        f"- errors: {summary.errors}",
        "",
        "## 按类别统计",
        "",
    ]
    for category, count in sorted(by_category.items()):
        lines.append(f"- {category}: {count}")
    lines.extend(["", "## 按决策统计", ""])
    for decision, count in sorted(by_decision.items()):
        lines.append(f"- {decision}: {count}")
    lines.extend(["", "## 需要人工复核样本", ""])
    queue = [result for result in results if result.requires_human_review or result.decision != "approved"]
    for result in queue[:50]:
        # Note 9: Limit long sections so Markdown stays readable on full runs.
        # CSV files still contain the complete queue.
        metadata = result.metadata or {}
        seed_case = metadata.get("seed_case") or {}
        lines.append(
            f"- {result.sample_id} / {result.category} / decision={result.decision} "
            f"/ expected={seed_case.get('expected_decision', '')} / status={result.review_status}"
        )
    if not queue:
        lines.append("- 无")
    lines.extend(["", "## 跳过样本", ""])
    for skipped in skipped_pairs[:50]:
        # Note 10: Skipped pairs are listed because they often represent content
        # safety blocks or missing generated images that need a different human
        # action from ordinary review failures.
        lines.append(f"- {skipped.get('sample_id', '')} / {skipped.get('category', '')}: {skipped.get('reason', '')}")
    if not skipped_pairs:
        lines.append("- 无")
    lines.extend(["", "## 错误样本", ""])
    for error in errors[:50]:
        lines.append(f"- {error.get('sample_id', '')} / {error.get('category', '')}: {error.get('error', '')}")
    if not errors:
        lines.append("- 无")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_run_reports(
    *,
    output_dir: Path,
    summary: RunSummary,
    results: list[ReviewResult],
    errors: list[dict[str, Any]],
    result_paths: dict[tuple[str, str], Path],
    skipped_pairs: list[dict[str, Any]] | None = None,
) -> None:
    # Note 11: This is the only public report-writing entry point. The runner
    # should pass structured results here and avoid writing ad hoc tables itself.
    tables_dir = output_dir / "tables"
    markdown_dir = output_dir / "markdown"

    summary_rows = [
        result_summary_row(result, result_paths.get((result.sample_id, result.category))) for result in results
    ]
    findings = [row for result in results for row in finding_rows(result)]
    human_queue = [
        # Note 12: Anything not completed/approved stays visible to humans. In
        # dry-run that means every processed sample enters the queue by design.
        human_queue_row(result)
        for result in results
        if result.requires_human_review or result.decision != "approved" or result.review_status != "completed"
    ]

    write_csv(tables_dir / "review_summary.csv", summary_rows, SUMMARY_COLUMNS)
    write_csv(tables_dir / "findings.csv", findings, FINDING_COLUMNS)
    human_queue_csv = tables_dir / "human_review_queue.csv"
    write_csv(human_queue_csv, human_queue, HUMAN_QUEUE_COLUMNS)
    # Note 13: The CSV remains the machine-readable source, but the formatted
    # workbook is much easier for humans to fill because it freezes headers,
    # highlights editable columns, wraps long paths, and adds a decision dropdown.
    export_workbook(human_queue_csv, tables_dir / "human_review_queue.xlsx")
    write_markdown_report(
        markdown_dir / "review_report.md",
        summary=summary,
        results=results,
        errors=errors,
        skipped_pairs=skipped_pairs or [],
    )
    (output_dir / "run_summary.json").write_text(
        json.dumps(to_jsonable(summary), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
