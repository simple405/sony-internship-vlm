"""Build verified evaluation gold from human annotations.

PIPELINE POSITION
-----------------
This script sits at Stage 3 of the annotation pipeline:

  Stage 1 – Annotator gold (annotator_gold.csv)
      Human annotators inspect each merchandise sample image against the
      corresponding atomic rules and record per-rule verdicts (visible/status
      per view, overall result, confidence, reason).

  Stage 2 – Atomic rule audit (atomic_rule_audit.csv)
      A second reviewer checks the *quality* of each atomic rule itself
      (are the rule's expected values correct?), not the annotation.  Each
      rule receives ``rule_validity=correct | incorrect | ambiguous | skip``.

  Stage 3 (THIS SCRIPT) – Verified evaluation gold
      Only Stage 1 rows whose corresponding atomic rule passed Stage 2 with
      ``rule_validity=correct`` are promoted to the verified gold set.  Rows
      backed by incorrect, ambiguous, or unreviewed rules are moved to
      ``excluded_gold_rows.csv`` with an ``exclude_reason`` explaining why.

WHY "BILLABLE-ONLY" NARROWING?
-------------------------------
Qwen accuracy is measured against this verified gold.  Including rows where
the ground-truth rule is wrong would unfairly penalise correct Qwen predictions
and skew accuracy metrics.  The filtering is intentionally conservative: when
in doubt (missing audit, ambiguous), rows are excluded rather than included.

The ``--include-unaudited`` flag relaxes this: rows with no matching audit
entry are promoted with ``audit_rule_validity=unaudited`` rather than excluded.
Use this during early development before all rules have been reviewed.

DRY-RUN / EMPTY-INPUT MODE
---------------------------
Every CSV input (``--annotator-gold``, ``--atomic-rule-audit``,
``--visual-findings``) is optional.  If none are provided, the script writes
all output CSVs with stable headers but zero data rows, and summary.json
records zero counts.  This lets downstream tasks consume the output directory
structure before human data has been collected.
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

# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------

# Columns expected in the incoming annotator_gold.csv from human annotators.
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

# Output columns for verified_evaluation_gold.csv — the canonical reference
# used when scoring Qwen predictions.  Includes audit provenance fields so
# consumers can trace every row back to its audit entry.
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
    "audit_rule_validity",   # "correct" for all promoted rows
    "audit_reason",          # reviewer's comment from the atomic rule audit
]

# excluded_gold_rows.csv has all verified gold columns plus an extra column
# explaining why the row was not promoted.
EXCLUDED_GOLD_COLUMNS = VERIFIED_GOLD_COLUMNS + ["exclude_reason"]

# atomic_rule_quality_report.csv — a pass-through of the audit CSV for
# downstream quality dashboards.
ATOMIC_RULE_QUALITY_COLUMNS = [
    "sample_id",
    "category",
    "rule_id",
    "atomic_value",
    "rule_validity",
    "corrected_value",
    "reason",
]

# coverage_gap_report.csv — Stage 1 visual findings that have not yet been
# linked to a specific atomic rule.
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Define and parse command-line arguments.

    All input CSV paths are optional to support dry-run usage before human
    data has been collected.

    Returns
    -------
    argparse.Namespace
        Parsed argument object.  Key fields:

        * ``annotator_gold``    – Stage 1 per-rule human verdicts.
        * ``atomic_rule_audit`` – Stage 2 rule validity audit.
        * ``visual_findings``   – optional Stage 1 free-form visual findings.
        * ``output_dir``        – destination directory for all output files.
        * ``include_unaudited`` – if True, rows missing from the audit are
          promoted with ``audit_rule_validity=unaudited`` instead of excluded.
    """
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


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def read_csv(path: Path | None) -> list[dict[str, str]]:
    """Read a CSV file into a list of stripped row dicts.

    Returns an empty list (rather than raising) when ``path`` is ``None`` or
    the file does not exist.  This supports the dry-run mode described in the
    module docstring.

    Encoding ``utf-8-sig`` handles BOM-prefixed files produced by Excel and
    some human annotation tools.  All cell values are stripped of leading and
    trailing whitespace.

    Parameters
    ----------
    path:
        Path to the CSV file, or ``None`` if the argument was not provided.

    Returns
    -------
    list[dict[str, str]]
        One dict per data row, keyed by column header.  Empty list if the file
        does not exist.
    """
    if path is None or not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    """Write a list of dicts to a CSV file, creating parent directories as needed.

    Uses ``utf-8-sig`` encoding (BOM-prefixed UTF-8) for Excel compatibility.
    The ``extrasaction="ignore"`` setting silently drops dict keys not present
    in ``fieldnames``, which is intentional: helper functions return richer
    dicts that are narrowed to the relevant columns at write time.

    Parameters
    ----------
    path:
        Destination file path.
    rows:
        Data rows as dicts.
    fieldnames:
        Ordered list of column names to write; defines both the header row
        and which keys are extracted from each row dict.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    """Write a JSON-serialisable object to a UTF-8 file.

    Parameters
    ----------
    path:
        Destination file path.  Parent directories are created if absent.
    payload:
        Any JSON-serialisable Python object.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def audit_index(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    """Build a (sample_id, rule_id) lookup index from atomic rule audit rows.

    The index maps composite keys to their first-seen audit row so that
    ``build_verified_rows`` can join each annotator gold row to its audit
    result in O(1).  Duplicate keys (same sample + rule reviewed twice) keep
    only the first entry, which is consistent with how audit tools typically
    work (first review is canonical).

    Parameters
    ----------
    rows:
        All rows from atomic_rule_audit.csv.

    Returns
    -------
    dict[tuple[str, str], dict[str, str]]
        Mapping from ``(sample_id, rule_id)`` to the audit row dict.
    """
    index: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (row.get("sample_id", ""), row.get("rule_id", ""))
        # Only index rows that have both parts of the composite key.
        if key[0] and key[1] and key not in index:
            index[key] = row
    return index


def build_verified_rows(
    gold_rows: list[dict[str, str]],
    audit_rows: list[dict[str, str]],
    include_unaudited: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split annotator gold rows into verified and excluded sets.

    For each gold row the corresponding audit entry is looked up by
    ``(sample_id, rule_id)``.  The decision logic is:

    * No audit entry found AND ``include_unaudited=True``
        → promote with ``audit_rule_validity=unaudited``.
    * No audit entry found AND ``include_unaudited=False``
        → exclude with ``exclude_reason=missing_audit``.
    * Audit found, ``rule_validity == "correct"``
        → promote (this is the "billable-only" filter: only rules confirmed
        correct by a human reviewer are allowed into the gold set).
    * Audit found, ``rule_validity`` is anything else (incorrect, ambiguous,
        skip, blank)
        → exclude with ``exclude_reason=rule_validity_<value>``.

    Parameters
    ----------
    gold_rows:
        All rows from annotator_gold.csv.
    audit_rows:
        All rows from atomic_rule_audit.csv.
    include_unaudited:
        Whether to promote rows whose rule was not reviewed.

    Returns
    -------
    tuple[list[dict], list[dict]]
        ``(verified, excluded)`` — two parallel lists of row dicts.  Excluded
        rows include an extra ``exclude_reason`` key.
    """
    # Build the O(1) audit lookup once for all gold rows.
    audits = audit_index(audit_rows)
    verified: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for row in gold_rows:
        key = (row.get("sample_id", ""), row.get("rule_id", ""))
        audit = audits.get(key)

        if audit is None:
            # No matching audit entry — the rule has not been reviewed yet.
            if include_unaudited:
                verified.append(verified_row(row, {"rule_validity": "unaudited", "reason": ""}))
            else:
                excluded.append({
                    **verified_row(row, {"rule_validity": "unaudited", "reason": ""}),
                    "exclude_reason": "missing_audit",
                })
            continue

        validity = audit.get("rule_validity", "")
        if validity == "correct":
            # The rule has been explicitly confirmed correct — promote this row.
            verified.append(verified_row(row, audit))
        else:
            # Rule is incorrect, ambiguous, skipped, or blank — exclude.
            excluded.append({
                **verified_row(row, audit),
                "exclude_reason": f"rule_validity_{validity or 'blank'}",
            })

    return verified, excluded


def verified_row(row: dict[str, str], audit: dict[str, str]) -> dict[str, Any]:
    """Merge one annotator gold row with its audit entry into a verified row dict.

    Both sources are needed because:
    * ``row`` carries the per-view visibility/status verdicts and the human
      annotator's result, confidence, and reason.
    * ``audit`` carries the rule reviewer's validity verdict and their comment.
    * ``category`` may be present in either source; the gold row is preferred.
    * ``value`` falls back to ``audit.atomic_value`` if the gold row left it
      blank (can happen when an annotator did not copy the rule value).

    Parameters
    ----------
    row:
        One row from annotator_gold.csv.
    audit:
        The matching row from atomic_rule_audit.csv (or a minimal stand-in
        dict when the audit is absent).

    Returns
    -------
    dict[str, Any]
        A flat dict with all keys from VERIFIED_GOLD_COLUMNS populated.
    """
    # Prefer category from the gold row; fall back to audit row if missing.
    category = row.get("category") or audit.get("category", "")
    return {
        "sample_id": row.get("sample_id", ""),
        "category": category,
        "rule_id": row.get("rule_id", ""),
        # If the annotator left 'value' blank, fill from the audited atomic_value.
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
        # Audit provenance — lets downstream tools trace each gold row.
        "audit_rule_validity": audit.get("rule_validity", ""),
        "audit_reason": audit.get("reason", ""),
    }


def atomic_rule_quality_rows(audit_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Re-project audit rows onto the atomic rule quality report schema.

    This is a simple column-selection pass-through that normalises the audit
    CSV into a fixed schema for downstream quality dashboards.  No data is
    added or transformed; rows with missing fields get empty strings.

    Parameters
    ----------
    audit_rows:
        All rows from atomic_rule_audit.csv.

    Returns
    -------
    list[dict[str, Any]]
        One dict per audit row, with keys matching ATOMIC_RULE_QUALITY_COLUMNS.
    """
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

    A "coverage gap" is a free-form visual finding (Stage 1) that has not yet
    been linked to an atomic rule from the supervision rulebook.  Until an
    explicit ``matched_rule_id`` column is added to the visual findings CSV,
    every Stage 1 finding is treated as a candidate gap and tagged with one of
    two gap reasons:

    * ``needs_rule_mapping``       – the finding's sample has atomic rules in
      the audit, so a reviewer should be able to match this finding to a rule.
    * ``sample_not_in_rule_audit`` – the sample has no audit entries at all;
      full rule coverage analysis is not yet possible for it.

    This output is a triage list rather than a strict coverage metric.  A
    later converter can add ``matched_rule_id`` and suppress matched findings
    to produce a true gap report.

    Parameters
    ----------
    visual_rows:
        All rows from human_visual_findings.csv.  Returns empty list if absent.
    audit_rows:
        All rows from atomic_rule_audit.csv (used to determine which samples
        have been audited).

    Returns
    -------
    list[dict[str, Any]]
        One dict per visual finding, with keys matching COVERAGE_GAP_COLUMNS.
    """
    if not visual_rows:
        return []
    # Build a set of sample IDs that have at least one audit entry.
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
                # Distinguish between "reviewable gap" and "no audit data yet".
                "gap_reason": "needs_rule_mapping" if sample_id in audited_samples else "sample_not_in_rule_audit",
            }
        )
    return gaps


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Orchestrate gold building, write all output files, and print a summary.

    Output files written to ``--output-dir``:

    * ``verified_evaluation_gold.csv``   – promoted rows (rule_validity=correct).
    * ``excluded_gold_rows.csv``         – rows that failed the audit filter.
    * ``atomic_rule_quality_report.csv`` – pass-through of the audit CSV.
    * ``coverage_gap_report.csv``        – Stage 1 findings lacking rule links.
    * ``summary.json``                   – row counts and input metadata.

    All outputs are written even when inputs are absent (dry-run mode), so
    downstream pipeline steps can always consume the output directory.
    """
    args = parse_args()

    # Load all three input CSVs; each returns [] gracefully if the file is absent.
    gold_rows = read_csv(args.annotator_gold)
    audit_rows = read_csv(args.atomic_rule_audit)
    visual_rows = read_csv(args.visual_findings)

    # Apply the audit filter to split gold rows into verified vs excluded.
    verified, excluded = build_verified_rows(gold_rows, audit_rows, args.include_unaudited)
    # Reproject audit rows for the quality dashboard.
    rule_quality = atomic_rule_quality_rows(audit_rows)
    # Collect visual findings that lack an atomic rule link.
    coverage_gaps = coverage_gap_rows(visual_rows, audit_rows)

    output_dir = args.output_dir
    write_csv(output_dir / "verified_evaluation_gold.csv", verified, VERIFIED_GOLD_COLUMNS)
    write_csv(output_dir / "excluded_gold_rows.csv", excluded, EXCLUDED_GOLD_COLUMNS)
    write_csv(output_dir / "atomic_rule_quality_report.csv", rule_quality, ATOMIC_RULE_QUALITY_COLUMNS)
    write_csv(output_dir / "coverage_gap_report.csv", coverage_gaps, COVERAGE_GAP_COLUMNS)

    # Build the summary dict; audit_validity_counts breaks down rule review
    # outcomes (correct / incorrect / ambiguous / skip) for a quick QA check.
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
        # Sorted for stable diff output across runs.
        "audit_validity_counts": dict(sorted(Counter(row.get("rule_validity", "") for row in audit_rows).items())),
        "outputs": [
            "verified_evaluation_gold.csv",
            "excluded_gold_rows.csv",
            "atomic_rule_quality_report.csv",
            "coverage_gap_report.csv",
        ],
    }
    write_json(output_dir / "summary.json", summary)
    # Print a machine-readable one-liner for Claude Code to capture.
    print(json.dumps({"status": "finished", **summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
