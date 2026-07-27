"""Integration test: fake CSV data through the full annotation pipeline.

validate_human_annotations → align_human_findings_to_atomic_rules
→ build_verified_evaluation_gold → compare_predictions

All file I/O uses pytest's tmp_path; no real API calls are made.
"""

import csv
import json
from pathlib import Path

import pytest

from vlm.scripts.supervise.validate_human_annotations import (
    validate_visual_findings,
    validate_annotator_gold,
    validate_atomic_rule_audit,
)
from vlm.scripts.supervise.build_verified_evaluation_gold import (
    build_verified_rows,
    audit_index,
)
from vlm.scripts.supervise.compare_predictions import (
    compute_metrics,
    match_events,
    extract_gold_events,
)


def _write_csv(path: Path, rows, fieldnames):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Stage 1 → Stage 3 → compare
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_data(tmp_path):
    """Create a minimal fake dataset with 2 rules, 1 sample."""
    atomic_rules = [
        {"rule_id": "hair_color", "value": "red"},
        {"rule_id": "outfit_type", "value": "dress"},
    ]
    rules_path = tmp_path / "atomic_rules.json"
    rules_path.write_text(
        json.dumps({"atomic_rules": atomic_rules}, ensure_ascii=False),
        encoding="utf-8",
    )

    # Stage 1 annotator gold: 2 rules, one correct, one wrong
    gold_rows = [
        {
            "sample_id": "s1", "rule_id": "hair_color", "value": "red",
            "front_visible": "visible", "front_status": "wrong color",
            "side_visible": "visible", "side_status": "correct",
            "back_visible": "visible", "back_status": "correct",
            "result": "wrong", "issue_type": "wrong color",
            "confidence": "high", "reason": "pink instead of red",
        },
        {
            "sample_id": "s1", "rule_id": "outfit_type", "value": "dress",
            "front_visible": "visible", "front_status": "correct",
            "side_visible": "visible", "side_status": "correct",
            "back_visible": "visible", "back_status": "correct",
            "result": "correct", "issue_type": "",
            "confidence": "high", "reason": "",
        },
    ]
    gold_cols = ["sample_id", "rule_id", "value", "front_visible", "front_status",
                 "side_visible", "side_status", "back_visible", "back_status",
                 "result", "issue_type", "confidence", "reason"]
    gold_path = tmp_path / "annotator_gold.csv"
    _write_csv(gold_path, gold_rows, gold_cols)

    # Stage 2 atomic rule audit: both rules are correct
    audit_rows = [
        {"sample_id": "s1", "category": "backpack", "rule_id": "hair_color",
         "rule_key": "hair_color", "atomic_value": "red",
         "rule_validity": "correct", "corrected_value": "", "reason": "",
         "annotator_id": "a1", "annotation_batch": "b1"},
        {"sample_id": "s1", "category": "backpack", "rule_id": "outfit_type",
         "rule_key": "outfit_type", "atomic_value": "dress",
         "rule_validity": "correct", "corrected_value": "", "reason": "",
         "annotator_id": "a1", "annotation_batch": "b1"},
    ]
    audit_cols = ["sample_id", "category", "rule_id", "rule_key", "atomic_value",
                  "rule_validity", "corrected_value", "reason", "annotator_id", "annotation_batch"]
    audit_path = tmp_path / "atomic_rule_audit.csv"
    _write_csv(audit_path, audit_rows, audit_cols)

    return {
        "tmp_path": tmp_path,
        "gold_path": gold_path,
        "audit_path": audit_path,
        "rules_path": rules_path,
        "gold_rows": gold_rows,
        "audit_rows": audit_rows,
    }


def test_stage1_gold_validation_passes(sample_data):
    """Stage 1: annotator_gold.csv passes validation with no FAIL rows."""
    gold_path = sample_data["gold_path"]
    report = validate_annotator_gold(gold_path, {})
    fail_rows = [r for r in report if r["qc_status"] == "FAIL"]
    assert fail_rows == [], f"Unexpected FAIL rows: {fail_rows}"


def test_stage2_audit_validation_passes(sample_data):
    """Stage 2: atomic_rule_audit.csv passes validation."""
    audit_path = sample_data["audit_path"]
    audit_cols = ["sample_id", "category", "rule_id", "rule_key", "atomic_value",
                  "rule_validity", "corrected_value", "reason", "annotator_id", "annotation_batch"]
    report = validate_atomic_rule_audit(audit_path, {})
    fail_rows = [r for r in report if r["qc_status"] == "FAIL"]
    assert fail_rows == []


def test_stage3_build_verified_gold_promotes_correct_rules(sample_data):
    """Stage 3: build_verified_rows promotes both rows (both rules are correct)."""
    gold_rows = sample_data["gold_rows"]
    audit_rows = sample_data["audit_rows"]
    verified, excluded = build_verified_rows(gold_rows, audit_rows, include_unaudited=False)
    assert len(verified) == 2
    assert len(excluded) == 0


def test_stage3_verified_gold_contains_wrong_rule(sample_data):
    """The 'wrong color' finding for hair_color is in the verified gold."""
    gold_rows = sample_data["gold_rows"]
    audit_rows = sample_data["audit_rows"]
    verified, _ = build_verified_rows(gold_rows, audit_rows, include_unaudited=False)
    wrong_rules = [r for r in verified if r["result"] == "wrong"]
    assert len(wrong_rules) == 1
    assert wrong_rules[0]["rule_id"] == "hair_color"


def test_compare_predictions_perfect_model(sample_data):
    """Model that flags exactly the same issue as gold → precision=recall=F1=1.0."""
    gold_rows = sample_data["gold_rows"]
    audit_rows = sample_data["audit_rows"]
    verified, _ = build_verified_rows(gold_rows, audit_rows, include_unaudited=False)

    gold_events = extract_gold_events(verified, "s1", "backpack")
    # Simulate perfect model prediction: same event
    pred_events = [dict(e) for e in gold_events]
    matched, fp, fn = match_events(pred_events, gold_events, strict=True)
    metrics = compute_metrics(matched, fp, fn)
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["f1"] == 1.0


def test_compare_predictions_missing_model(sample_data):
    """Model that flags nothing → precision undefined (0), recall=0."""
    gold_rows = sample_data["gold_rows"]
    audit_rows = sample_data["audit_rows"]
    verified, _ = build_verified_rows(gold_rows, audit_rows, include_unaudited=False)
    gold_events = extract_gold_events(verified, "s1", "backpack")

    matched, fp, fn = match_events([], gold_events, strict=True)
    metrics = compute_metrics(matched, fp, fn)
    assert metrics["recall"] == 0.0
    assert metrics["fn"] > 0


def test_compare_predictions_over_flagging_model(sample_data):
    """Model that flags everything as wrong → low precision."""
    gold_rows = sample_data["gold_rows"]
    audit_rows = sample_data["audit_rows"]
    verified, _ = build_verified_rows(gold_rows, audit_rows, include_unaudited=False)
    gold_events = extract_gold_events(verified, "s1", "backpack")

    # Predict issues for ALL rules (correct + wrong), only 1 is actually wrong
    fake_pred_events = [
        {"sample_id": "s1", "category": "backpack", "view": "front",
         "issue_type": "wrong color", "rule_id": "hair_color",
         "attribute": "color", "element_name": "hair_color",
         "confidence": 0.9, "reason": ""},
        {"sample_id": "s1", "category": "backpack", "view": "front",
         "issue_type": "wrong color", "rule_id": "outfit_type",
         "attribute": "color", "element_name": "outfit_type",
         "confidence": 0.9, "reason": ""},
    ]
    matched, fp, fn = match_events(fake_pred_events, gold_events, strict=True)
    metrics = compute_metrics(matched, fp, fn)
    # 1 TP, 1 FP, 0 FN → precision=0.5
    assert metrics["precision"] < 1.0
    assert metrics["fp"] >= 1
