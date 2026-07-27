"""Tests for convert_annotation_xlsx_to_csv.py — column_index, detect_schema, rows_to_dicts."""

from vlm.scripts.supervise.convert_annotation_xlsx_to_csv import (
    column_index,
    detect_schema,
    rows_to_dicts,
    safe_output_name,
)
from pathlib import Path


# ---------------------------------------------------------------------------
# column_index — Excel A=0, Z=25, AA=26, AB=27, AZ=51, BA=52
# ---------------------------------------------------------------------------

def test_column_index_A():
    assert column_index("A1") == 0

def test_column_index_B():
    assert column_index("B5") == 1

def test_column_index_Z():
    assert column_index("Z99") == 25

def test_column_index_AA():
    assert column_index("AA1") == 26

def test_column_index_AB():
    assert column_index("AB3") == 27

def test_column_index_AZ():
    assert column_index("AZ1") == 51

def test_column_index_BA():
    assert column_index("BA1") == 52

def test_column_index_column_only():
    # Just the letter part, no row number
    assert column_index("C") == 2


# ---------------------------------------------------------------------------
# detect_schema
# ---------------------------------------------------------------------------

def test_detect_schema_human_visual_findings():
    header = ["sample_id", "finding_id", "view", "feature_key", "issue_type"]
    assert detect_schema(header) == "human_visual_findings"

def test_detect_schema_human_visual_findings_element_name():
    header = ["sample_id", "finding_id", "view", "element_name", "issue_type"]
    assert detect_schema(header) == "human_visual_findings"

def test_detect_schema_atomic_rule_audit():
    header = ["sample_id", "rule_id", "rule_validity", "atomic_value", "reason"]
    assert detect_schema(header) == "atomic_rule_audit"

def test_detect_schema_human_to_atomic_rule_mapping():
    header = ["human_finding_id", "atomic_rule_id", "candidate_match_type", "score"]
    assert detect_schema(header) == "human_to_atomic_rule_mapping"

def test_detect_schema_v3_rule_level():
    header = ["sample_id", "rule_id", "front_visible", "front_status",
              "side_visible", "side_status", "back_visible", "back_status"]
    assert detect_schema(header) == "v3_rule_level"

def test_detect_schema_unknown():
    header = ["foo", "bar", "baz"]
    assert detect_schema(header) == "unknown"

def test_detect_schema_strips_whitespace():
    # Columns with leading/trailing spaces should still match
    header = [" finding_id ", " view ", " feature_key "]
    # detect_schema uses set comprehension with strip
    assert detect_schema(header) == "human_visual_findings"


# ---------------------------------------------------------------------------
# rows_to_dicts
# ---------------------------------------------------------------------------

def test_rows_to_dicts_basic():
    rows = [["name", "value"], ["hair", "red"]]
    header, records = rows_to_dicts(rows)
    assert header == ["name", "value"]
    assert records == [{"name": "hair", "value": "red"}]

def test_rows_to_dicts_empty_input():
    header, records = rows_to_dicts([])
    assert header == [] and records == []

def test_rows_to_dicts_skips_blank_rows():
    rows = [["col1", "col2"], ["val1", "val2"], ["", ""], ["val3", "val4"]]
    header, records = rows_to_dicts(rows)
    assert len(records) == 2  # blank row is skipped

def test_rows_to_dicts_pads_short_rows():
    rows = [["a", "b", "c"], ["x"]]  # row has only 1 value, header has 3
    header, records = rows_to_dicts(rows)
    assert records[0]["b"] == ""
    assert records[0]["c"] == ""

def test_rows_to_dicts_strips_cell_whitespace():
    rows = [["col"], ["  value  "]]
    header, records = rows_to_dicts(rows)
    assert records[0]["col"] == "value"

def test_rows_to_dicts_header_only():
    rows = [["a", "b"]]
    header, records = rows_to_dicts(rows)
    assert header == ["a", "b"]
    assert records == []


# ---------------------------------------------------------------------------
# safe_output_name
# ---------------------------------------------------------------------------

def test_safe_output_name_basic():
    p = Path("some/dir/annotations.xlsx")
    assert safe_output_name(p) == "annotations.csv"

def test_safe_output_name_preserves_stem():
    p = Path("human_visual_findings_batch2.xlsx")
    assert safe_output_name(p) == "human_visual_findings_batch2.csv"
