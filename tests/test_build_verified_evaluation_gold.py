"""Tests for build_verified_evaluation_gold.py — audit_index, build_verified_rows, helpers."""

from vlm.scripts.supervise.build_verified_evaluation_gold import (
    audit_index,
    build_verified_rows,
    verified_row,
    atomic_rule_quality_rows,
    coverage_gap_rows,
)


# ---------------------------------------------------------------------------
# audit_index
# ---------------------------------------------------------------------------

def test_audit_index_basic():
    rows = [{"sample_id": "s1", "rule_id": "r1", "rule_validity": "correct", "reason": ""}]
    idx = audit_index(rows)
    assert ("s1", "r1") in idx
    assert idx[("s1", "r1")]["rule_validity"] == "correct"

def test_audit_index_duplicate_keeps_first():
    rows = [
        {"sample_id": "s1", "rule_id": "r1", "rule_validity": "correct", "reason": "first"},
        {"sample_id": "s1", "rule_id": "r1", "rule_validity": "incorrect", "reason": "second"},
    ]
    idx = audit_index(rows)
    assert idx[("s1", "r1")]["reason"] == "first"

def test_audit_index_skips_missing_keys():
    rows = [{"sample_id": "", "rule_id": "r1"}, {"sample_id": "s1", "rule_id": ""}]
    idx = audit_index(rows)
    assert len(idx) == 0

def test_audit_index_multiple_samples():
    rows = [
        {"sample_id": "s1", "rule_id": "r1", "rule_validity": "correct", "reason": ""},
        {"sample_id": "s2", "rule_id": "r1", "rule_validity": "incorrect", "reason": ""},
    ]
    idx = audit_index(rows)
    assert len(idx) == 2


# ---------------------------------------------------------------------------
# verified_row
# ---------------------------------------------------------------------------

def test_verified_row_uses_gold_value():
    gold = {"sample_id": "s1", "rule_id": "r1", "value": "red",
            "front_visible": "visible", "front_status": "correct",
            "side_visible": "visible", "side_status": "correct",
            "back_visible": "visible", "back_status": "correct",
            "result": "correct", "issue_type": "", "confidence": "high", "reason": ""}
    audit = {"rule_validity": "correct", "reason": "ok", "category": "backpack", "atomic_value": "blue"}
    row = verified_row(gold, audit)
    assert row["value"] == "red"  # gold value preferred

def test_verified_row_falls_back_to_atomic_value():
    gold = {"sample_id": "s1", "rule_id": "r1", "value": "",
            "front_visible": "visible", "front_status": "correct",
            "side_visible": "visible", "side_status": "correct",
            "back_visible": "visible", "back_status": "correct",
            "result": "correct", "issue_type": "", "confidence": "", "reason": ""}
    audit = {"rule_validity": "correct", "reason": "", "category": "backpack", "atomic_value": "blue"}
    row = verified_row(gold, audit)
    assert row["value"] == "blue"  # fallback to audit atomic_value

def test_verified_row_audit_provenance():
    gold = {"sample_id": "s1", "rule_id": "r1", "value": "red",
            "front_visible": "visible", "front_status": "correct",
            "side_visible": "visible", "side_status": "correct",
            "back_visible": "visible", "back_status": "correct",
            "result": "correct", "issue_type": "", "confidence": "", "reason": ""}
    audit = {"rule_validity": "correct", "reason": "reviewer note", "category": "plush", "atomic_value": "red"}
    row = verified_row(gold, audit)
    assert row["audit_rule_validity"] == "correct"
    assert row["audit_reason"] == "reviewer note"


# ---------------------------------------------------------------------------
# build_verified_rows
# ---------------------------------------------------------------------------

def _make_gold_row(sample_id="s1", rule_id="r1"):
    return {"sample_id": sample_id, "rule_id": rule_id, "value": "red",
            "front_visible": "visible", "front_status": "correct",
            "side_visible": "visible", "side_status": "correct",
            "back_visible": "visible", "back_status": "correct",
            "result": "correct", "issue_type": "", "confidence": "", "reason": ""}

def _make_audit_row(sample_id="s1", rule_id="r1", validity="correct"):
    return {"sample_id": sample_id, "rule_id": rule_id, "rule_validity": validity,
            "reason": "", "category": "backpack", "atomic_value": "red"}

def test_build_verified_rows_promotes_correct():
    gold = [_make_gold_row()]
    audit = [_make_audit_row(validity="correct")]
    verified, excluded = build_verified_rows(gold, audit, include_unaudited=False)
    assert len(verified) == 1
    assert len(excluded) == 0

def test_build_verified_rows_excludes_incorrect():
    gold = [_make_gold_row()]
    audit = [_make_audit_row(validity="incorrect")]
    verified, excluded = build_verified_rows(gold, audit, include_unaudited=False)
    assert len(verified) == 0
    assert len(excluded) == 1
    assert excluded[0]["exclude_reason"] == "rule_validity_incorrect"

def test_build_verified_rows_excludes_ambiguous():
    gold = [_make_gold_row()]
    audit = [_make_audit_row(validity="ambiguous")]
    verified, excluded = build_verified_rows(gold, audit, include_unaudited=False)
    assert len(excluded) == 1
    assert "ambiguous" in excluded[0]["exclude_reason"]

def test_build_verified_rows_missing_audit_excluded_by_default():
    gold = [_make_gold_row()]
    verified, excluded = build_verified_rows(gold, [], include_unaudited=False)
    assert len(verified) == 0
    assert excluded[0]["exclude_reason"] == "missing_audit"

def test_build_verified_rows_missing_audit_promoted_with_flag():
    gold = [_make_gold_row()]
    verified, excluded = build_verified_rows(gold, [], include_unaudited=True)
    assert len(verified) == 1
    assert verified[0]["audit_rule_validity"] == "unaudited"

def test_build_verified_rows_empty_inputs():
    verified, excluded = build_verified_rows([], [], include_unaudited=False)
    assert verified == [] and excluded == []


# ---------------------------------------------------------------------------
# atomic_rule_quality_rows
# ---------------------------------------------------------------------------

def test_atomic_rule_quality_rows_passthrough():
    audit = [{"sample_id": "s1", "category": "backpack", "rule_id": "r1",
              "atomic_value": "red", "rule_validity": "correct",
              "corrected_value": "", "reason": ""}]
    result = atomic_rule_quality_rows(audit)
    assert len(result) == 1
    assert result[0]["rule_validity"] == "correct"
    assert result[0]["atomic_value"] == "red"

def test_atomic_rule_quality_rows_empty():
    assert atomic_rule_quality_rows([]) == []


# ---------------------------------------------------------------------------
# coverage_gap_rows
# ---------------------------------------------------------------------------

def _visual_row(sample_id="s1"):
    return {"sample_id": sample_id, "category": "backpack", "finding_id": "f1",
            "view": "front", "issue_type": "wrong color", "feature_key": "hair",
            "expected_from_2d": "red", "observed_in_multiview": "blue", "severity": "major"}

def test_coverage_gap_rows_empty_visual():
    assert coverage_gap_rows([], []) == []

def test_coverage_gap_rows_audited_sample():
    audit = [{"sample_id": "s1", "rule_id": "r1"}]
    gaps = coverage_gap_rows([_visual_row("s1")], audit)
    assert len(gaps) == 1
    assert gaps[0]["gap_reason"] == "needs_rule_mapping"

def test_coverage_gap_rows_unaudited_sample():
    gaps = coverage_gap_rows([_visual_row("s1")], [])
    assert gaps[0]["gap_reason"] == "sample_not_in_rule_audit"
