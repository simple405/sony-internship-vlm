"""Build standard supervision annotation products from filled Excel files.

Dual-schema support (legacy vs v3)
-----------------------------------
The script supports two annotation sheet schemas because the project evolved
from a boolean "is the rule visible in this view?" design to a richer
"visible + per-view status" design:

1. Legacy schema (front/side/back boolean columns):
   Columns: sample_id, rule_id, value, front, side, back, result, reason
   front/side/back values: "TRUE" or "FALSE"
   Used in early trial annotations before the v3 schema was introduced.

2. V3 visible/status schema:
   Columns: sample_id, rule_id, value, front_visible, front_status,
            side_visible, side_status, back_visible, back_status, result
   <view>_visible values: "visible" or "invisible"
   <view>_status values: "correct", "wrong color", "wrong material", "wrong shape",
                         "extra" (for visible), or "correct", "wrong invisible"
                         (for invisible)
   This is the current production schema.

The detect_schema() function inspects the header row and returns the schema
name. All downstream logic branches on schema to apply the correct validation
rules (qc_legacy vs qc_v3). Both schemas produce the same agent_inputs.jsonl
and merged_annotations.jsonl output shapes; only the row-level QC differs.

XLSX parsing in stdlib-only mode
---------------------------------
The script reads .xlsx files without openpyxl so it can run in minimal
environments (e.g. annotation review containers without Python deps).

Algorithm:
  1. Treat the .xlsx file as a ZIP archive (zipfile.ZipFile).
  2. Parse xl/sharedStrings.xml to build the shared string table (an indexed
     list of cell string values used by cells with type="s").
  3. Parse xl/workbook.xml and xl/_rels/workbook.xml.rels to find the first
     sheet's XML path (usually xl/worksheets/sheet1.xml).
  4. Parse the sheet XML and extract <row>/<c> elements. Each <c> has:
       - r attribute (cell reference like "B3")
       - t attribute (type: "s" for shared string, "inlineStr" for inline, etc.)
       - <v> child (value node for shared string index or direct value)
       - <is> child (inline string node for inlineStr cells)
  5. Map column letters to 0-based indices using column_index().
  6. Build row lists by inserting "" for skipped columns (handles sparse rows).
  7. The first row is the header; remaining rows are data rows.

This approach is sufficient for the annotation workbooks which are simple
single-sheet files with no formulas or complex formatting.

The script is intentionally dependency-free: it reads .xlsx files through the
standard-library zip/xml modules so it can run even when openpyxl is unavailable.
It supports both legacy trial sheets with front/side/back boolean columns and
the newer v3 visible/status split columns.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


XML_NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
JSON_SUFFIX = ".json"
LEGACY_COLUMNS = ["sample_id", "rule_id", "value", "front", "side", "back", "result", "reason"]
V3_COLUMNS = [
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
LEGACY_VIEW_VALUES = {"TRUE", "FALSE"}
RESULT_VALUES = {"correct", "wrong"}
VISIBLE_VALUES = {"visible", "invisible"}
VISIBLE_STATUS_VALUES = {"correct", "wrong color", "wrong material", "wrong shape", "extra"}
INVISIBLE_STATUS_VALUES = {"correct", "wrong invisible"}
ERROR_STATUSES = {"wrong color", "wrong material", "wrong shape", "extra", "wrong invisible"}


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the annotation product builder.

    Returns:
        Parsed namespace with fields:
          input_dir     -- root directory containing category/sample/*.xlsx files
          output_dir    -- directory for generated products
          copy_inputs   -- if True, copy each selected sample folder to output_dir/source_inputs
          include_empty -- if True, include empty template workbooks in the manifest
                          (they still won't contribute annotation rows)
    """
    parser = argparse.ArgumentParser(
        description="Merge filled annotation .xlsx files into agent inputs, gold labels, QC report, and sample summary."
    )
    parser.add_argument("--input-dir", type=Path, required=True, help="Root directory containing category/sample/*.xlsx files.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output directory for generated products.")
    parser.add_argument(
        "--copy-inputs",
        action="store_true",
        help="Copy each selected sample folder into output_dir/source_inputs for preview packages.",
    )
    parser.add_argument(
        "--include-empty",
        action="store_true",
        help="Include empty template workbooks in the manifest. Empty sheets never add annotation rows.",
    )
    return parser.parse_args()


def column_index(cell_ref: str) -> int:
    """Convert an Excel cell reference (e.g. "C5") to a 0-based column index.

    Algorithm:
      1. Extract the letter prefix from the cell reference (ignoring digits).
      2. Treat the letters as a base-26 number where A=1, B=2, ..., Z=26.
      3. Return the 0-based index (so "A" -> 0, "B" -> 1, "AA" -> 26, etc.).

    Args:
        cell_ref: Excel cell reference string like "A1", "B3", "AA12".

    Returns:
        0-based column index (int). "A1" returns 0, "C5" returns 2.
    """
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    index = 0
    for letter in letters:
        index = index * 26 + ord(letter.upper()) - 64
    return index - 1


def read_xlsx_rows(path: Path) -> list[list[str]]:
    """Read an .xlsx file using stdlib zipfile and xml.etree and return row lists.

    This is the stdlib-only XLSX parser described in the module docstring.
    It reads the shared string table, locates the first sheet via the workbook
    relationships, parses the sheet XML, and builds a list of row lists where
    each cell is a string (with empty strings for skipped columns).

    Args:
        path: Path to an .xlsx file.

    Returns:
        List of row lists. Each row is a list of cell strings (with "" for empty
        cells or cells that don't exist in sparse rows). Returns an empty list
        if the workbook has no sheets or the structure is unrecognised.
    """
    with zipfile.ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("a:si", XML_NS):
                shared_strings.append("".join(text.text or "" for text in item.findall(".//a:t", XML_NS)))

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in relationships.findall("rel:Relationship", XML_NS)}
        sheet = workbook.find(".//a:sheet", XML_NS)
        if sheet is None:
            return []

        rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        if not rel_id:
            return []
        target = rel_map[rel_id].lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target

        worksheet = ET.fromstring(archive.read(target))
        rows: list[list[str]] = []
        for row in worksheet.findall(".//a:sheetData/a:row", XML_NS):
            values: list[str] = []
            for cell in row.findall("a:c", XML_NS):
                index = column_index(cell.attrib.get("r", "A1"))
                while len(values) < index:
                    values.append("")
                value = cell_value(cell, shared_strings)
                values.append(value.strip())
            rows.append(values)
        return rows


def cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    """Extract the text value from an Excel cell XML element.

    Handles three cell types:
      - type="s": shared string (value is an index into shared_strings)
      - type="inlineStr": inline string (text is in <is><t> child elements)
      - default: direct value in <v> element (numeric, formula result, etc.)

    Args:
        cell: An <c> XML element from the sheet XML.
        shared_strings: The shared string table loaded from xl/sharedStrings.xml.

    Returns:
        String value of the cell. Returns "" for empty cells or unrecognised types.
    """
    cell_type = cell.attrib.get("t")
    value_node = cell.find("a:v", XML_NS)
    inline_node = cell.find("a:is", XML_NS)
    if cell_type == "s" and value_node is not None and value_node.text is not None:
        return shared_strings[int(value_node.text)]
    if cell_type == "inlineStr" and inline_node is not None:
        return "".join(text.text or "" for text in inline_node.findall(".//a:t", XML_NS))
    if value_node is not None and value_node.text is not None:
        return value_node.text
    return ""


def detect_schema(header: list[str]) -> str | None:
    """Detect whether the workbook uses the v3 visible/status schema or legacy bool schema.

    Detection rules (see module docstring for schema descriptions):
      - If header contains all six v3 columns (front_visible, front_status,
        side_visible, side_status, back_visible, back_status), return
        "v3_visible_status".
      - Else if header contains front, side, back, result (legacy bool columns),
        return "legacy_front_side_back_bool".
      - Else return None (unrecognised schema).

    Args:
        header: List of column names from the first row of the workbook.

    Returns:
        Schema name string or None if the schema cannot be determined.
    """
    columns = set(header)
    if {"front_visible", "front_status", "side_visible", "side_status", "back_visible", "back_status"} <= columns:
        return "v3_visible_status"
    if {"front", "side", "back", "result"} <= columns:
        return "legacy_front_side_back_bool"
    return None


def value_at(row: list[str], index: dict[str, int], column: str) -> str:
    """Extract a single column value from a row list using a column->index map.

    Args:
        row: Raw row list (list of cell strings from read_xlsx_rows).
        index: Dict mapping column name -> 0-based column index.
        column: Column name to extract.

    Returns:
        Stripped string value, or "" if the column is not in the index or the
        row is too short to contain that column.
    """
    position = index.get(column)
    if position is None or position >= len(row):
        return ""
    return row[position].strip()


def has_filled_annotation(rows: list[dict[str, str]], schema: str) -> bool:
    """Check if any row has a non-empty value in at least one annotation column.

    This distinguishes truly empty template workbooks from partially-filled ones.
    A workbook with only sample_id/rule_id/value columns filled (no annotation
    columns) is considered empty and will be skipped unless --include-empty is set.

    Annotation columns checked:
      - v3 schema: front_visible, front_status, side_visible, side_status,
                   back_visible, back_status, result
      - legacy schema: front, side, back, result, reason

    Args:
        rows: List of row dicts from rows_from_workbook().
        schema: Schema name from detect_schema().

    Returns:
        True if at least one row has at least one non-empty annotation column.
    """
    if schema == "v3_visible_status":
        columns = ["front_visible", "front_status", "side_visible", "side_status", "back_visible", "back_status", "result"]
    else:
        columns = ["front", "side", "back", "result", "reason"]
    return any(any(row.get(column, "") for column in columns) for row in rows)


def rows_from_workbook(path: Path) -> tuple[str | None, list[dict[str, str]]]:
    """Parse an .xlsx workbook and return (schema name, list of normalised row dicts).

    Steps:
      1. Call read_xlsx_rows() to get raw row lists.
      2. Treat the first row as the header and detect the schema.
      3. Build a column->index map from the header.
      4. For each data row, extract the relevant columns (based on schema) and
         build a row dict. Add a "source_row" key for QC traceability.
      5. Skip rows where both sample_id and rule_id are empty (blank rows).

    Args:
        path: Path to an .xlsx workbook file.

    Returns:
        Tuple (schema_name, rows). schema_name is None if the schema is not
        recognised or the workbook is empty. rows is a list of dicts where each
        dict has the schema-appropriate columns plus "source_row" (1-based row
        number from the Excel file).
    """
    raw_rows = read_xlsx_rows(path)
    if not raw_rows:
        return None, []
    header = [cell.strip() for cell in raw_rows[0]]
    schema = detect_schema(header)
    if schema is None:
        return None, []
    index = {column: i for i, column in enumerate(header)}
    output_columns = V3_COLUMNS if schema == "v3_visible_status" else LEGACY_COLUMNS
    rows: list[dict[str, str]] = []
    for source_row, row in enumerate(raw_rows[1:], start=2):
        record = {column: value_at(row, index, column) for column in output_columns}
        if not record.get("sample_id") and not record.get("rule_id"):
            continue
        record["source_row"] = str(source_row)
        rows.append(record)
    return schema, rows


def sample_identity(workbook_path: Path, root: Path) -> tuple[str, str]:
    """Infer (category, sample_id) from the workbook's relative path under root.

    Expected directory structure: input_dir/category/sample_id/*.xlsx
    If the path does not have at least 3 parts, falls back to using the parent
    directory name as sample_id and grandparent as category.

    Args:
        workbook_path: Absolute path to the .xlsx file.
        root: Absolute path to the input_dir (the search root).

    Returns:
        Tuple (category, sample_id). category may be "" if the structure is flat.
    """
    relative = workbook_path.relative_to(root)
    if len(relative.parts) >= 3:
        return relative.parts[0], relative.parts[1]
    sample_id = workbook_path.parent.name
    category = workbook_path.parent.parent.name if workbook_path.parent.parent != root.parent else ""
    return category, sample_id


def nearby_paths(sample_dir: Path) -> tuple[list[str], list[str], str]:
    """Find images and JSON files in the sample directory for agent inputs.

    Args:
        sample_dir: Directory containing the annotation workbook and sample assets.

    Returns:
        Tuple (image_paths, json_paths, atomic_rules_path):
          image_paths        -- sorted list of image file paths (str) in the directory
          json_paths         -- sorted list of .json file paths (str) in the directory
          atomic_rules_path  -- the first *atomic_rules.json file found, or the
                               first json_path if no atomic_rules.json exists, or ""
    """
    images = [str(path) for path in sorted(sample_dir.iterdir()) if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES]
    jsons = [str(path) for path in sorted(sample_dir.iterdir()) if path.is_file() and path.suffix.lower() == JSON_SUFFIX]
    atomic = next((path for path in jsons if path.endswith("atomic_rules.json")), jsons[0] if jsons else "")
    return images, jsons, atomic


def load_atomic_rule_ids(sample_dir: Path) -> set[str]:
    """Load the set of known rule IDs from *atomic_rules.json in sample_dir.

    Used for QC warnings: if an annotation row's rule_id is not in this set,
    a "rule_id_not_in_atomic_rules" warning is added.

    Args:
        sample_dir: Directory to search for *atomic_rules.json files.

    Returns:
        Set of rule_id strings. Returns empty set if no atomic_rules.json is
        found or the file cannot be parsed.
    """
    candidates = sorted(sample_dir.glob("*atomic_rules.json"))
    if not candidates:
        return set()
    try:
        data = json.loads(candidates[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return set()
    rules = data.get("atomic_rules") if isinstance(data, dict) else data
    rule_ids: set[str] = set()
    if isinstance(rules, list):
        for item in rules:
            if isinstance(item, dict):
                for key in ("rule_id", "id", "name"):
                    if item.get(key):
                        rule_ids.add(str(item[key]))
                        break
    return rule_ids


def qc_legacy(row: dict[str, str], known_rule_ids: set[str]) -> tuple[str, str, str]:
    """Run QC checks on a single legacy-schema annotation row.

    Legacy schema required columns: sample_id, rule_id, value, front, side, back, result.
    front/side/back values must be "TRUE" or "FALSE".
    result must be in RESULT_VALUES ("correct" or "wrong").
    If result=="wrong" and reason is empty, a warning is added (not a hard failure).

    Args:
        row: Annotation row dict from the workbook.
        known_rule_ids: Set of valid rule IDs for this sample (from atomic_rules.json).

    Returns:
        Tuple (qc_status, issues_str, warnings_str):
          qc_status    -- "FAIL", "WARN", or "PASS"
          issues_str   -- semicolon-joined hard validation failures
          warnings_str -- semicolon-joined soft validation warnings
    """
    issues: list[str] = []
    warnings: list[str] = []
    for column in ["sample_id", "rule_id", "value", "front", "side", "back", "result"]:
        if not row.get(column):
            issues.append(f"missing_{column}")
    for column in ["front", "side", "back"]:
        if row.get(column) and row[column] not in LEGACY_VIEW_VALUES:
            issues.append(f"invalid_{column}:{row[column]}")
    if row.get("result") and row["result"] not in RESULT_VALUES:
        issues.append(f"invalid_result:{row['result']}")
    if row.get("result") == "wrong" and not row.get("reason"):
        warnings.append("wrong_without_reason")
    if known_rule_ids and row.get("rule_id") not in known_rule_ids:
        warnings.append("rule_id_not_in_atomic_rules")
    return qc_status(issues, warnings), ";".join(issues), ";".join(warnings)


def qc_v3(row: dict[str, str], known_rule_ids: set[str]) -> tuple[str, str, str]:
    """Run QC checks on a single v3-schema annotation row.

    V3 schema required columns: sample_id, rule_id, value, front_visible,
    front_status, side_visible, side_status, back_visible, back_status, result.

    Per-row checks:
      - All required columns are non-empty.
      - <view>_visible is in VISIBLE_VALUES ("visible" or "invisible").
      - If visible=="visible", <view>_status is in VISIBLE_STATUS_VALUES.
      - If visible=="invisible", <view>_status is in INVISIBLE_STATUS_VALUES.
      - result is in RESULT_VALUES.
      - Cross-view consistency: result must match the expected value computed
        from per-view statuses (if any status is in ERROR_STATUSES, expected
        result is "wrong"; otherwise "correct").

    Args:
        row: Annotation row dict from the workbook.
        known_rule_ids: Set of valid rule IDs for this sample (from atomic_rules.json).

    Returns:
        Tuple (qc_status, issues_str, warnings_str):
          qc_status    -- "FAIL", "WARN", or "PASS"
          issues_str   -- semicolon-joined hard validation failures
          warnings_str -- semicolon-joined soft validation warnings
    """
    issues: list[str] = []
    warnings: list[str] = []
    for column in V3_COLUMNS:
        if not row.get(column):
            issues.append(f"missing_{column}")
    status_values = []
    for view in ["front", "side", "back"]:
        visible = row.get(f"{view}_visible", "")
        status = row.get(f"{view}_status", "")
        status_values.append(status)
        if visible and visible not in VISIBLE_VALUES:
            issues.append(f"invalid_{view}_visible:{visible}")
        if visible == "visible" and status and status not in VISIBLE_STATUS_VALUES:
            issues.append(f"invalid_{view}_status_for_visible:{status}")
        if visible == "invisible" and status and status not in INVISIBLE_STATUS_VALUES:
            issues.append(f"invalid_{view}_status_for_invisible:{status}")
    expected = "wrong" if any(status in ERROR_STATUSES for status in status_values) else "correct"
    if row.get("result") and row["result"] not in RESULT_VALUES:
        issues.append(f"invalid_result:{row['result']}")
    elif row.get("result") and row["result"] != expected:
        issues.append(f"result_mismatch_expected_{expected}")
    if known_rule_ids and row.get("rule_id") not in known_rule_ids:
        warnings.append("rule_id_not_in_atomic_rules")
    return qc_status(issues, warnings), ";".join(issues), ";".join(warnings)


def qc_status(issues: list[str], warnings: list[str]) -> str:
    """Compute QC status string from issue and warning lists.

    Args:
        issues: List of hard validation failures.
        warnings: List of soft validation warnings.

    Returns:
        "FAIL" if issues is non-empty, "WARN" if only warnings, else "PASS".
    """
    if issues:
        return "FAIL"
    if warnings:
        return "WARN"
    return "PASS"


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    """Write records to a UTF-8-with-BOM CSV file with dynamically-discovered columns.

    Column order is determined by the order in which keys first appear across
    all records. Parent directories are created if needed.

    Args:
        path: Destination CSV file path.
        records: List of row dicts to write.
    """
    columns: list[str] = []
    for record in records:
        for key in record:
            if key not in columns:
                columns.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(records)


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """Write records as UTF-8 JSON Lines (one JSON object per line).

    Args:
        path: Destination .jsonl file path.
        records: List of dicts to write (each becomes one line).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_products(input_dir: Path, output_dir: Path, copy_inputs: bool, include_empty: bool) -> dict[str, Any]:
    """Discover workbooks, run QC, and write all output products.

    Algorithm:
      1. Recursively find all .xlsx files under input_dir.
      2. For each workbook, parse it with rows_from_workbook().
      3. Skip workbooks with unrecognised schema or no filled annotations
         (unless --include-empty is set).
      4. Infer category/sample_id from the workbook path.
      5. Load the atomic_rule_ids set for QC warnings.
      6. Run schema-appropriate QC (qc_legacy or qc_v3) on each row.
      7. Build manifest entry, agent_inputs entry, and annotation rows.
      8. If --copy-inputs is set, copy the entire sample directory to
         output_dir/source_inputs/category/sample_id.
      9. Aggregate all rows and write output files:
           - merged_annotations.jsonl
           - agent_inputs.jsonl
           - annotation_qc_report.csv
           - sample_summary.csv
           - selected_samples_manifest.csv
           - summary.json

    Args:
        input_dir: Root directory containing category/sample/*.xlsx files.
        output_dir: Destination directory for all products.
        copy_inputs: If True, copy each sample folder to output_dir/source_inputs.
        include_empty: If True, include empty template workbooks in the manifest
                      (they still won't add annotation rows).

    Returns:
        Summary dict with run statistics (also written to summary.json).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    qc_rows: list[dict[str, Any]] = []
    agent_inputs: list[dict[str, Any]] = []
    schema_counts: Counter[str] = Counter()

    for workbook_path in sorted(input_dir.rglob("*.xlsx")):
        schema, workbook_rows = rows_from_workbook(workbook_path)
        if schema is None:
            continue
        if not workbook_rows or (not include_empty and not has_filled_annotation(workbook_rows, schema)):
            continue

        category, sample_id = sample_identity(workbook_path, input_dir)
        sample_dir = workbook_path.parent
        images, jsons, atomic_rules_path = nearby_paths(sample_dir)
        known_rule_ids = load_atomic_rule_ids(sample_dir)
        schema_counts[schema] += 1

        if copy_inputs:
            copied_dir = output_dir / "source_inputs" / category / sample_id
            if copied_dir.exists():
                shutil.rmtree(copied_dir)
            shutil.copytree(sample_dir, copied_dir)
        else:
            copied_dir = None

        row_count = 0
        for row in workbook_rows:
            record = {
                "category": category,
                "sample_id": row.get("sample_id") or sample_id,
                **{key: value for key, value in row.items() if key not in {"sample_id", "source_row"}},
                "source_xlsx": str(workbook_path),
                "source_row": row.get("source_row", ""),
                "schema_version": schema,
            }
            annotations.append(record)
            row_count += 1
            if schema == "v3_visible_status":
                status, issues, warnings = qc_v3(record, known_rule_ids)
            else:
                status, issues, warnings = qc_legacy(record, known_rule_ids)
            qc_rows.append({**record, "qc_status": status, "issues": issues, "warnings": warnings})

        manifest.append(
            {
                "category": category,
                "sample_id": sample_id,
                "source_folder": str(sample_dir),
                "copied_folder": str(copied_dir or ""),
                "annotation_xlsx": str(workbook_path),
                "image_count": len(images),
                "json_count": len(jsons),
                "rule_rows": row_count,
                "schema_version": schema,
            }
        )
        agent_inputs.append(
            {
                "sample_id": sample_id,
                "category": category,
                "task": "anime_ip_merchandise_supervision",
                "images": images,
                "atomic_rules_path": atomic_rules_path,
                "annotation_source_xlsx": str(workbook_path),
                "expected_output_contract": {
                    "unit": "rule_level",
                    "schema_version": schema,
                    "fields": V3_COLUMNS if schema == "v3_visible_status" else LEGACY_COLUMNS,
                },
            }
        )

    sample_summary = summarize_samples(annotations, qc_rows)
    write_jsonl(output_dir / "merged_annotations.jsonl", annotations)
    write_jsonl(output_dir / "agent_inputs.jsonl", agent_inputs)
    write_csv(output_dir / "annotation_qc_report.csv", qc_rows)
    write_csv(output_dir / "sample_summary.csv", sample_summary)
    write_csv(output_dir / "selected_samples_manifest.csv", manifest)

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "xlsx_files_used": len(manifest),
        "samples": len({(row["category"], row["sample_id"]) for row in annotations}),
        "rule_rows": len(annotations),
        "schema_counts": dict(sorted(schema_counts.items())),
        "result_counts": dict(sorted(Counter(str(row.get("result", "")) for row in annotations).items())),
        "qc_counts": dict(sorted(Counter(str(row.get("qc_status", "")) for row in qc_rows).items())),
        "core_outputs": [
            "merged_annotations.jsonl",
            "agent_inputs.jsonl",
            "annotation_qc_report.csv",
            "sample_summary.csv",
        ],
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def summarize_samples(annotations: list[dict[str, Any]], qc_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate annotation and QC statistics by (category, sample_id).

    Args:
        annotations: List of all annotation row dicts (from merged_annotations.jsonl).
        qc_rows: List of all QC row dicts (from annotation_qc_report.csv).

    Returns:
        List of sample summary dicts, one per unique (category, sample_id) pair.
        Each dict contains: category, sample_id, rule_rows, correct_rows,
        wrong_rows, qc_pass_rows, qc_warn_rows, qc_fail_rows, schema_version.
    """
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    grouped_qc: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in annotations:
        grouped[(str(row["category"]), str(row["sample_id"]))].append(row)
    for row in qc_rows:
        grouped_qc[(str(row["category"]), str(row["sample_id"]))].append(row)

    summary: list[dict[str, Any]] = []
    for key, rows in sorted(grouped.items()):
        qc_for_sample = grouped_qc[key]
        summary.append(
            {
                "category": key[0],
                "sample_id": key[1],
                "rule_rows": len(rows),
                "correct_rows": sum(1 for row in rows if row.get("result") == "correct"),
                "wrong_rows": sum(1 for row in rows if row.get("result") == "wrong"),
                "qc_pass_rows": sum(1 for row in qc_for_sample if row.get("qc_status") == "PASS"),
                "qc_warn_rows": sum(1 for row in qc_for_sample if row.get("qc_status") == "WARN"),
                "qc_fail_rows": sum(1 for row in qc_for_sample if row.get("qc_status") == "FAIL"),
                "schema_version": rows[0].get("schema_version", ""),
            }
        )
    return summary


def main() -> None:
    """Entry point: parse args, validate input_dir, build products, print summary."""
    args = parse_args()
    if not args.input_dir.exists():
        raise SystemExit(f"input directory does not exist: {args.input_dir}")
    summary = build_products(args.input_dir, args.output_dir, args.copy_inputs, args.include_empty)
    print(json.dumps({"status": "finished", **summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
