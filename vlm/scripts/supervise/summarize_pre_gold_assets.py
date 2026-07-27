"""Summarize pre-gold supervision assets and blocked evaluation steps.

WHAT IS "PRE-GOLD"?
--------------------
The annotation pipeline progresses through several stages before a verified
evaluation gold set exists:

  Stage 0 – Sample configs + atomic rule JSON files
      VLM pipeline runs use JSON files that describe which product images to
      evaluate and which atomic rules to check.  These are the authoritative
      inputs for the entire pipeline.

  Stage 1 – Human visual findings / annotator gold
      Human annotators inspect sample images and fill in annotation CSVs.
      Until these are returned, any downstream accuracy measurements are
      blocked.

  Stage 2 – Atomic rule audit
      A second reviewer validates the atomic rules themselves.  Until this
      is done, ``build_verified_evaluation_gold.py`` cannot produce a gold set.

  Stage 3 – Verified evaluation gold
      Produced by ``build_verified_evaluation_gold.py`` after Stages 1 and 2.

"Pre-gold" refers to the state of the pipeline BEFORE Stage 3 is available:
sample configs and Qwen prediction caches exist, but human annotations or rule
audits have not yet been returned.  This script inventories what IS available
so the team can communicate current status, identify which evaluation steps are
blocked, and plan follow-up actions — all without requiring human gold data or
Qwen API quota.

ASSETS INVENTORIED
------------------
1. **Sample configs** (``--sample-config``)
   One or more JSON files describing the evaluation samples.  Each file may
   contain a flat list of sample dicts or a ``{"samples": [...]}`` envelope.
   Inventoried into ``sample_config_inventory.csv``.

2. **Human visual findings** (``--visual-findings``)
   Optional ``human_visual_findings.csv`` returned by annotators.  If absent,
   the final coverage/generation quality metrics step is marked as blocked.

3. **Atomic rule audit** (``--atomic-rule-audit``)
   Optional ``atomic_rule_audit.csv`` from the rule reviewer.  If absent,
   atomic rule quality metrics are blocked.

4. **Mapping candidates** (``--mapping-candidates``)
   Optional ``human_to_atomic_rule_mapping_candidates.csv`` linking visual
   findings to atomic rules.  Counted in summary.json but not written to a
   separate inventory CSV (used only for count reporting).

5. **Verified gold** (``--verified-gold``)
   Optional ``verified_evaluation_gold.csv``.  If absent, Qwen accuracy
   measurement is blocked.

6. **Qwen prediction caches** (``--qwen-output-root``)
   ``summary.json`` files under a multicategory review output directory
   (default ``vlm/tmp/multicategory_supervision_review_v3``).  Each summary
   captures model name, rule counts, and QC pass/warn/fail tallies.
   Inventoried into ``qwen_prediction_inventory.csv``.

7. **Qwen quota status** (``--qwen-quota-blocked``)
   A boolean flag.  When set, the expanded baseline prediction step is marked
   as blocked even if the Qwen output root has some existing results.

This script is deliberately descriptive: it does not require human gold data
or API quota, and it does not write any new prediction or annotation data.
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Define and parse command-line arguments.

    Returns
    -------
    argparse.Namespace
        Parsed argument object.  Key fields:

        * ``sample_config``      – zero or more sample config JSON paths
          (``action="append"`` means the flag can be repeated).
        * ``visual_findings``    – optional path to human_visual_findings.csv.
        * ``atomic_rule_audit``  – optional path to atomic_rule_audit.csv.
        * ``mapping_candidates`` – optional path to mapping candidates CSV.
        * ``verified_gold``      – optional path to verified_evaluation_gold.csv.
        * ``qwen_output_root``   – root directory containing Qwen prediction
          subdirectories (default ``vlm/tmp/multicategory_supervision_review_v3``).
        * ``qwen_quota_blocked`` – flag indicating Qwen API quota is unavailable.
        * ``output_dir``         – destination directory for all summary outputs.
    """
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


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def read_csv_rows(path: Path | None) -> list[dict[str, str]]:
    """Read a CSV file into a list of stripped row dicts.

    Returns an empty list without error when ``path`` is ``None`` or the file
    does not exist.  This supports the script's "inventory what's available"
    philosophy — absent inputs are noted in the blocked steps rather than
    causing a crash.

    Parameters
    ----------
    path:
        Path to the CSV file, or ``None`` if the argument was not provided.

    Returns
    -------
    list[dict[str, str]]
        One dict per data row, keyed by column header.  Empty list if the file
        is absent.
    """
    if path is None or not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def read_sample_configs(paths: list[Path]) -> list[dict[str, Any]]:
    """Load one or more sample config JSON files into a flat sample list.

    Each config file may use either format:
    * A JSON array at the top level: ``[{...}, {...}]``
    * A JSON object with a ``"samples"`` key: ``{"samples": [{...}, {...}]}``

    Each sample dict is augmented with a ``"sample_config"`` key recording
    which config file it came from.  This allows the inventory CSV to show
    provenance when multiple config files are provided.

    Parameters
    ----------
    paths:
        List of config JSON file paths.

    Returns
    -------
    list[dict[str, Any]]
        Flat list of sample dicts from all provided config files, in file order.
    """
    samples: list[dict[str, Any]] = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        # Handle both top-level array and {"samples": [...]} envelope formats.
        raw_samples = data if isinstance(data, list) else data.get("samples", [])
        for sample in raw_samples:
            item = dict(sample)
            # Tag each sample with its source config file for traceability.
            item["sample_config"] = str(path)
            samples.append(item)
    return samples


# ---------------------------------------------------------------------------
# Qwen prediction inventory
# ---------------------------------------------------------------------------

def qwen_prediction_inventory(root: Path) -> list[dict[str, Any]]:
    """Scan a Qwen output root directory and inventory all completed prediction runs.

    The expected directory structure is::

        <root>/
          <category>/
            <sample_run_dir>/
              summary.json   ← detected by this glob
              ...

    Each ``summary.json`` is expected to contain fields like ``category``,
    ``sample_id``, ``model_name``, ``requested_rule_count``,
    ``returned_rule_count``, and ``qc_counts`` (a dict with PASS/WARN/FAIL
    keys).  Missing fields fall back to reasonable defaults derived from the
    directory path.

    Parameters
    ----------
    root:
        Root directory of the multicategory Qwen review output (e.g.
        ``vlm/tmp/multicategory_supervision_review_v3``).

    Returns
    -------
    list[dict[str, Any]]
        One dict per found summary.json, with normalised keys.  Files that
        cannot be read or parsed (OSError, JSON decode error, encoding error)
        are silently skipped.
    """
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    # Glob for all summary.json files two levels deep: category/sample_run/summary.json
    for summary_path in sorted(root.glob("*/*/summary.json")):
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            # Silently skip corrupted or partially written summary files.
            continue
        rows.append(
            {
                # Fall back to parent directory names if the summary omits category/sample_id.
                "category": summary.get("category", summary_path.parent.parent.name),
                "sample_id": summary.get("sample_id", summary_path.parent.name.split("_v3_")[0]),
                "output_dir": str(summary_path.parent),
                "model_name": summary.get("model_name", ""),
                "requested_rule_count": summary.get("requested_rule_count", ""),
                "returned_rule_count": summary.get("returned_rule_count", ""),
                # QC counts are nested inside qc_counts dict; default "" if absent.
                "qc_pass": summary.get("qc_counts", {}).get("PASS", ""),
                "qc_warn": summary.get("qc_counts", {}).get("WARN", ""),
                "qc_fail": summary.get("qc_counts", {}).get("FAIL", ""),
            }
        )
    return rows


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
        Ordered column names; extra dict keys are silently ignored.
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
# Analysis helpers
# ---------------------------------------------------------------------------

def category_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Count rows by their ``category`` field and return a sorted dict.

    Parameters
    ----------
    rows:
        List of dicts each expected to have a ``"category"`` key.

    Returns
    -------
    dict[str, int]
        Category name → row count, sorted alphabetically by category name
        for stable output across runs.
    """
    return dict(sorted(Counter(str(row.get("category", "")) for row in rows).items()))


def blocked_steps(
    args: argparse.Namespace,
    visual_rows: list[dict[str, str]],
    audit_rows: list[dict[str, str]],
    verified_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Determine which evaluation steps are currently blocked and why.

    Each blocking condition is checked independently; multiple steps can be
    blocked simultaneously.  The output is a list of ``{step, blocked_by}``
    dicts intended to communicate current pipeline status to the team.

    Blocked conditions:

    * Human visual findings not received
        → "final coverage/generation quality metrics" is blocked.
    * Atomic rule audit not received
        → "atomic rule quality metrics" is blocked.
    * Verified evaluation gold not built
        → "Qwen accuracy against verified gold" is blocked.
    * ``--qwen-quota-blocked`` flag set
        → "expanded Qwen baseline prediction" is blocked.

    Parameters
    ----------
    args:
        Parsed CLI arguments (checked for ``qwen_quota_blocked``).
    visual_rows:
        Rows from human_visual_findings.csv (empty list if absent).
    audit_rows:
        Rows from atomic_rule_audit.csv (empty list if absent).
    verified_rows:
        Rows from verified_evaluation_gold.csv (empty list if absent).

    Returns
    -------
    list[dict[str, str]]
        One dict per blocked step, each with ``step`` and ``blocked_by`` keys.
        Empty list if no steps are currently blocked.
    """
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Load all available assets, write inventory CSVs, and print a summary.

    Execution flow:
    1. Parse CLI arguments.
    2. Load all available assets (sample configs, annotation CSVs, Qwen
       prediction summaries).
    3. Determine which evaluation steps are currently blocked.
    4. Write output files:
       * ``sample_config_inventory.csv`` – one row per sample from all config files.
       * ``qwen_prediction_inventory.csv`` – one row per Qwen summary.json found.
       * ``blocked_steps.csv`` – one row per blocked evaluation step.
       * ``summary.json`` – all counts and metadata in a single JSON file.
    5. Print a machine-readable one-liner summary to stdout.

    All outputs are written even when some inputs are absent, so consumers
    always find the output directory in a consistent state.
    """
    args = parse_args()

    # Load all available inputs; each returns [] gracefully if absent.
    samples = read_sample_configs(args.sample_config)
    visual_rows = read_csv_rows(args.visual_findings)
    audit_rows = read_csv_rows(args.atomic_rule_audit)
    mapping_rows = read_csv_rows(args.mapping_candidates)
    verified_rows = read_csv_rows(args.verified_gold)
    qwen_rows = qwen_prediction_inventory(args.qwen_output_root)
    blocked = blocked_steps(args, visual_rows, audit_rows, verified_rows)

    output_dir = args.output_dir

    # Write the three inventory CSVs.
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

    # Build the summary dict; sample_category_counts provides per-category
    # breakdowns for a quick cross-check against expected evaluation scope.
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

    # Print a machine-readable one-liner for Claude Code to capture.
    print(json.dumps({"status": "finished", **summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
