"""Create CSV templates for pre-gold human annotation workflow.

PURPOSE
-------
Before human annotators can fill in annotation data, they need a structured
CSV template that:
1. Lists all samples they should annotate (pre-filled from sample configs).
2. Lists all atomic rules per sample (pre-filled from atomic_rules.json).
3. Provides empty columns for the annotator to fill in their observations.

This script generates those templates so annotators receive consistent,
pre-populated CSVs rather than blank files.  The templates serve as both
a data-entry form (annotators fill them in) and an import contract (the
downstream gold-building scripts expect these exact column names).

THREE TEMPLATE TYPES
---------------------
1. **human_visual_findings_template.csv**
   Free-form visual observation template.  One row per sample (not per rule).
   Annotators inspect the product images and record visual elements they
   observe — character appearance, clothing, accessories, defects, etc.
   Pre-filled columns: ``sample_id``, ``category``, ``severity`` (default
   "unknown").
   Annotator-filled columns: ``finding_id``, ``human_rule_name``,
   ``element_name``, ``attribute``, ``view``, ``bbox_2d``,
   ``bbox_multiview``, ``visible``, ``status``, ``match_status``,
   ``issue_type``, ``feature_key``, ``expected_value``, ``observed_value``,
   ``expected_from_2d``, ``observed_in_multiview``, ``source_2d_evidence``,
   ``multiview_evidence``, ``matched_rule_id``, ``reason``,
   ``annotator_id``, ``annotation_batch``.

2. **annotator_gold_template.csv**
   Per-rule verdict template.  One row per atomic rule per sample.
   Pre-filled columns: ``sample_id``, ``category``, ``rule_id``, ``value``
   (the expected value from the atomic rules JSON).
   Annotator-filled columns: ``front_visible``, ``front_status``,
   ``side_visible``, ``side_status``, ``back_visible``, ``back_status``,
   ``result``, ``issue_type``, ``confidence``, ``reason``, ``evidence``,
   ``annotator_id``, ``annotation_batch``.

3. **atomic_rule_audit_template.csv**
   Rule quality review template.  One row per atomic rule per sample.
   Pre-filled columns: ``sample_id``, ``category``, ``rule_id``,
   ``rule_key``, ``atomic_value``.
   Reviewer-filled columns: ``rule_validity`` (correct / incorrect /
   ambiguous / skip), ``corrected_value`` (if incorrect), ``reason``,
   ``annotator_id``, ``annotation_batch``.

COLUMN CONVENTIONS
------------------
* ``sample_id``      – unique identifier for the product sample.
* ``category``       – merchandise category (e.g. "figurine", "plush").
* ``rule_id``        – unique identifier for the atomic rule, sourced from
  the rule's ``rule_id``, ``id``, or ``name`` field (in that priority order).
* ``rule_key``       – alias for ``rule_id`` (kept for legacy compatibility).
* ``atomic_value``   – the rule's expected value as a string.
* ``annotator_id``   – filled by the annotator (their ID or initials).
* ``annotation_batch`` – filled by the annotator (batch label for tracking).

HOW TO USE THE TEMPLATES
-------------------------
1. Run this script with one or more ``--sample-config`` JSON files.
2. Distribute the three template CSVs to annotators / reviewers.
3. Annotators open the CSV in Excel or Google Sheets and fill in the empty
   columns row by row, using the pre-filled identifiers for reference.
4. Return the filled CSVs; feed them into
   ``build_verified_evaluation_gold.py`` as ``--annotator-gold`` and
   ``--atomic-rule-audit``.

With ``--per-sample``, per-sample subdirectories are also written under
``output_dir/by_sample/<category>/<sample_id>/``.  This is useful when each
annotator receives a separate package per product.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("vlm/tmp/human_annotation_templates")

# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------

# Columns for human_visual_findings_template.csv.
# Annotators fill all columns that are not pre-populated by this script.
# Pre-filled: sample_id, category, severity (default "unknown").
VISUAL_FINDINGS_COLUMNS = [
    "sample_id",            # pre-filled: unique sample identifier
    "category",             # pre-filled: merchandise category
    "finding_id",           # annotator fills: sequential finding ID (F001, F002, ...)
    "human_rule_name",      # annotator fills: free-text rule description
    "element_name",         # annotator fills: the visual element observed
    "attribute",            # annotator fills: the attribute being checked
    "view",                 # annotator fills: which view (front/side/back/top)
    "bbox_2d",              # annotator fills: bounding box on 2D source image
    "bbox_multiview",       # annotator fills: bounding box on multiview image
    "visible",              # annotator fills: yes/no/partial
    "status",               # annotator fills: correct/incorrect/unclear
    "match_status",         # annotator fills: matched/unmatched/partial_match
    "issue_type",           # annotator fills: color/shape/proportion/missing/extra
    "feature_key",          # annotator fills: machine-readable feature identifier
    "expected_value",       # annotator fills: what the rule says it should be
    "observed_value",       # annotator fills: what was actually observed
    "expected_from_2d",     # annotator fills: expected appearance from 2D design
    "observed_in_multiview",# annotator fills: actual observation in multiview photos
    "severity",             # pre-filled: "unknown" (annotator updates to critical/major/minor)
    "source_2d_evidence",   # annotator fills: reference to 2D design source
    "multiview_evidence",   # annotator fills: reference to supporting multiview photo
    "matched_rule_id",      # annotator fills: atomic rule ID matched to this finding
    "reason",               # annotator fills: free-text explanation
    "annotator_id",         # annotator fills: their identifier
    "annotation_batch",     # annotator fills: batch label for this annotation run
]

# Columns for annotator_gold_template.csv.
# Annotators fill per-rule verdicts for each sample/rule combination.
# Pre-filled: sample_id, category, rule_id, value.
ANNOTATOR_GOLD_COLUMNS = [
    "sample_id",            # pre-filled: unique sample identifier
    "category",             # pre-filled: merchandise category
    "rule_id",              # pre-filled: atomic rule identifier
    "value",                # pre-filled: expected value from atomic_rules.json
    "front_visible",        # annotator fills: yes/no/partial — front view
    "front_status",         # annotator fills: correct/incorrect/unclear — front view
    "side_visible",         # annotator fills: yes/no/partial — side view
    "side_status",          # annotator fills: correct/incorrect/unclear — side view
    "back_visible",         # annotator fills: yes/no/partial — back view
    "back_status",          # annotator fills: correct/incorrect/unclear — back view
    "result",               # annotator fills: overall pass/fail/unclear
    "issue_type",           # annotator fills: color/shape/proportion/missing/extra
    "confidence",           # annotator fills: high/medium/low
    "reason",               # annotator fills: free-text explanation
    "evidence",             # annotator fills: image crop or region reference
    "annotator_id",         # annotator fills: their identifier
    "annotation_batch",     # annotator fills: batch label
]

# Columns for atomic_rule_audit_template.csv.
# A second reviewer (not the original annotator) fills the validity columns.
# Pre-filled: sample_id, category, rule_id, rule_key, atomic_value.
ATOMIC_RULE_AUDIT_COLUMNS = [
    "sample_id",            # pre-filled: unique sample identifier
    "category",             # pre-filled: merchandise category
    "rule_id",              # pre-filled: atomic rule identifier
    "rule_key",             # pre-filled: alias for rule_id (legacy compatibility)
    "atomic_value",         # pre-filled: the rule's expected value
    "rule_validity",        # reviewer fills: correct / incorrect / ambiguous / skip
    "corrected_value",      # reviewer fills: the correct value if rule_validity=incorrect
    "reason",               # reviewer fills: explanation of the validity verdict
    "annotator_id",         # reviewer fills: their identifier
    "annotation_batch",     # reviewer fills: batch label
]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Define and parse command-line arguments.

    Returns
    -------
    argparse.Namespace
        Parsed argument object.  Key fields:

        * ``sample_config``  – one or more sample config JSON paths (required;
          ``action="append"`` allows the flag to be repeated for multiple files).
        * ``output_dir``     – destination directory for template CSVs.
        * ``per_sample``     – if True, also write per-sample template sets under
          ``output_dir/by_sample/<category>/<sample_id>/``.
    """
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


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def read_sample_configs(paths: list[Path]) -> list[dict[str, Any]]:
    """Load one or more sample config JSON files into a deduplicated sample list.

    Each config file may use either format:
    * A JSON array: ``[{"sample_id": "...", ...}, ...]``
    * A JSON object with a ``"samples"`` key: ``{"samples": [...]}``

    Deduplication is performed by ``(category, sample_id)`` composite key.
    The first occurrence of any duplicate is kept; later duplicates are
    silently dropped.  This prevents generating duplicate template rows when
    the same sample appears in multiple config files.

    Parameters
    ----------
    paths:
        List of config JSON file paths passed via ``--sample-config``.

    Returns
    -------
    list[dict[str, Any]]
        Deduplicated flat list of sample dicts, in order of first appearance.
    """
    samples: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        # Handle both top-level array and {"samples": [...]} envelope.
        raw_samples = data if isinstance(data, list) else data.get("samples", [])
        for sample in raw_samples:
            sample_id = str(sample.get("sample_id", "")).strip()
            category = str(sample.get("category", "")).strip()
            key = (category, sample_id)
            # Skip samples with no ID and skip duplicates.
            if not sample_id or key in seen:
                continue
            seen.add(key)
            samples.append(sample)
    return samples


def load_atomic_rules(path: Path) -> list[dict[str, str]]:
    """Load atomic rules from a JSON file and return a normalised rule list.

    The atomic_rules.json file may use one of two formats:
    * A JSON array: ``[{"rule_id": "R01", "value": "red"}, ...]``
    * A JSON object with an ``"atomic_rules"`` key: ``{"atomic_rules": [...]}``

    Each rule must have at least one identifier field: ``rule_id``, ``id``, or
    ``name`` (checked in that priority order).  Rules with no identifier are
    silently skipped.  The ``value`` field (the expected value) is converted to
    a string; missing values become empty strings.

    Parameters
    ----------
    path:
        Path to the atomic_rules.json file for this sample.

    Returns
    -------
    list[dict[str, str]]
        Normalised rule list; each dict has ``rule_id``, ``rule_key``
        (= ``rule_id``), and ``atomic_value`` keys.
    """
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    # Extract the rule list from either a dict wrapper or a bare array.
    raw_rules = data.get("atomic_rules", data) if isinstance(data, dict) else data
    rules: list[dict[str, str]] = []
    if not isinstance(raw_rules, list):
        return rules
    for item in raw_rules:
        if not isinstance(item, dict):
            continue
        # Try rule_id first, then id, then name as the canonical identifier.
        rule_id = str(item.get("rule_id") or item.get("id") or item.get("name") or "").strip()
        if not rule_id:
            continue  # Skip rules without any identifier.
        value = item.get("value", "")
        rules.append(
            {
                "rule_id": rule_id,
                "rule_key": rule_id,        # kept as a legacy alias
                "atomic_value": str(value),
            }
        )
    return rules


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    """Write a list of dicts to a CSV file with UTF-8 BOM for Excel compatibility.

    Parameters
    ----------
    path:
        Output CSV file path.  Parent directories are created if needed.
    rows:
        Data rows as dicts.
    fieldnames:
        Ordered column names; extra dict keys are silently ignored
        (``extrasaction="ignore"``).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    """Write a JSON file with UTF-8 encoding (no BOM).

    Parameters
    ----------
    path:
        Output JSON file path.  Parent directories are created if needed.
    payload:
        Any JSON-serialisable Python object.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Template row generation
# ---------------------------------------------------------------------------

def template_rows(
    samples: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Generate template rows for all three annotation templates.

    For each sample:
    * One ``visual_findings`` row is generated (one per sample, not per rule),
      with ``sample_id``, ``category``, and ``severity="unknown"`` pre-filled.
      Annotators add additional rows as needed for each finding they observe.
    * One ``annotator_gold`` row is generated per atomic rule, with
      ``sample_id``, ``category``, ``rule_id``, and ``value`` pre-filled.
    * One ``atomic_rule_audit`` row is generated per atomic rule, with
      ``sample_id``, ``category``, ``rule_id``, ``rule_key``, and
      ``atomic_value`` pre-filled.

    A manifest row is also generated per sample recording the sample's source
    images and rule count for reference.

    Parameters
    ----------
    samples:
        Deduplicated list of sample dicts from ``read_sample_configs``.

    Returns
    -------
    tuple[list[dict], list[dict], list[dict], list[dict]]
        ``(visual_rows, gold_rows, audit_rows, manifest)`` — four lists:
        * ``visual_rows`` – one pre-seeded row per sample for the visual
          findings template.
        * ``gold_rows``   – one pre-seeded row per (sample, rule) for the
          annotator gold template.
        * ``audit_rows``  – one pre-seeded row per (sample, rule) for the
          atomic rule audit template.
        * ``manifest``    – one row per sample listing metadata (image paths,
          rule count).
    """
    visual_rows: list[dict[str, Any]] = []
    gold_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []

    for sample in samples:
        sample_id = str(sample["sample_id"])
        category = str(sample.get("category", ""))
        # Load the atomic rules for this sample.
        rules = load_atomic_rules(Path(sample["atomic_rules"]))

        # Manifest row records the sample's image paths and rule count.
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

        # One visual findings template row per sample.
        # Only sample_id, category, and a default severity are pre-filled;
        # all observation columns are left blank for the annotator.
        visual_rows.append(
            {
                "sample_id": sample_id,
                "category": category,
                "finding_id": "",           # annotator fills (e.g. "F001")
                "severity": "unknown",      # annotator updates to critical/major/minor
            }
        )

        # One gold row and one audit row per atomic rule.
        for rule in rules:
            # Annotator gold: pre-fill sample/rule identity and expected value;
            # leave all verdict columns blank.
            gold_rows.append(
                {
                    "sample_id": sample_id,
                    "category": category,
                    "rule_id": rule["rule_id"],
                    "value": rule["atomic_value"],  # expected value from the rule JSON
                }
            )
            # Atomic rule audit: pre-fill sample/rule identity and expected value;
            # leave rule_validity, corrected_value, and reason blank for the reviewer.
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


# ---------------------------------------------------------------------------
# Per-sample output
# ---------------------------------------------------------------------------

def write_per_sample_templates(output_dir: Path, samples: list[dict[str, Any]]) -> None:
    """Write separate template CSV sets for each individual sample.

    Creates a directory tree::

        output_dir/
          by_sample/
            <category>/
              <sample_id>/
                human_visual_findings.csv
                annotator_gold.csv
                atomic_rule_audit.csv

    This layout is useful when distributing annotation work: each annotator
    receives a folder with only their assigned samples.

    Parameters
    ----------
    output_dir:
        The top-level output directory (same as ``args.output_dir``).
    samples:
        The deduplicated sample list; each sample is processed independently
        by calling ``template_rows`` on a one-element list.
    """
    for sample in samples:
        sample_id = str(sample["sample_id"])
        category = str(sample.get("category", ""))
        # Generate template rows for this single sample only.
        visual_rows, gold_rows, audit_rows, _ = template_rows([sample])
        sample_dir = output_dir / "by_sample" / category / sample_id
        write_csv(sample_dir / "human_visual_findings.csv", visual_rows, VISUAL_FINDINGS_COLUMNS)
        write_csv(sample_dir / "annotator_gold.csv", gold_rows, ANNOTATOR_GOLD_COLUMNS)
        write_csv(sample_dir / "atomic_rule_audit.csv", audit_rows, ATOMIC_RULE_AUDIT_COLUMNS)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Load sample configs, generate all template rows, and write output files.

    Output files written to ``--output-dir``:

    * ``human_visual_findings_template.csv`` – one row per sample (annotator fills).
    * ``annotator_gold_template.csv``        – one row per (sample, rule) (annotator fills).
    * ``atomic_rule_audit_template.csv``     – one row per (sample, rule) (reviewer fills).
    * ``template_manifest.csv``              – one row per sample with metadata.
    * ``summary.json``                       – row counts and generation metadata.

    With ``--per-sample``, also writes per-sample template sets under
    ``output_dir/by_sample/<category>/<sample_id>/``.
    """
    args = parse_args()

    # Load and deduplicate all samples from the provided config files.
    samples = read_sample_configs(args.sample_config)

    # Generate all template rows in a single pass over the sample list.
    visual_rows, gold_rows, audit_rows, manifest = template_rows(samples)

    output_dir = args.output_dir

    # Write the four combined output files.
    write_csv(output_dir / "human_visual_findings_template.csv", visual_rows, VISUAL_FINDINGS_COLUMNS)
    write_csv(output_dir / "annotator_gold_template.csv", gold_rows, ANNOTATOR_GOLD_COLUMNS)
    write_csv(output_dir / "atomic_rule_audit_template.csv", audit_rows, ATOMIC_RULE_AUDIT_COLUMNS)
    write_csv(
        output_dir / "template_manifest.csv",
        manifest,
        ["sample_id", "category", "source_image", "multiview_image", "atomic_rules", "rule_count"],
    )

    # Optionally write per-sample template sets.
    if args.per_sample:
        write_per_sample_templates(output_dir, samples)

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "sample_configs": [str(path) for path in args.sample_config],
        "samples": len(samples),
        "visual_template_rows": len(visual_rows),
        "gold_template_rows": len(gold_rows),       # equals total rule count across all samples
        "audit_template_rows": len(audit_rows),     # equals total rule count across all samples
        "per_sample": bool(args.per_sample),
        "outputs": [
            "human_visual_findings_template.csv",
            "annotator_gold_template.csv",
            "atomic_rule_audit_template.csv",
            "template_manifest.csv",
        ],
    }
    write_json(output_dir / "summary.json", summary)

    # Print a machine-readable one-liner for Claude Code to capture.
    print(json.dumps({"status": "finished", **summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
