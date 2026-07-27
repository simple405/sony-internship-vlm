"""Tests for validate_human_annotations.py — schema validation, cross-view consistency."""
import csv
import json
import io
from pathlib import Path

import pytest

from vlm.scripts.supervise.validate_human_annotations import (
    missing_columns,
    status,
    load_atomic_rule_map,
    validate_known_sample,
    validate_known_rule,
    validate_visual_findings,
    validate_annotator_gold,
    validate_atomic_rule_audit,
    read_csv,
    VISUAL_ISSUE_TYPES,
    ERROR_STATUSES,
)


# ---------------------------------------------------------------------------
# missing_columns / status
# ---------------------------------------------------------------------------

def test_missing_columns_all_present():
    assert missing_columns(["a", "b", "c"], ["a", "b"]) == []

def test_missing_columns_some_missing():
    assert missing_columns(["a"], ["a", "b"]) == ["b"]

def test_status_fail():
    assert status(["err"], []) == "FAIL"

def test_status_warn():
    assert status([], ["w"]) == "WARN"

def test_status_pass():
    assert status([], []) == "PASS"

def test_status_fail_takes_priority_over_warn():
    assert status(["err"], ["w"]) == "FAIL"


# ---------------------------------------------------------------------------
# load_atomic_rule_map
# ---------------------------------------------------------------------------

def _json_path(tmp_path, data):
    p = tmp_path / "rules.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p

def test_load_atomic_rule_map_wrapper_form(tmp_path):
    p = _json_path(tmp_path, {"atomic_rules": [{"rule_id": "hair_color", "value": "red"}]})
    result = load_atomic_rule_map(p)
    assert result == {"hair_color": "red"}

def test_load_atomic_rule_map_bare_list(tmp_path):
    p = _json_path(tmp_path, [{"rule_id": "eye_color", "value": "blue"}])
    result = load_atomic_rule_map(p)
    assert result == {"eye_color": "blue"}

def test_load_atomic_rule_map_alias_id(tmp_path):
    p = _json_path(tmp_path, [{"id": "outfit_type", "value": "dress"}])
    result = load_atomic_rule_map(p)
    assert result == {"outfit_type": "dress"}

def test_load_atomic_rule_map_alias_name(tmp_path):
    p = _json_path(tmp_path, [{"name": "boot_color", "value": "black"}])
    result = load_atomic_rule_map(p)
    assert result == {"boot_color": "black"}

def test_load_atomic_rule_map_missing_file(tmp_path):
    result = load_atomic_rule_map(tmp_path / "nonexistent.json")
    assert result == {}

def test_load_atomic_rule_map_bad_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    result = load_atomic_rule_map(p)
    assert result == {}


# ---------------------------------------------------------------------------
# validate_known_sample / validate_known_rule
# ---------------------------------------------------------------------------

def _registry(sample_id="s1", category="backpack", rule_id="hair_color", value="red"):
    return {sample_id: {"category": category, "atomic_rules": "", "rule_map": {rule_id: value}}}

def test_validate_known_sample_no_registry():
    issues, warnings = [], []
    validate_known_sample({"sample_id": "s1"}, {}, issues, warnings)
    assert issues == [] and warnings == []

def test_validate_known_sample_unknown():
    issues, warnings = [], []
    validate_known_sample({"sample_id": "unknown"}, _registry(), issues, warnings)
    assert "unknown_sample_id" in issues

def test_validate_known_sample_category_mismatch():
    issues, warnings = [], []
    validate_known_sample({"sample_id": "s1", "category": "plush"}, _registry(), issues, warnings)
    assert any("category_mismatch" in w for w in warnings)

def test_validate_known_rule_unknown_rule():
    issues, warnings = [], []
    row = {"sample_id": "s1", "rule_id": "nonexistent"}
    validate_known_rule(row, _registry(), issues, warnings)
    assert "rule_id_not_in_atomic_rules" in issues

def test_validate_known_rule_value_mismatch_is_warning():
    issues, warnings = [], []
    row = {"sample_id": "s1", "rule_id": "hair_color", "atomic_value": "blue"}
    validate_known_rule(row, _registry(), issues, warnings)
    assert "atomic_value_differs_from_source" in warnings


# ---------------------------------------------------------------------------
# CSV helpers for writing test data
# ---------------------------------------------------------------------------

def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# validate_visual_findings
# ---------------------------------------------------------------------------

VISUAL_COLS = ["sample_id", "category", "finding_id", "view", "issue_type", "feature_key"]

def test_validate_visual_findings_valid(tmp_path):
    p = tmp_path / "vf.csv"
    _write_csv(p, [{"sample_id": "s1", "category": "backpack", "finding_id": "f1",
                    "view": "front", "issue_type": "wrong color", "feature_key": "hair"}],
               VISUAL_COLS)
    report = validate_visual_findings(p, {})
    assert all(r["qc_status"] == "PASS" for r in report)

def test_validate_visual_findings_missing_required_col(tmp_path):
    p = tmp_path / "vf.csv"
    _write_csv(p, [], ["sample_id", "category"])  # missing finding_id, view, issue_type
    report = validate_visual_findings(p, {})
    assert len(report) == 1 and report[0]["qc_status"] == "FAIL"

def test_validate_visual_findings_invalid_issue_type(tmp_path):
    p = tmp_path / "vf.csv"
    _write_csv(p, [{"sample_id": "s1", "category": "backpack", "finding_id": "f1",
                    "view": "front", "issue_type": "invalid_type", "feature_key": "hair"}],
               VISUAL_COLS)
    report = validate_visual_findings(p, {})
    assert any("invalid_issue_type" in r["issues"] for r in report)

def test_validate_visual_findings_duplicate_finding_id(tmp_path):
    p = tmp_path / "vf.csv"
    row = {"sample_id": "s1", "category": "backpack", "finding_id": "f1",
           "view": "front", "issue_type": "wrong color", "feature_key": "hair"}
    _write_csv(p, [row, row], VISUAL_COLS)
    report = validate_visual_findings(p, {})
    issues_all = ";".join(r["issues"] for r in report)
    assert "duplicate_finding_id_for_sample" in issues_all


# ---------------------------------------------------------------------------
# validate_annotator_gold — cross-view consistency check
# ---------------------------------------------------------------------------

GOLD_COLS = ["sample_id", "rule_id", "value", "front_visible", "front_status",
             "side_visible", "side_status", "back_visible", "back_status", "result"]

def _gold_row_dict(result="correct", front_status="correct", side_status="correct",
                   back_status="correct"):
    return {"sample_id": "s1", "rule_id": "hair_color", "value": "red",
            "front_visible": "visible", "front_status": front_status,
            "side_visible": "visible", "side_status": side_status,
            "back_visible": "visible", "back_status": back_status,
            "result": result}

def test_validate_annotator_gold_all_correct(tmp_path):
    p = tmp_path / "gold.csv"
    _write_csv(p, [_gold_row_dict()], GOLD_COLS)
    report = validate_annotator_gold(p, {})
    assert all(r["qc_status"] == "PASS" for r in report)

def test_validate_annotator_gold_cross_view_mismatch_false_wrong(tmp_path):
    """All views correct but result='wrong' → FAIL."""
    p = tmp_path / "gold.csv"
    _write_csv(p, [_gold_row_dict(result="wrong")], GOLD_COLS)
    report = validate_annotator_gold(p, {})
    assert any("result_mismatch_expected_correct" in r["issues"] for r in report)

def test_validate_annotator_gold_cross_view_mismatch_false_correct(tmp_path):
    """Front has ERROR_STATUS but result='correct' → FAIL."""
    p = tmp_path / "gold.csv"
    _write_csv(p, [_gold_row_dict(front_status="wrong color", result="correct")], GOLD_COLS)
    report = validate_annotator_gold(p, {})
    assert any("result_mismatch_expected_wrong" in r["issues"] for r in report)

def test_validate_annotator_gold_wrong_result_matches_error_status(tmp_path):
    """Front has ERROR_STATUS and result='wrong' → PASS."""
    p = tmp_path / "gold.csv"
    _write_csv(p, [_gold_row_dict(front_status="wrong color", result="wrong")], GOLD_COLS)
    report = validate_annotator_gold(p, {})
    assert all("result_mismatch" not in r["issues"] for r in report)

def test_validate_annotator_gold_invisible_correct_status(tmp_path):
    """visible=invisible, status=correct → valid."""
    row = _gold_row_dict()
    row["back_visible"] = "invisible"
    row["back_status"] = "correct"
    p = tmp_path / "gold.csv"
    _write_csv(p, [row], GOLD_COLS)
    report = validate_annotator_gold(p, {})
    assert all("invalid_back_status" not in r["issues"] for r in report)

def test_validate_annotator_gold_invisible_wrong_status_invalid(tmp_path):
    """visible=invisible, status='wrong color' (only valid for visible) → FAIL."""
    row = _gold_row_dict()
    row["back_visible"] = "invisible"
    row["back_status"] = "wrong color"
    p = tmp_path / "gold.csv"
    _write_csv(p, [row], GOLD_COLS)
    report = validate_annotator_gold(p, {})
    assert any("invalid_back_status_for_invisible" in r["issues"] for r in report)

def test_validate_annotator_gold_duplicate_rule_id(tmp_path):
    p = tmp_path / "gold.csv"
    row = _gold_row_dict()
    _write_csv(p, [row, row], GOLD_COLS)
    report = validate_annotator_gold(p, {})
    issues_all = ";".join(r["issues"] for r in report)
    assert "duplicate_rule_id_for_sample" in issues_all


# ---------------------------------------------------------------------------
# validate_atomic_rule_audit
# ---------------------------------------------------------------------------

AUDIT_COLS = ["sample_id", "category", "rule_id", "rule_key", "atomic_value",
              "rule_validity", "corrected_value", "reason", "annotator_id", "annotation_batch"]

def _audit_row_dict(rule_validity="correct", corrected_value="", reason=""):
    return {"sample_id": "s1", "category": "backpack", "rule_id": "hair_color",
            "rule_key": "hair_color", "atomic_value": "red",
            "rule_validity": rule_validity, "corrected_value": corrected_value,
            "reason": reason, "annotator_id": "a1", "annotation_batch": "b1"}

def test_validate_atomic_rule_audit_correct(tmp_path):
    p = tmp_path / "audit.csv"
    _write_csv(p, [_audit_row_dict()], AUDIT_COLS)
    report = validate_atomic_rule_audit(p, {})
    assert all(r["qc_status"] == "PASS" for r in report)

def test_validate_atomic_rule_audit_wrong_value_missing_corrected(tmp_path):
    p = tmp_path / "audit.csv"
    _write_csv(p, [_audit_row_dict(rule_validity="wrong_value")], AUDIT_COLS)
    report = validate_atomic_rule_audit(p, {})
    assert any("missing_corrected_value_for_wrong_value" in r["issues"] for r in report)

def test_validate_atomic_rule_audit_wrong_value_with_corrected(tmp_path):
    p = tmp_path / "audit.csv"
    _write_csv(p, [_audit_row_dict(rule_validity="wrong_value",
                                   corrected_value="blue", reason="color error")], AUDIT_COLS)
    report = validate_atomic_rule_audit(p, {})
    assert all("missing_corrected_value" not in r["issues"] for r in report)

def test_validate_atomic_rule_audit_non_correct_without_reason_is_warning(tmp_path):
    p = tmp_path / "audit.csv"
    _write_csv(p, [_audit_row_dict(rule_validity="ambiguous")], AUDIT_COLS)
    report = validate_atomic_rule_audit(p, {})
    assert any("non_correct_without_reason" in r["warnings"] for r in report)

def test_validate_atomic_rule_audit_invalid_validity(tmp_path):
    p = tmp_path / "audit.csv"
    _write_csv(p, [_audit_row_dict(rule_validity="bogus_value")], AUDIT_COLS)
    report = validate_atomic_rule_audit(p, {})
    assert any("invalid_rule_validity" in r["issues"] for r in report)


# ---------------------------------------------------------------------------
# read_csv helper (the bug was here — verify it now works)
# ---------------------------------------------------------------------------

def test_read_csv_basic(tmp_path):
    p = tmp_path / "test.csv"
    _write_csv(p, [{"a": "1", "b": " hello "}], ["a", "b"])
    header, rows = read_csv(p)
    assert header == ["a", "b"]
    assert rows[0]["b"] == "hello"  # stripped

def test_read_csv_bom(tmp_path):
    p = tmp_path / "bom.csv"
    p.write_bytes(b"\xef\xbb\xbfcol1,col2\r\nval1,val2\r\n")
    header, rows = read_csv(p)
    assert header[0] == "col1"
    assert rows[0]["col1"] == "val1"

