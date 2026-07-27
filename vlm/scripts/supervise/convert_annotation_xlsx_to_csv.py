"""Convert annotation .xlsx workbooks to CSV without assuming final workflow.

WHY STDLIB-ONLY XLSX PARSING?
------------------------------
This converter intentionally uses only Python's standard library (zipfile,
xml.etree, csv) and avoids third-party packages like openpyxl or pandas for
several reasons:

1. **Zero installation friction** – the script runs immediately on any Python
   3.7+ installation without pip-installing dependencies.
2. **Predictable parsing** – openpyxl's auto-type-conversion (dates, numbers,
   formulas) can introduce subtle data loss when annotator intent differs from
   Excel's inference.  Reading raw XML gives string-only cells, preserving
   exactly what the annotator typed.
3. **Workflow flexibility** – early in the project we do not yet know the final
   annotation schema or which columns will be present.  A generic converter that
   reads "whatever is in the first worksheet" and preserves the original header
   allows us to inspect CSVs and iterate on the annotation template without
   rewriting parser code each time.

XLSX FILE STRUCTURE (PRIMER)
-----------------------------
An .xlsx file is a ZIP archive containing XML files:

* ``xl/workbook.xml``       – workbook-level metadata and sheet list.
* ``xl/_rels/workbook.xml.rels`` – relationships mapping sheet IDs to their
  XML file paths (e.g. ``worksheets/sheet1.xml``).
* ``xl/worksheets/sheet1.xml`` – the actual cell grid for the first sheet.
* ``xl/sharedStrings.xml``  – a centralised string table.  Cells of type "s"
  (shared string) store an integer index into this table rather than inline
  text, which saves space when the same string appears many times.

This script reads the first worksheet only (annotators typically fill one sheet
per workbook) and reconstructs the CSV by combining cell references, shared
string lookups, and inline string nodes.

SHARED STRINGS TABLE LOOKUP
----------------------------
Most text cells in Excel workbooks use type ``t="s"`` and store an index (e.g.
``<v>42</v>``) rather than the actual string.  The text is looked up in
``xl/sharedStrings.xml``, which contains a flat list of ``<si>`` (string item)
elements.  Each ``<si>`` may have multiple ``<t>`` (text) nodes for rich-text
runs; we concatenate all ``<t>`` node texts to reconstruct the full cell value.

Inline strings (``t="inlineStr"``) store their text directly in the cell as an
``<is>`` (inline string) element; these are rare but supported here.  Numeric
and date cells (no type attribute or ``t="n"``) store their value in ``<v>``
as a string and are returned as-is without type conversion.

COLUMN HEADER DETECTION HEURISTICS
-----------------------------------
The script assumes the first row of each worksheet is the header.  It emits a
``conversion_manifest.csv`` that records a ``schema_guess`` for each workbook
based on which columns are present:

* ``human_visual_findings``       – has ``finding_id``, ``view``, and either
  ``feature_key`` or ``element_name``.
* ``atomic_rule_audit``           – has ``rule_id``, ``rule_validity``,
  ``atomic_value``.
* ``human_to_atomic_rule_mapping`` – has ``human_finding_id``,
  ``atomic_rule_id``, ``candidate_match_type``.
* ``v3_rule_level``               – has the six view-status columns
  (``front_visible``, ``front_status``, etc.).
* ``unknown``                     – none of the above patterns matched.

This heuristic is deliberately coarse and will be extended as new annotation
schemas are introduced.  It serves as a sanity check during batch conversion
but does not enforce schema — the raw header is always preserved in the output
CSV so consumers can adapt to schema drift.
"""

from __future__ import annotations

import argparse
import csv
import json
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any


# OpenXML namespaces used in .xlsx XML files.  The "a" prefix maps to the main
# spreadsheet namespace; "rel" maps to the relationships namespace.
XML_NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

DEFAULT_OUTPUT_DIR = Path("vlm/tmp/annotation_xlsx_converted")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Define and parse command-line arguments.

    Returns
    -------
    argparse.Namespace
        Parsed argument object.  Key fields:

        * ``input``         – a single .xlsx file, or a directory containing
          .xlsx files.
        * ``output_dir``    – destination directory for converted CSVs.
        * ``recursive``     – when ``input`` is a directory, whether to search
          subdirectories recursively (``**/*.xlsx`` glob).
        * ``include_empty`` – whether to write a CSV file even when the
          worksheet has a header but zero data rows (default False).
    """
    parser = argparse.ArgumentParser(description="Convert annotation xlsx files to CSV.")
    parser.add_argument("--input", type=Path, required=True, help="An .xlsx file or a directory containing .xlsx files.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--recursive", action="store_true", help="Recursively find .xlsx files when --input is a directory.")
    parser.add_argument("--include-empty", action="store_true", help="Write CSV files even when the worksheet has no data rows.")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Excel cell addressing
# ---------------------------------------------------------------------------

def column_index(cell_ref: str) -> int:
    """Convert an Excel column reference (A, B, ..., Z, AA, AB, ...) to a zero-based index.

    Examples:
    * ``A`` → 0
    * ``B`` → 1
    * ``Z`` → 25
    * ``AA`` → 26
    * ``AB`` → 27

    The conversion is base-26 with digits A=1, B=2, ..., Z=26.  This function
    extracts only the letter portion of a full cell reference like ``"B5"`` and
    ignores the row number.

    Parameters
    ----------
    cell_ref:
        Cell reference string, e.g. ``"A1"``, ``"AB42"``, or just ``"C"``.

    Returns
    -------
    int
        Zero-based column index.
    """
    # Extract only alphabetic characters (the column letters).
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    index = 0
    # Process each letter left-to-right as a base-26 digit (A=1, not A=0).
    for letter in letters:
        index = index * 26 + ord(letter.upper()) - 64
    # Convert from 1-based (Excel convention) to 0-based (Python list indexing).
    return index - 1


# ---------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------

def cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    """Extract the display value from a worksheet cell XML element.

    Excel cells have several possible structures depending on type:

    1. **Shared string** (``t="s"``)
         ``<c r="A1" t="s"><v>42</v></c>``
         The ``<v>`` node contains an integer index into the shared strings
         table; this function looks up ``shared_strings[42]`` and returns it.

    2. **Inline string** (``t="inlineStr"``)
         ``<c r="A2" t="inlineStr"><is><t>Hello</t></is></c>``
         The ``<is>`` (inline string) element contains one or more ``<t>``
         text nodes; we concatenate their text content.

    3. **Numeric or untyped** (no ``t`` attribute, or ``t="n"``)
         ``<c r="A3"><v>123.45</v></c>``
         The ``<v>`` node's text is returned as-is (a string representation of
         the number).  We do NOT convert to float/int — preserving strings
         avoids precision loss and allows downstream tools to apply their own
         type logic.

    4. **Empty cell**
         ``<c r="A4" />`` or a cell with no ``<v>`` / ``<is>`` child.
         Returns an empty string.

    Parameters
    ----------
    cell:
        XML Element representing one ``<c>`` (cell) node.
    shared_strings:
        Pre-loaded list of all shared string entries from
        ``xl/sharedStrings.xml``.  Order must match the Excel file's order.

    Returns
    -------
    str
        The cell's display value as a string, or ``""`` if the cell is empty.
    """
    cell_type = cell.attrib.get("t")
    value_node = cell.find("a:v", XML_NS)
    inline_node = cell.find("a:is", XML_NS)

    # Case 1: shared string cell — look up in the shared strings table.
    if cell_type == "s" and value_node is not None and value_node.text is not None:
        return shared_strings[int(value_node.text)]

    # Case 2: inline string cell — concatenate all <t> text nodes.
    if cell_type == "inlineStr" and inline_node is not None:
        return "".join(text.text or "" for text in inline_node.findall(".//a:t", XML_NS))

    # Case 3: numeric or untyped cell — return <v> text as-is.
    if value_node is not None and value_node.text is not None:
        return value_node.text

    # Case 4: empty cell (no value, no inline string).
    return ""


def read_xlsx_rows(path: Path) -> list[list[str]]:
    """Parse an .xlsx file and extract all rows from the first worksheet.

    This function:
    1. Opens the .xlsx file as a ZIP archive.
    2. Reads ``xl/sharedStrings.xml`` if present and builds the shared string
       lookup table.
    3. Reads ``xl/workbook.xml`` and ``xl/_rels/workbook.xml.rels`` to find the
       first sheet's XML file path.
    4. Reads the worksheet XML and iterates over all ``<row>`` elements.
    5. For each row, extracts all ``<c>`` (cell) elements, decodes their values
       using ``cell_value``, and inserts them into the correct column positions
       (handling sparse cell references like ``A1, C1`` with an implicit empty
       ``B1`` in between).

    Rows and cells are returned exactly as they appear in the XML; no blank-row
    trimming or column normalisation is applied.  Empty cells within a row are
    represented as ``""``.

    Parameters
    ----------
    path:
        Path to the .xlsx workbook file.

    Returns
    -------
    list[list[str]]
        One list per row; each inner list contains string cell values in column
        order.  Returns an empty list if the workbook has no sheets or the
        first sheet is empty.
    """
    with zipfile.ZipFile(path) as archive:
        # Step 1: load the shared strings table (if it exists).
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            # Each <si> (string item) may contain multiple <t> (text) nodes
            # for rich-text formatting; concatenate all text fragments.
            for item in root.findall("a:si", XML_NS):
                shared_strings.append("".join(text.text or "" for text in item.findall(".//a:t", XML_NS)))

        # Step 2: find the first sheet's XML file path.
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        # Build a map from relationship IDs to their target paths.
        rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in relationships.findall("rel:Relationship", XML_NS)}
        # Find the first <sheet> element in the workbook.
        sheet = workbook.find(".//a:sheet", XML_NS)
        if sheet is None:
            return []
        # Extract the relationship ID attribute (namespace prefix required).
        rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        if not rel_id:
            return []
        # Resolve the target path and normalise it to always start with "xl/".
        target = rel_map[rel_id].lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target

        # Step 3: parse the worksheet XML.
        worksheet = ET.fromstring(archive.read(target))
        rows: list[list[str]] = []
        # Iterate over all <row> elements in <sheetData>.
        for row in worksheet.findall(".//a:sheetData/a:row", XML_NS):
            values: list[str] = []
            # Iterate over all <c> (cell) elements in this row.
            for cell in row.findall("a:c", XML_NS):
                # Extract the cell reference (e.g. "B5") and compute its column index.
                index = column_index(cell.attrib.get("r", "A1"))
                # Pad the values list with empty strings if there are sparse cells.
                while len(values) < index:
                    values.append("")
                # Decode the cell value and append; strip whitespace for cleaner CSVs.
                values.append(cell_value(cell, shared_strings).strip())
            rows.append(values)
        return rows


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_xlsx_files(path: Path, recursive: bool) -> list[Path]:
    """Find all .xlsx files under the given path.

    If ``path`` is a file, return a one-element list (or empty list if the
    extension is not .xlsx).  If ``path`` is a directory, glob for .xlsx files,
    optionally recursively.  Temporary Excel lock files (names starting with
    ``~$``) are excluded.

    Parameters
    ----------
    path:
        A file or directory path.
    recursive:
        Whether to search subdirectories when ``path`` is a directory.

    Returns
    -------
    list[Path]
        Sorted list of .xlsx file paths.
    """
    if path.is_file():
        return [path] if path.suffix.lower() == ".xlsx" else []
    pattern = "**/*.xlsx" if recursive else "*.xlsx"
    # Exclude Excel temporary lock files (start with ~$).
    return sorted(item for item in path.glob(pattern) if item.is_file() and not item.name.startswith("~$"))


# ---------------------------------------------------------------------------
# Schema detection
# ---------------------------------------------------------------------------

def detect_schema(header: list[str]) -> str:
    """Guess the annotation schema based on which columns are present.

    This heuristic checks for known column-name combinations that identify
    specific annotation templates.  The guess is coarse and will not catch
    all cases, but it provides a quick sanity check during batch conversion.

    Schema detection patterns:

    * ``human_visual_findings`` – has ``finding_id``, ``view``, and either
      ``feature_key`` or ``element_name``.
    * ``atomic_rule_audit``     – has ``rule_id``, ``rule_validity``,
      ``atomic_value``.
    * ``human_to_atomic_rule_mapping`` – has ``human_finding_id``,
      ``atomic_rule_id``, ``candidate_match_type``.
    * ``v3_rule_level``         – has all six view-status columns
      (``front_visible``, ``front_status``, etc.).
    * ``unknown``               – none of the above matched.

    Parameters
    ----------
    header:
        List of column names (first row of the worksheet).

    Returns
    -------
    str
        One of the schema identifiers listed above, or ``"unknown"``.
    """
    # Convert to a set for O(1) membership testing and strip whitespace.
    columns = {item.strip() for item in header}

    # Check each known schema in priority order (most specific first).
    if {"finding_id", "view"} <= columns and ({"feature_key"} <= columns or {"element_name"} <= columns):
        return "human_visual_findings"
    if {"rule_id", "rule_validity", "atomic_value"} <= columns:
        return "atomic_rule_audit"
    if {"human_finding_id", "atomic_rule_id", "candidate_match_type"} <= columns:
        return "human_to_atomic_rule_mapping"
    if {"front_visible", "front_status", "side_visible", "side_status", "back_visible", "back_status"} <= columns:
        return "v3_rule_level"

    return "unknown"


# ---------------------------------------------------------------------------
# Row parsing
# ---------------------------------------------------------------------------

def rows_to_dicts(rows: list[list[str]]) -> tuple[list[str], list[dict[str, str]]]:
    """Convert a raw row list (first row = header) into a list of row dicts.

    The first row is treated as the column header; subsequent rows are zipped
    with the header to form dicts.  Rows that are entirely blank (all empty
    strings after stripping) are skipped.

    Cells beyond the header length are silently dropped (this can happen if
    an annotator added extra columns mid-sheet without updating the header).
    Missing cells (row shorter than header) are filled with empty strings.

    Parameters
    ----------
    rows:
        Raw row list as returned by ``read_xlsx_rows``.

    Returns
    -------
    tuple[list[str], list[dict[str, str]]]
        ``(header, records)`` where:
        * ``header`` is the stripped column name list from the first row.
        * ``records`` is a list of dicts (one per data row), keyed by column name.
    """
    if not rows:
        return [], []
    # The first row is the header; strip whitespace from each column name.
    header = [cell.strip() for cell in rows[0]]
    records: list[dict[str, str]] = []
    for row in rows[1:]:
        # Build a dict by zipping header with this row; pad with "" if the row is short.
        record = {column: (row[index].strip() if index < len(row) else "") for index, column in enumerate(header)}
        # Skip entirely blank rows (can occur when an annotator deletes content but not the row).
        if any(record.values()):
            records.append(record)
    return header, records


def safe_output_name(path: Path) -> str:
    """Generate a CSV output filename from the .xlsx input path.

    Simply replaces the .xlsx extension with .csv, preserving the base name.
    No path sanitisation or collision resolution is applied — if two .xlsx
    files have the same name (but different directories) and --recursive is
    used, the last one wins.  This is acceptable for annotation conversion
    where file names are typically unique.

    Parameters
    ----------
    path:
        The .xlsx input file path.

    Returns
    -------
    str
        The base filename with .csv extension (no directory component).
    """
    return path.with_suffix(".csv").name


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
        Ordered column names (defines header row and dict key extraction order).
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
        Output JSON file path.
    payload:
        Any JSON-serialisable Python object.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Find .xlsx files, convert each to CSV, and write a conversion manifest.

    For each .xlsx file found:
    1. Parse the first worksheet into a raw row list.
    2. Treat the first row as the header and convert subsequent rows to dicts.
    3. Detect the likely annotation schema based on column names.
    4. Write the CSV file (unless the worksheet is empty and --include-empty
       is False).
    5. Record metadata (schema guess, row/column counts, paths) in a manifest.

    After processing all files, write two summary outputs:
    * ``conversion_manifest.csv`` – one row per .xlsx file, listing its output
      path, schema guess, and row/column counts.
    * ``summary.json`` – high-level statistics and the full manifest as a JSON array.

    Both outputs are written even if no .xlsx files are found (dry-run mode).
    """
    args = parse_args()
    files = find_xlsx_files(args.input, args.recursive)
    manifest: list[dict[str, Any]] = []

    for xlsx_path in files:
        # Step 1-2: parse the workbook and split header from data rows.
        rows = read_xlsx_rows(xlsx_path)
        header, records = rows_to_dicts(rows)

        # Step 3: guess the schema based on column names.
        schema = detect_schema(header)

        # Step 4: determine output CSV path and whether to write it.
        output_path = args.output_dir / safe_output_name(xlsx_path)
        wrote_csv = bool(records or args.include_empty)
        if wrote_csv:
            write_csv(output_path, records, header)

        # Step 5: record metadata for the manifest.
        manifest.append(
            {
                "source_xlsx": str(xlsx_path),
                "output_csv": str(output_path) if wrote_csv else "",
                "schema_guess": schema,
                "columns": len(header),
                "data_rows": len(records),
                "wrote_csv": wrote_csv,
            }
        )

    # Build the summary dict with top-level counts.
    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "input": str(args.input),
        "output_dir": str(args.output_dir),
        "xlsx_files": len(files),
        "csv_files_written": sum(1 for row in manifest if row["wrote_csv"]),
    }

    # Write both manifest outputs.
    write_csv(
        args.output_dir / "conversion_manifest.csv",
        manifest,
        ["source_xlsx", "output_csv", "schema_guess", "columns", "data_rows", "wrote_csv"],
    )
    write_json(args.output_dir / "summary.json", {**summary, "manifest": manifest})

    # Print a machine-readable one-liner for Claude Code to capture.
    print(json.dumps({"status": "finished", **summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
